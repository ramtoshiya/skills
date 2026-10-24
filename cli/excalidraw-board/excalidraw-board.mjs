#!/usr/bin/env node
import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { openRooms } from "./rooms.mjs";
import { createScene, loadScene, writeScene } from "./protocol.mjs";
import { compact } from "./scene.mjs";
import { uploadImage, uploadImages } from "./images.mjs";

const help = `excalidraw-board (proof of concept, Node.js 24.21+)
  room create <name>
  room import --name <name> --stdin          read a room link from stdin
  room import <link> --name <name>           link also enters shell history
  room list [name-prefix]
  room link --name <name> | --id <prefix>     prints the secret room link
  read --name <name> | --id <prefix> [--full] [--outline | --frame <id> | --group <id> | --ids a,b]
  write --name <name> | --id <prefix>         read {add:[],update:[],delete:[]} from stdin
  image --name <name> | --id <prefix> --file <png-or-jpeg> [--element-id <id>] [--x <n>] [--y <n>] [--width <n>] [--frame <id>]
  images --name <name> | --id <prefix> [--concurrency <1-8>]   read {images:[{file,elementId,x,y,width,frame}]} from stdin
`;

function input() {
  const value = readFileSync(0, "utf8");
  if (Buffer.byteLength(value) > 5000000) throw new Error("Input exceeds 5 MB");
  return value;
}
function argumentsFor(args, options, positionalCount = 0) {
  let parsed;
  try { parsed = parseArgs({ args, strict: true, allowPositionals: true, options }); }
  catch { throw new Error("Invalid command options. Run excalidraw-board --help"); }
  if (parsed.positionals.length > positionalCount) throw new Error("Unexpected positional argument");
  return parsed;
}
const selectors = { name: { type: "string" }, id: { type: "string" } };
function terminalText(value) {
  return String(value).replace(/[\x00-\x1f\x7f-\x9f]/g, character => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
}
const terminalJSON = value => terminalText(JSON.stringify(value));
function selector(values) {
  if (Boolean(values.name) === Boolean(values.id)) throw new Error("Specify exactly one of --name or --id");
  return { name: values.name, id: values.id };
}
function parseLink(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error("Invalid Excalidraw room link"); }
  const match = /^#room=([A-Za-z0-9_-]{1,128}),([A-Za-z0-9_-]{22})$/.exec(url.hash);
  if (url.origin !== "https://excalidraw.com" || url.pathname !== "/" || url.search || url.username || url.password || !match) throw new Error("Invalid Excalidraw room link");
  if (Buffer.from(match[2], "base64url").toString("base64url") !== match[2]) throw new Error("Invalid room key encoding");
  return { id: match[1], key: match[2] };
}
function validName(name) {
  if (typeof name !== "string" || !name.trim() || /[\x00-\x1f\x7f]/.test(name)) throw new Error("Expected a nonempty name without control characters");
  return name;
}

async function main(args) {
  if (!args.length || ["help", "--help", "-h"].includes(args[0])) { console.log(help); return; }
  if (args[0] === "--version") { console.log("excalidraw-board 0.1.0-poc"); return; }
  const registry = openRooms();
  try {
    if (args[0] === "room") {
      const command = args[1];
      if (command === "create") {
        const { positionals } = argumentsFor(args.slice(2), {}, 1);
        const name = validName(positionals[0]);
        const room = { name, id: randomBytes(10).toString("hex"), key: randomBytes(16).toString("base64url") };
        const saved = await createScene(room);
        registry.add(room);
        registry.resolve({ id: room.id });
        console.log(terminalJSON({ name, id: room.id, revision: saved.revision }));
      } else if (command === "import") {
        const { values, positionals } = argumentsFor(args.slice(2), { name: { type: "string" }, stdin: { type: "boolean" } }, 1);
        if (Boolean(values.stdin) === Boolean(positionals.length)) throw new Error("Use either --stdin or a single room link");
        const room = { ...parseLink(values.stdin ? input().trim() : positionals[0]), name: validName(values.name) };
        await loadScene(room);
        const stored = registry.add(room);
        registry.resolve({ id: stored.id });
        console.log(terminalJSON({ name: stored.name, id: stored.id }));
      } else if (command === "list") {
        const { positionals } = argumentsFor(args.slice(2), {}, 1);
        console.log("NAME\tID\tLAST USED");
        for (const room of registry.list(positionals[0] || "")) console.log(`${terminalText(room.name)}\t${terminalText(room.short_id)}\t${new Date(room.last_used).toISOString()}`);
      } else if (command === "link") {
        const { values } = argumentsFor(args.slice(2), selectors);
        console.log(registry.link(registry.resolve(selector(values))));
      } else throw new Error("Unknown room command. Run excalidraw-board --help");
    } else if (args[0] === "read") {
      const { values } = argumentsFor(args.slice(1), { ...selectors, full: { type: "boolean" }, outline: { type: "boolean" }, frame: { type: "string" }, group: { type: "string" }, ids: { type: "string" } });
      if ([values.outline, values.frame, values.group, values.ids].filter(value => value !== undefined && value !== false).length > 1) throw new Error("Choose only one read filter");
      const saved = await loadScene(registry.resolve(selector(values)));
      console.log(terminalJSON({ revision: saved.revision }));
      let elements = saved.elements.filter(element => !element.isDeleted);
      if (values.outline) {
        for (const frame of elements.filter(element => ["frame", "magicframe"].includes(element.type))) {
          const count = elements.filter(element => element.frameId === frame.id).length;
          console.log(`frame\t${terminalJSON(frame.id)}\t${terminalJSON(frame.name || "Untitled")}\t${[frame.x, frame.y, frame.width, frame.height].map(terminalJSON).join(",")}\t${count}`);
        }
        const groups = new Map();
        for (const element of elements) {
          const id = element.groupIds?.at(-1);
          if (id && !element.frameId) groups.set(id, [...(groups.get(id) || []), element]);
        }
        for (const [id, members] of groups) {
          const x = Math.min(...members.map(element => element.x));
          const y = Math.min(...members.map(element => element.y));
          const right = Math.max(...members.map(element => element.x + element.width));
          const bottom = Math.max(...members.map(element => element.y + element.height));
          console.log(`group\t${terminalJSON(id)}\t${terminalJSON(members.find(element => element.text)?.text || "Untitled")}\t${[x, y, right - x, bottom - y].map(terminalJSON).join(",")}\t${members.length}`);
        }
      } else {
        if (values.frame) elements = elements.filter(element => element.id === values.frame || element.frameId === values.frame);
        if (values.group) elements = elements.filter(element => element.groupIds?.includes(values.group));
        if (values.ids) { const ids = new Set(values.ids.split(",")); elements = elements.filter(element => ids.has(element.id)); }
        for (const element of elements) console.log(terminalJSON(values.full ? element : compact(element)));
      }
    } else if (args[0] === "images") {
      const { values } = argumentsFor(args.slice(1), { ...selectors, concurrency: { type: "string" } });
      let manifest;
      try { manifest = JSON.parse(input()); } catch { throw new Error("Expected an images manifest on stdin"); }
      if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)
          || Object.keys(manifest).some(key => key !== "images")) throw new Error("Expected an images manifest on stdin");
      const receipt = await uploadImages(registry.resolve(selector(values)), manifest.images,
        { concurrency: values.concurrency === undefined ? 4 : Number(values.concurrency) });
      console.log(terminalJSON(receipt));
      if (receipt.warning) { console.error(receipt.warning); process.exitCode = 2; }
    } else if (args[0] === "image") {
      const { values } = argumentsFor(args.slice(1), { ...selectors,
        file: { type: "string" }, "element-id": { type: "string" }, frame: { type: "string" },
        x: { type: "string" }, y: { type: "string" }, width: { type: "string" },
      });
      if (!values.file) throw new Error("Image needs --file with a PNG or JPEG path");
      const options = { file: values.file, elementId: values["element-id"], frame: values.frame };
      for (const field of ["x", "y", "width"]) {
        if (values[field] !== undefined) {
          if (!values[field].trim() || !Number.isFinite(Number(values[field]))) throw new Error("Image coordinates and width must be finite numbers");
          options[field] = Number(values[field]);
        }
      }
      const receipt = await uploadImage(registry.resolve(selector(values)), options);
      console.log(terminalJSON(receipt));
      if (receipt.warning) { console.error(receipt.warning); process.exitCode = 2; }
    } else if (args[0] === "write") {
      const { values } = argumentsFor(args.slice(1), selectors);
      let batch;
      try { batch = JSON.parse(input()); } catch { throw new Error("Expected a JSON batch on stdin"); }
      const receipt = await writeScene(registry.resolve(selector(values)), batch);
      console.log(terminalJSON(receipt));
      if (receipt.warning) { console.error(receipt.warning); process.exitCode = 2; }
    } else throw new Error("Unknown command. Run excalidraw-board --help");
  } finally { registry.close(); }
}

main(process.argv.slice(2)).catch(error => {
  // Never echo raw arguments, input, URLs, room keys, or network error objects.
  const message = error instanceof Error ? error.message : "Command failed";
  if (error?.receipt) console.log(terminalJSON(error.receipt));
  console.error(terminalText(message.replace(/https?:\/\/\S+/g, "[URL omitted]")));
  process.exitCode = 1;
});

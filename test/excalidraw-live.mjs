// Opt-in service integration check. This creates three disposable remote boards.
import assert from "node:assert/strict";
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

if (process.argv.length !== 3 || process.argv[2] !== "--live") {
  console.error("Pass --live to create three disposable Excalidraw rooms and write test elements.");
  process.exit(1);
}
const root = fileURLToPath(new URL("../", import.meta.url));
const home = mkdtempSync(join(tmpdir(), "excalidraw-live-"));
const env = { ...process.env, HOME: home };
execFileSync("sh", [join(root, "cli/excalidraw-board/install.sh")], { env, stdio: "pipe" });
const bin = join(home, ".local/bin/excalidraw-board");
const outputs = [];
const run = (args, input) => {
  const result = spawnSync(bin, args, { env, input, encoding: "utf8", timeout: 60000 });
  outputs.push(result.stdout || "", result.stderr || "");
  if (result.error || result.status !== 0) throw new Error("Installed CLI command failed. Inspect the private test home.");
  return result.stdout;
};
const rooms = Array.from({ length: 3 }, (_, i) => JSON.parse(run(["room", "create", `poc-${i}`])));

function writer(agent, target, at) {
  return new Promise((resolve, reject) => {
    const program = `
      const {spawn} = require('node:child_process');
      setTimeout(() => {
        const child=spawn(process.argv[1],['write','--id',process.argv[2]],{stdio:['pipe','pipe','pipe']});
        child.stdout.pipe(process.stdout);child.stderr.pipe(process.stderr);
        child.on('error',()=>process.exit(1));child.on('exit',code=>process.exit(code ?? 1));
        child.stdin.end(process.argv[3]);
      }, Math.max(0, Number(process.argv[4])-Date.now()));
    `;
    const batch = { add: Array.from({ length: 10 }, (_, i) => ({ id: `${agent}-${target}-${i}`, type: "rectangle", x: i * 120, y: agent === "A" ? 0 : 100, w: 100, h: 60 })) };
    const child = spawn(process.execPath, ["-e", program, bin, rooms[target].id, JSON.stringify(batch), String(at)], { env, stdio: ["ignore", "pipe", "pipe"] });
    let out = "", err = "";
    child.stdout.on("data", data => { out += data; });
    child.stderr.on("data", data => { err += data; });
    child.on("error", reject);
    child.on("exit", code => {
      outputs.push(out, err);
      if (code !== 0) reject(new Error("Writer failed. Inspect the private test home."));
      else { try { resolve(JSON.parse(out)); } catch (error) { reject(error); } }
    });
  });
}
function read(target) {
  const [header, ...elements] = run(["read", "--id", rooms[target].id, "--full"]).trim().split("\n").map(JSON.parse);
  return { ...header, elements };
}
function checkIds(target) {
  const scene = read(target);
  assert.equal(scene.elements.length, 20);
  const expected = new Set(["A", "B"].flatMap(agent => Array.from({ length: 10 }, (_, i) => `${agent}-${target}-${i}`)));
  assert.deepEqual(new Set(scene.elements.map(element => element.id)), expected);
  return scene;
}
try {
  let at = Date.now() + 1000;
  const sameRoom = await Promise.all([writer("A", 0, at), writer("B", 0, at)]);
  const before = checkIds(0);
  const noOp = JSON.parse(run(["write", "--id", rooms[0].id], JSON.stringify({ update: [{ id: "A-0-0", x: 0 }] })));
  assert.deepEqual(noOp.changed, []);
  assert.equal(noOp.revision, before.revision);
  at = Date.now() + 1000;
  const multiRoom = await Promise.all([1, 2].flatMap(target => [writer("A", target, at), writer("B", target, at)]));
  for (const target of [1, 2]) checkIds(target);
  // The relay and persistence are independent. This check observes an encrypted relay peer, not a browser render.
  const { RoomSocket, writeScene, loadScene } = await import("../cli/excalidraw-board/protocol.mjs");
  const { openRooms } = await import("../cli/excalidraw-board/rooms.mjs");
  const registry = openRooms(join(home, ".local/state/excalidraw-board"));
  const room = registry.resolve({ id: rooms[0].id });
  const keys = registry.list().map(row => row.key);
  registry.close();
  const receiver = new RoomSocket(room);
  try {
    await receiver.open();
    const stale = await loadScene(room);
    await writeScene(room, { update: [{ id: "A-0-0", backgroundColor: "#b2f2bb" }] });
    const url = new URL(`https://firestore.googleapis.com/v1/projects/excalidraw-room-persistence/databases/(default)/documents/scenes/${room.id}`);
    url.searchParams.set("currentDocument.updateTime", stale.updateTime);
    url.searchParams.set("updateMask.fieldPaths", "sceneVersion");
    const rejected = await fetch(url, { method: "PATCH", signal: AbortSignal.timeout(15000), headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fields: { sceneVersion: { integerValue: "0" } } }) });
    assert.equal(rejected.status, 400);
    assert.equal((await rejected.json()).error.status, "FAILED_PRECONDITION");
    const deadline = Date.now() + 10000;
    while (!receiver.elements.some(element => element.id === "A-0-0" && element.backgroundColor === "#b2f2bb")) {
      if (receiver.error) throw receiver.error;
      if (Date.now() > deadline) throw new Error("Relay peer did not receive the update");
      await new Promise(resolve => setTimeout(resolve, 50));
    }
  } finally { await receiver.close(); }
  const database = new DatabaseSync(join(home, ".local/state/excalidraw-board/rooms.db"));
  try {
    const old = database.prepare("SELECT id,last_used FROM rooms").all();
    await new Promise(resolve => setTimeout(resolve, 5));
    read(1);
    for (const row of old) {
      const current = database.prepare("SELECT last_used FROM rooms WHERE id=?").get(row.id);
      assert.equal(current.last_used > row.last_used, row.id === rooms[1].id);
    }
  } finally { database.close(); }

  const imagePath = join(home, "pixel.png");
  writeFileSync(imagePath, Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64"));
  const imageArgs = ["image", "--id", rooms[0].id, "--file", imagePath, "--element-id", "pixel", "--x", "260", "--width", "80"];
  const image = JSON.parse(run(imageArgs));
  assert.equal(image.fileSaved, true);
  assert.equal(image.saved, true);
  assert.equal(image.notified, true);
  assert.equal(image.uploaded, true);
  const picture = read(0).elements.find(element => element.id === "pixel");
  assert.equal(picture.type, "image");
  assert.equal(picture.fileId, image.fileId);
  assert.equal(picture.status, "saved");
  assert.equal(picture.width, 80);
  assert.equal(picture.height, 80);
  const repeatedImage = JSON.parse(run(imageArgs));
  assert.equal(repeatedImage.uploaded, false);
  assert.equal(repeatedImage.revision, image.revision);
  assert.deepEqual(repeatedImage.changed, []);

  assert.ok(!outputs.some(output => keys.some(key => output.includes(key))), "CLI output exposed a room key");
  console.log(JSON.stringify({ sameRoom: { expected: 20, actual: before.elements.length }, multiRoom: { rooms: 2, elementsEach: 20 }, maxAttempts: Math.max(...sameRoom.concat(multiRoom).map(receipt => receipt.attempts)), staleSave: "HTTP 400 FAILED_PRECONDITION", noOp: "unchanged revision", relay: "received and decrypted", image: "encrypted upload/readback and idempotent retry", lastUsed: "correct room only", privateTestHome: home }));
} catch (error) {
  console.error(`Live check failed. Private test home retained at ${home}`);
  throw error;
}

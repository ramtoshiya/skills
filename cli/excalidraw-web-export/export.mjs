#!/usr/bin/env node
import { constants } from "node:fs";
import { access, copyFile, open, readFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify, parseArgs } from "node:util";
import { chromium } from "playwright";

const run = promisify(execFile);
const help = `Usage:
  excalidraw-web-export scene.excalidraw output.png [options]
  excalidraw-web-export --room-id prefix output.png [options]
Options:
  --ids a,b                  Render only these exact live element IDs
  --exclude-ids a,b          Omit these exact live element IDs
  --url https://host/        Excalidraw deployment (default https://excalidraw.com)
  --executable-path path    Existing Chrome/Chromium executable
  --timeout-ms number       Browser launch and export deadline (default 120000)
  --help                    Show usage

Uses the deployed app's native PNG download, not a screenshot or clipboard.
Reads saved rooms through excalidraw-board on PATH. Never opens a room link.
Uses an isolated browser context and never overwrites an output file.`;

let browser;
let timer;
try {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: Object.fromEntries([
      ["help", "boolean"], ["room-id", "string"], ["ids", "string"],
      ["exclude-ids", "string"], ["url", "string"], ["executable-path", "string"],
      ["timeout-ms", "string"],
    ].map(([name, type]) => [name, { type }])),
  });
  if (values.help) {
    console.log(help);
  } else {
    const roomId = values["room-id"];
    if (positionals.length !== (roomId !== undefined ? 1 : 2)) throw new Error(help);
    if (roomId !== undefined && !/^[a-zA-Z0-9_-]+$/.test(roomId)) throw new Error("Expected a room ID prefix, not a room link");
    if (values.ids !== undefined && values["exclude-ids"] !== undefined) throw new Error("Choose only one of --ids or --exclude-ids");
    const timeout = Number(values["timeout-ms"] ?? 120_000);
    if (!Number.isFinite(timeout) || timeout <= 0 || timeout > 600_000) throw new Error("Timeout must be between 1 and 600000ms");
    const url = new URL(values.url ?? "https://excalidraw.com");
    if (!["https:", "http:"].includes(url.protocol) || url.hash || url.search || url.username || url.password) {
      throw new Error("Use a deployment URL without room fragments, query parameters, or credentials");
    }
    const output = positionals.at(-1);
    try {
      await access(output);
      throw new Error(`Output already exists: ${output}`);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    let scene;
    let revision;
    if (roomId !== undefined) {
      let stdout;
      try {
        const args = ["snapshot", "--id", roomId];
        if (values.ids !== undefined) args.push("--ids", values.ids);
        if (values["exclude-ids"] !== undefined) args.push("--exclude-ids", values["exclude-ids"]);
        ({ stdout } = await run("excalidraw-board", args, { timeout, maxBuffer: 64 * 1024 * 1024 }));
      } catch (error) {
        if (error.code === "ENOENT") throw new Error("excalidraw-board is missing from PATH. Install it separately before exporting rooms.");
        throw new Error("excalidraw-board snapshot failed. Use a version with the snapshot command, then check room and image access before retrying.");
      }
      scene = JSON.parse(stdout);
      revision = scene.revision;
      if (typeof revision !== "string") throw new Error("Expected a revision from excalidraw-board snapshot");
    } else {
      scene = JSON.parse(await readFile(positionals[0], "utf8"));
    }
    if (!Array.isArray(scene.elements)) throw new Error("Input must contain an Excalidraw elements array");
    let elements = scene.elements.filter(element => !element.isDeleted);
    const selection = roomId === undefined ? (values.ids ?? values["exclude-ids"]) : undefined;
    if (selection !== undefined) {
      const ids = selection.split(",").map(id => id.trim());
      if (ids.some(id => !id)) throw new Error("Selection IDs must be nonempty comma-separated IDs");
      const live = new Set(elements.map(element => element.id));
      if (ids.some(id => !live.has(id))) throw new Error("Selection includes an unknown or deleted element ID");
      const wanted = new Set(ids);
      elements = elements.filter(element => values.ids !== undefined ? wanted.has(element.id) : !wanted.has(element.id));
    }
    if (!elements.length) throw new Error("Selection contains no live elements");
    const files = {};
    for (const element of elements.filter(element => element.type === "image")) {
      const file = scene.files?.[element.fileId];
      if (typeof file?.dataURL !== "string" || !/^data:image\/(png|jpeg|webp|gif);base64,/.test(file.dataURL)) {
        throw new Error("Selected images need embedded raster files in the scene or room snapshot");
      }
      files[element.fileId] = file;
    }
    const data = JSON.stringify({ type: "excalidraw", version: 2, source: "headless-web-export", elements, files,
      appState: { ...scene.appState, exportEmbedScene: false } });
    const started = performance.now();
    let executablePath = values["executable-path"] ?? process.env.CHROMIUM_EXECUTABLE_PATH;
    if (!executablePath && process.platform === "darwin") {
      const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
      try { await access(chrome); executablePath = chrome; } catch {}
    }
    try {
      browser = await chromium.launch({ headless: true, executablePath, timeout });
    } catch {
      throw new Error("Cannot launch headless Chrome/Chromium. Set --executable-path or install managed Chromium as described in the exporter README.");
    }
    const context = await browser.newContext({ locale: "en-US", viewport: { width: 1000, height: 800 }, acceptDownloads: true, serviceWorkers: "block" });
    // Force the app's browser-download fallback instead of an unautomatable OS save dialog.
    await context.addInitScript(() => { delete window.showSaveFilePicker; delete window.showOpenFilePicker; });
    await context.route("**/*", route => {
      const request = route.request();
      const target = new URL(request.url());
      const navigation = !request.isNavigationRequest() || target.origin === url.origin;
      return request.method() === "GET" && navigation ? route.continue() : route.abort();
    });
    await context.routeWebSocket("**/*", socket => socket.close());
    const page = await context.newPage();
    page.setDefaultTimeout(timeout);
    const exportImage = async () => {
      await page.goto(url.href, { waitUntil: "domcontentloaded", timeout });
      await page.getByRole("button", { name: "Rectangle", exact: true }).waitFor();
      await page.locator("canvas").last().evaluate((canvas, data) => {
        const transfer = new DataTransfer();
        transfer.items.add(new File([data], "selection.excalidraw", { type: "application/json" }));
        canvas.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer }));
      }, data);
      await page.getByText("Content replaced.", { exact: false }).waitFor();
      await page.keyboard.press("ControlOrMeta+a");
      await page.keyboard.press("ControlOrMeta+Shift+e");
      await page.getByRole("checkbox", { name: "Only selected", exact: true }).setChecked(true);
      await page.getByRole("checkbox", { name: "Embed scene", exact: true }).setChecked(false);
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.getByRole("button", { name: "Export to PNG", exact: true }).click(),
      ]);
      const failure = await download.failure();
      if (failure) throw new Error("The app's PNG download failed");
      return download.path();
    };
    const downloadPath = await Promise.race([
      exportImage(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Deployed-app export timed out")), Math.max(1, timeout - (performance.now() - started))); }),
    ]);
    clearTimeout(timer);
    const file = await open(downloadPath, "r");
    let header;
    try {
      header = Buffer.alloc(24);
      const { bytesRead } = await file.read(header, 0, 24, 0);
      if (bytesRead !== 24 || !header.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) throw new Error("Download is not a PNG");
    } finally { await file.close(); }
    await copyFile(downloadPath, output, constants.COPYFILE_EXCL);
    console.log(JSON.stringify({ width: header.readUInt32BE(16), height: header.readUInt32BE(20),
      elementIds: elements.map(element => element.id), revision, headless: true, method: "app-download",
      elapsedMs: Math.round(performance.now() - started) }));
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  clearTimeout(timer);
  if (browser) await browser.close();
}

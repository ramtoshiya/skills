import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs, promisify } from "node:util";
import { PNG } from "pngjs";
import { chromium } from "playwright";

const { values } = parseArgs({ options: { live: { type: "boolean" }, "output-dir": { type: "string" } } });
if (!values.live) throw new Error("Pass --live to create a disposable remote room and upload test images");
const directory = dirname(fileURLToPath(import.meta.url));
const run = promisify(execFile);
const home = await mkdtemp(join(tmpdir(), "excalidraw-image-room-"));
const output = values["output-dir"] ? resolve(values["output-dir"]) : join(home, "artifacts");
await mkdir(output, { recursive: true, mode: 0o700 });
const env = { ...process.env, HOME: home };
const board = async args => JSON.parse((await run("excalidraw-board", args, { env, timeout: 60_000, maxBuffer: 64 * 1024 * 1024 })).stdout);
const room = await board(["room", "create", "room-image-export-validation"]);
const source = new PNG({ width: 64, height: 48 });
const colors = [[255, 0, 0, 255], [0, 128, 0, 255], [0, 0, 255, 255], [255, 255, 0, 255]];
for (let y = 0; y < 48; y++) for (let x = 0; x < 64; x++) {
  source.data.set(colors[(y >= 24 ? 2 : 0) + (x >= 32 ? 1 : 0)], (y * 64 + x) * 4);
}
const bytes = PNG.sync.write(source);
const imagePath = join(output, "room-image-pattern.png");
await writeFile(imagePath, bytes, { flag: "wx" });
const uploaded = await board(["image", "--id", room.id, "--file", imagePath, "--element-id", "image-a", "--x", "40", "--y", "80", "--width", "320"]);
assert.equal(uploaded.fileSaved, true);
await board(["image", "--id", room.id, "--file", imagePath, "--element-id", "image-b", "--x", "600", "--y", "80", "--width", "160"]);
const jpegBrowser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE_PATH });
let jpeg;
try {
  const page = await jpegBrowser.newPage();
  const base64 = await page.evaluate(async dataURL => {
    const image = new Image();
    image.src = dataURL;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = image.width;
    canvas.height = image.height;
    canvas.getContext("2d").drawImage(image, 0, 0);
    return canvas.toDataURL("image/jpeg", 1).split(",")[1];
  }, `data:image/png;base64,${bytes.toString("base64")}`);
  jpeg = Buffer.from(base64, "base64");
} finally { await jpegBrowser.close(); }
const jpegPath = join(output, "room-image-pattern.jpg");
await writeFile(jpegPath, jpeg, { flag: "wx" });
const jpegUploaded = await board(["image", "--id", room.id, "--file", jpegPath, "--element-id", "image-jpeg", "--x", "1000", "--y", "80", "--width", "320"]);
assert.equal(jpegUploaded.fileSaved, true);
const before = (await run("excalidraw-board", ["read", "--id", room.id, "--full"], { env, timeout: 60_000 })).stdout;

// Install only into the test's private HOME. Leave the user's installed CLI alone.
await run("sh", [join(directory, "../excalidraw-board/install.sh")], { env, timeout: 30_000 });
await run("sh", [join(directory, "install.sh")], { env, timeout: 60_000 });
const snapshotEnv = { ...env, PATH: `${join(home, ".local/bin")}:${env.PATH}` };
const snapshot = JSON.parse((await run("excalidraw-board", ["snapshot", "--id", room.id, "--ids", "image-a,image-b"], { env: snapshotEnv, timeout: 60_000 })).stdout);
assert.equal(Object.keys(snapshot.files).length, 1);
assert.equal(snapshot.files[uploaded.fileId].dataURL, `data:image/png;base64,${bytes.toString("base64")}`);
assert.equal(snapshot.revision, JSON.parse(before.split("\n")[0]).revision);
const jpegSnapshot = JSON.parse((await run("excalidraw-board", ["snapshot", "--id", room.id, "--ids", "image-jpeg"], { env: snapshotEnv, timeout: 60_000 })).stdout);
assert.equal(jpegSnapshot.files[jpegUploaded.fileId].dataURL, `data:image/jpeg;base64,${jpeg.toString("base64")}`);
const browserArgs = process.env.CHROMIUM_EXECUTABLE_PATH ? ["--executable-path", process.env.CHROMIUM_EXECUTABLE_PATH] : [];
const exportPng = async (name, ids, option = "--ids") => {
  const path = join(output, name);
  const { stdout } = await run("excalidraw-web-export", ["--room-id", room.id, path, option, ids, ...browserArgs], { env: snapshotEnv, timeout: 125_000 });
  const receipt = JSON.parse(stdout);
  assert.equal(receipt.revision, snapshot.revision);
  return { png: PNG.sync.read(await readFile(path)), receipt };
};
const { png: single, receipt } = await exportPng("room-image-only.png", "image-a");
assert.equal(single.width, 340);
assert.equal(single.height, 260);
const pixel = (image, x, y) => [...image.data.subarray((y * image.width + x) * 4, (y * image.width + x) * 4 + 4)];
for (const [index, x, y] of [[0, 90, 70], [1, 250, 70], [2, 90, 190], [3, 250, 190]]) {
  assert.deepEqual(pixel(single, x, y), colors[index]);
}
const { png: both } = await exportPng("room-images-two.png", "image-a,image-b");
assert.equal(both.width, 740);
assert.equal(both.height, 260);
assert.deepEqual(pixel(both, 610, 40), colors[0]);
assert.deepEqual(pixel(both, 690, 100), colors[3]);
const { png: jpegPng } = await exportPng("room-jpeg-export.png", "image-jpeg");
assert.equal(jpegPng.width, 340);
assert.equal(jpegPng.height, 260);
for (const [index, x, y] of [[0, 90, 70], [1, 250, 70], [2, 90, 190], [3, 250, 190]]) {
  const actual = pixel(jpegPng, x, y);
  assert.equal(actual[3], 255);
  for (let channel = 0; channel < 3; channel++) assert.ok(Math.abs(actual[channel] - colors[index][channel]) <= 8, "JPEG colors must match within compression tolerance");
}
const { png: excluded, receipt: excludedReceipt } = await exportPng("room-images-excluding-b.png", "image-b", "--exclude-ids");
assert.deepEqual(excludedReceipt.elementIds, ["image-a", "image-jpeg"]);
assert.equal(excluded.width, 1300);
assert.equal(excluded.height, 260);
assert.deepEqual(pixel(excluded, 90, 70), colors[0]);
const jpegRed = pixel(excluded, 1050, 70);
assert.ok(jpegRed[0] >= 247 && jpegRed[1] <= 8 && jpegRed[2] <= 8);
const after = (await run("excalidraw-board", ["read", "--id", room.id, "--full"], { env: snapshotEnv, timeout: 60_000 })).stdout;
assert.equal(after, before, "Export must not change the saved revision or elements");
console.log(JSON.stringify({ roomPrefix: room.id.slice(0, 8), revision: snapshot.revision, fileId: uploaded.fileId,
  sourceImageBytes: bytes.length, sourceJpegBytes: jpeg.length, imageCount: 3, uniqueFiles: 2, imageBytesMatch: true, pixelChecks: 12,
  roomUnchanged: true, single: { width: single.width, height: single.height },
  multiple: { width: both.width, height: both.height }, method: receipt.method, installedExporter: true,
  privateTestHome: home, artifacts: output }));

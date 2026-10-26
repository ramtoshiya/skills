import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { test } from "node:test";
import { PNG } from "pngjs";

const run = promisify(execFile);
const script = fileURLToPath(new URL("export.mjs", import.meta.url));
const example = fileURLToPath(new URL("../excalidraw-export/example.excalidraw", import.meta.url));
const executable = process.env.CHROMIUM_EXECUTABLE_PATH;
const browserArgs = executable ? ["--executable-path", executable] : [];
const live = process.env.EXCALIDRAW_LIVE === "1";
const pixel = (png, x, y) => [...png.data.subarray((y * png.width + x) * 4, (y * png.width + x) * 4 + 4)];
const exportPng = async (output, args = []) => {
  const { stdout } = await run(process.execPath, [script, example, output, ...args, ...browserArgs], { timeout: 125_000 });
  return { receipt: JSON.parse(stdout), png: PNG.sync.read(await readFile(output)) };
};

test("invalid selections and room links fail without exporting or overwriting", async () => {
  const directory = await mkdtemp(join(tmpdir(), "excalidraw-web-validation-"));
  try {
    const output = join(directory, "result.png");
    for (const [args, message] of [
      [["--ids", ""], "Selection IDs must be nonempty"],
      [["--ids", "missing"], "unknown or deleted"],
      [["--exclude-ids", "extent,top-left,bottom-right,heading,middle"], "no live elements"],
      [["--ids", "middle", "--exclude-ids", "heading"], "Choose only one"],
      [["--url", "https://excalidraw.com/#room=not-a-real-room"], "without room fragments"],
    ]) {
      await assert.rejects(run(process.execPath, [script, example, output, ...args]), error => error.stderr.includes(message));
    }
    const missingImage = join(directory, "missing-image.excalidraw");
    await writeFile(missingImage, JSON.stringify({ elements: [{ id: "image", type: "image", fileId: "missing" }] }));
    await assert.rejects(run(process.execPath, [script, missingImage, output]), error => error.stderr.includes("Selected images need embedded raster files"));
    await writeFile(output, "keep me");
    await assert.rejects(run(process.execPath, [script, example, output]), error => error.stderr.includes("already exists"));
    assert.equal(await readFile(output, "utf8"), "keep me");
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("deployed app downloads selected IDs with native export padding", { skip: !live, timeout: 250_000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "excalidraw-web-selection-"));
  try {
    const { png, receipt } = await exportPng(join(directory, "middle.png"), ["--ids", "middle"]);
    assert.equal(receipt.method, "app-download");
    assert.deepEqual(receipt.elementIds, ["middle"]);
    assert.equal(png.width, 620);
    assert.equal(png.height, 420);
    assert.deepEqual(pixel(png, 310, 210), [0, 128, 0, 255]);
    assert.deepEqual(pixel(png, 0, 0), [255, 255, 255, 255]);
    const { png: text } = await exportPng(join(directory, "text.png"), ["--ids", "heading,middle"]);
    assert.equal(text.width, 5520);
    assert.equal(text.height, 3320);
    assert.deepEqual(pixel(text, 5210, 3110), [0, 128, 0, 255]);
    let ink = 0;
    for (let y = 10; y < 110; y++) for (let x = 10; x < 1700; x++) {
      const offset = (y * text.width + x) * 4;
      if (text.data[offset] < 80 && text.data[offset + 1] < 80 && text.data[offset + 2] < 80) ink++;
    }
    assert.ok(ink > 1000, "download must contain rendered Latin and Korean text");
    const image = new PNG({ width: 4, height: 3 });
    for (let i = 0; i < image.data.length; i += 4) image.data.set([20, 100, 240, 255], i);
    const imageScene = join(directory, "embedded.excalidraw");
    const imageOutput = join(directory, "image.png");
    await writeFile(imageScene, JSON.stringify({ type: "excalidraw", version: 2,
      elements: [{ id: "image", type: "image", fileId: "file", status: "saved", x: 0, y: 0, width: 40, height: 30, scale: [1, 1] }],
      files: { file: { id: "file", mimeType: "image/png", dataURL: `data:image/png;base64,${PNG.sync.write(image).toString("base64")}`, created: 1 } },
    }));
    await run(process.execPath, [script, imageScene, imageOutput, ...browserArgs], { timeout: 125_000 });
    const rendered = PNG.sync.read(await readFile(imageOutput));
    assert.equal(rendered.width, 60);
    assert.equal(rendered.height, 50);
    assert.deepEqual(pixel(rendered, 30, 25), [20, 100, 240, 255]);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("deployed 96MP selection preserves both distant corners and omits the middle", { skip: !live, timeout: 250_000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "excalidraw-web-large-"));
  try {
    const { png: full } = await exportPng(join(directory, "full.png"));
    assert.equal(full.width, 12020);
    assert.equal(full.height, 8020);
    assert.deepEqual(pixel(full, 60, 60), [255, 0, 0, 255]);
    assert.deepEqual(pixel(full, 11960, 7960), [0, 0, 255, 255]);
    assert.deepEqual(pixel(full, 5510, 3510), [0, 128, 0, 255]);
    const { png: selected } = await exportPng(join(directory, "without-middle.png"), ["--exclude-ids", "middle"]);
    assert.equal(selected.width, full.width);
    assert.equal(selected.height, full.height);
    for (let y = 3309; y < 3711; y++) {
      full.data.fill(255, (y * full.width + 5409) * 4, (y * full.width + 6011) * 4);
    }
    assert.ok(full.data.equals(selected.data), "only the omitted object's painted pixels may change");
  } finally { await rm(directory, { recursive: true, force: true }); }
});

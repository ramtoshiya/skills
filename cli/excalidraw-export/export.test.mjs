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
const example = fileURLToPath(new URL("example.excalidraw", import.meta.url));
const executable = process.env.CHROMIUM_EXECUTABLE_PATH;
const browserArgs = executable ? ["--executable-path", executable] : [];
const pixel = (png, x, y) => [...png.data.subarray((y * png.width + x) * 4, (y * png.width + x) * 4 + 4)];

// Real CLI and PNG pixels catch viewport clipping, scaling errors, and missing assets.
test("headless export preserves distant corners and loads Latin and Korean fonts", { timeout: 120_000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "excalidraw-large-"));
  try {
    const output = join(directory, "large.png");
    const { stdout } = await run(process.execPath, [script, example, output, ...browserArgs], { timeout: 110_000 });
    const receipt = JSON.parse(stdout);
    const png = PNG.sync.read(await readFile(output));
    assert.equal(png.width, 12000);
    assert.equal(png.height, 8000);
    assert.deepEqual(pixel(png, 50, 50), [255, 0, 0, 255]);
    assert.deepEqual(pixel(png, 11950, 7950), [0, 0, 255, 255]);
    assert.deepEqual(pixel(png, 5500, 3500), [0, 128, 0, 255]);
    assert.equal(receipt.headless, true);
    assert.ok(receipt.fonts.includes("Excalifont"));
    assert.ok(receipt.fonts.includes("Xiaolai"));
    let dark = 0;
    for (let y = 400; y < 510; y++) {
      for (let x = 500; x < 2200; x++) {
        const offset = (y * png.width + x) * 4;
        if (png.data[offset] < 80 && png.data[offset + 1] < 80 && png.data[offset + 2] < 80) dark++;
      }
    }
    assert.ok(dark > 1000, "text must produce visible ink, not only a font receipt");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("crop uses export-relative coordinates and scale without changing framed children", { timeout: 120_000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "excalidraw-crop-"));
  try {
    const scene = JSON.parse(await readFile(example, "utf8"));
    scene.elements = [
      { id: "extent", type: "rectangle", x: -100, y: -100, width: 400, height: 300, strokeWidth: 0, roughness: 0, backgroundColor: "#ffffff", fillStyle: "solid" },
      { id: "frame", type: "frame", x: -50, y: -50, width: 200, height: 150, name: null },
      { id: "child", type: "rectangle", x: -20, y: -20, width: 100, height: 100, frameId: "frame", strokeWidth: 0, roughness: 0, backgroundColor: "#008000", fillStyle: "solid" },
    ];
    const input = join(directory, "scene.excalidraw");
    const output = join(directory, "crop.png");
    await writeFile(input, JSON.stringify(scene));
    await run(process.execPath, [script, input, output, "--region", "80,80,100,100", "--scale", "2", ...browserArgs], { timeout: 110_000 });
    const png = PNG.sync.read(await readFile(output));
    assert.equal(png.width, 200);
    assert.equal(png.height, 200);
    assert.deepEqual(pixel(png, 100, 100), [0, 128, 0, 255]);
    await assert.rejects(
      run(process.execPath, [script, input, join(directory, "limited.png"), "--max-pixels", "100", ...browserArgs]),
      error => error.stderr.includes("Scene canvas") && error.stderr.includes("exceeds the configured limit"),
    );
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("CLI rejects invalid limits and preserves existing output", async () => {
  const directory = await mkdtemp(join(tmpdir(), "excalidraw-validation-"));
  try {
    const output = join(directory, "output.png");
    for (const args of [["--scale", "0"], ["--region", "0,0,-1,20"], ["--region", "0,0,40000,1"]]) {
      await assert.rejects(run(process.execPath, [script, example, output, ...args]), error => error.code === 1);
    }
    await writeFile(output, "keep me");
    await assert.rejects(run(process.execPath, [script, example, output]), error => error.stderr.includes("already exists"));
    assert.equal(await readFile(output, "utf8"), "keep me");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

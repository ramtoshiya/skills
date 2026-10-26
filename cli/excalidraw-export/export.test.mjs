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
test("headless selection removes only the middle object from the 96MP export", { timeout: 120_000 }, async () => {
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
    const selectedOutput = join(directory, "selected.png");
    await run(process.execPath, [script, example, selectedOutput, "--exclude-ids", "middle", ...browserArgs], { timeout: 110_000 });
    const selected = PNG.sync.read(await readFile(selectedOutput));
    assert.equal(selected.width, 12000);
    assert.equal(selected.height, 8000);
    // Include the rectangle's one-pixel antialiased stroke outside its bounds.
    // Everything else, including every text pixel, must match the full export.
    for (let y = 3299; y < 3701; y++) {
      png.data.fill(255, (y * png.width + 5399) * 4, (y * png.width + 6001) * 4);
    }
    assert.deepEqual(pixel(selected, 5500, 3500), [255, 255, 255, 255]);
    assert.ok(png.data.equals(selected.data), "only the green object's pixels may change");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("ID inclusion sizes only the selection and preserves scene stacking order", { timeout: 120_000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), "excalidraw-ids-"));
  try {
    const singleOutput = join(directory, "middle.png");
    await run(process.execPath, [script, example, singleOutput, "--ids", "middle", "--max-pixels", "300000", ...browserArgs], { timeout: 110_000 });
    const single = PNG.sync.read(await readFile(singleOutput));
    assert.equal(single.width, 600);
    assert.equal(single.height, 400);
    assert.deepEqual(pixel(single, 300, 200), [0, 128, 0, 255]);

    const scene = {
      appState: { viewBackgroundColor: "#ffffff" },
      elements: [
        { id: "back", type: "rectangle", x: -100, y: -100, width: 100, height: 100, backgroundColor: "#ff0000", fillStyle: "solid", roughness: 0 },
        { id: "front", type: "rectangle", x: -80, y: -80, width: 60, height: 60, backgroundColor: "#0000ff", fillStyle: "solid", roughness: 0 },
        { id: "omit", type: "rectangle", x: -70, y: -70, width: 40, height: 40, backgroundColor: "#008000", fillStyle: "solid", roughness: 0 },
      ],
    };
    const input = join(directory, "overlapping.excalidraw");
    const output = join(directory, "included.png");
    const source = JSON.stringify(scene);
    await writeFile(input, source);
    await run(process.execPath, [script, input, output, "--ids", "front,back", ...browserArgs], { timeout: 110_000 });
    const included = PNG.sync.read(await readFile(output));
    assert.equal(included.width, 100);
    assert.equal(included.height, 100);
    assert.deepEqual(pixel(included, 10, 10), [255, 0, 0, 255]);
    assert.deepEqual(pixel(included, 50, 50), [0, 0, 255, 255]);
    assert.equal(await readFile(input, "utf8"), source);
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
    for (const [args, message] of [
      [["--exclude-ids", ""], "Excluded IDs must be nonempty"],
      [["--exclude-ids", "middle,missing"], "Unknown live element IDs: missing"],
      [["--exclude-ids", "extent,top-left,bottom-right,heading,middle"], "Selection contains no live elements"],
      [["--ids", ""], "Selected IDs must be nonempty"],
      [["--ids", "middle,missing"], "Unknown live element IDs: missing"],
      [["--ids", "middle", "--exclude-ids", "top-left"], "Choose only one of --ids or --exclude-ids"],
    ]) {
      await assert.rejects(
        run(process.execPath, [script, example, output, ...args]),
        error => error.code === 1 && error.stderr.includes(message),
      );
    }
    await writeFile(output, "keep me");
    await assert.rejects(run(process.execPath, [script, example, output]), error => error.stderr.includes("already exists"));
    assert.equal(await readFile(output, "utf8"), "keep me");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

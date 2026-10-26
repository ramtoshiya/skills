#!/usr/bin/env node
import { readFile, writeFile, access } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { build } from "esbuild";
import { chromium } from "playwright";

const directory = dirname(fileURLToPath(import.meta.url));
const help = `Usage: node export.mjs scene.excalidraw output.png [options]
  --region x,y,width,height  Crop relative to the full export's top-left, before scaling
  --exclude-ids id1,id2       Omit these exact element IDs before rendering
  --scale number             Pixels per scene unit (default 1)
  --max-pixels number        Per-canvas allocation limit (default 100000000)
  --timeout-ms number        Total rendering deadline after build (default 120000)
  --executable-path path     Use an existing Chromium/Chrome executable
  --help                     Show usage

Runs headless. No scrolling, screenshots, remote page, or scene upload.
Existing output files are never overwritten. Use trusted local scene files only.`;

let browser;
let server;
let timer;
try {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: Object.fromEntries([
      ["help", "boolean"], ["region", "string"], ["scale", "string"], ["exclude-ids", "string"],
      ["max-pixels", "string"], ["timeout-ms", "string"], ["executable-path", "string"],
    ].map(([name, type]) => [name, { type }])),
  });
  if (values.help) {
    console.log(help);
  } else {
    if (positionals.length !== 2) throw new Error(help);
    const [input, output] = positionals;
    const scale = Number(values.scale ?? 1);
    const maxPixels = Number(values["max-pixels"] ?? 100_000_000);
    const timeout = Number(values["timeout-ms"] ?? 120_000);
    if (![scale, maxPixels, timeout].every(value => Number.isFinite(value) && value > 0)) {
      throw new Error("Scale, pixel limit, and timeout must be positive finite numbers");
    }
    let region;
    if (values.region !== undefined) {
      const parts = values.region.split(",");
      const [x, y, width, height] = parts.map(Number);
      if (parts.length !== 4 || parts.some(part => !part.trim()) || ![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) {
        throw new Error("Region must be x,y,width,height with positive width and height");
      }
      if (Math.ceil(width * scale) > 32767 || Math.ceil(height * scale) > 32767 || Math.ceil(width * scale) * Math.ceil(height * scale) > maxPixels) {
        throw new Error("Region exceeds the configured canvas limit");
      }
      region = { x, y, width, height };
    }
    try {
      await access(output);
      throw new Error(`Output already exists: ${output}`);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    const scene = JSON.parse(await readFile(input, "utf8"));
    if (!Array.isArray(scene.elements) || scene.elements.every(element => element.isDeleted)) {
      throw new Error("Input must contain a nonempty Excalidraw elements array");
    }
    if (values["exclude-ids"] !== undefined) {
      const excludedIds = values["exclude-ids"].split(",").map(id => id.trim());
      if (excludedIds.some(id => !id)) throw new Error("Excluded IDs must be nonempty comma-separated element IDs");
      const liveIds = new Set(scene.elements.filter(element => !element.isDeleted).map(element => element.id));
      const unknownIds = excludedIds.filter(id => !liveIds.has(id));
      if (unknownIds.length) throw new Error(`Unknown live element IDs: ${unknownIds.join(", ")}`);
      const excluded = new Set(excludedIds);
      scene.elements = scene.elements.filter(element => !element.isDeleted && !excluded.has(element.id));
      if (!scene.elements.length) throw new Error("Selection contains no live elements");
    }
    for (const file of Object.values(scene.files ?? {})) {
      if (typeof file.dataURL !== "string" || !file.dataURL.startsWith("data:image/")) {
        throw new Error("Images must be embedded data:image URLs, not remote URLs");
      }
    }
    const bundle = await build({
      absWorkingDir: directory,
      entryPoints: ["browser.mjs"], bundle: true, write: false,
      format: "iife", minify: true, define: { "process.env.NODE_ENV": '"production"' },
    });
    const fontsDirectory = join(directory, "node_modules/@excalidraw/excalidraw/dist/prod/fonts");
    const fontRequests = new Set();
    server = createServer(async (request, response) => {
      try {
        if (request.url === "/") {
          response.setHeader("Content-Type", "text/html");
          response.end('<!doctype html><meta charset="utf-8"><script>window.EXCALIDRAW_ASSET_PATH="/"</script><script src="/bundle.js"></script>');
        } else if (request.url === "/bundle.js") {
          response.setHeader("Content-Type", "text/javascript");
          response.end(bundle.outputFiles[0].contents);
        } else if (/^\/fonts\/[a-zA-Z0-9_./-]+\.woff2$/.test(request.url) && !request.url.includes("..")) {
          fontRequests.add(request.url);
          response.setHeader("Content-Type", "font/woff2");
          response.end(await readFile(join(fontsDirectory, request.url.slice(7))));
        } else {
          response.writeHead(404).end();
        }
      } catch {
        response.writeHead(404).end();
      }
    });
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    const origin = `http://127.0.0.1:${server.address().port}`;
    const started = performance.now();
    browser = await chromium.launch({ headless: true, executablePath: values["executable-path"], timeout });
    const job = async () => {
      const page = await browser.newPage({ viewport: { width: 800, height: 600 }, deviceScaleFactor: 1 });
      await page.route("**/*", route => {
        const url = new URL(route.request().url());
        return url.origin === origin || ["data:", "blob:"].includes(url.protocol) ? route.continue() : route.abort();
      });
      await page.goto(origin, { timeout });
      await page.waitForFunction(() => typeof window.renderScene === "function", undefined, { timeout });
      return page.evaluate(options => window.renderScene(options), { scene, region, scale, maxPixels });
    };
    const result = await Promise.race([
      job(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Rendering exceeded ${timeout}ms`)), Math.max(1, timeout - (performance.now() - started))); }),
    ]);
    clearTimeout(timer);
    const png = Buffer.from(result.data, "base64");
    await writeFile(output, png, { flag: "wx" });
    const { data, ...receipt } = result;
    console.log(JSON.stringify({ ...receipt, bytes: png.length, elapsedMs: Math.round(performance.now() - started), headless: true, viewport: "800x600", fontFilesLoaded: fontRequests.size }));
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  clearTimeout(timer);
  if (browser) await browser.close();
  if (server) await new Promise(resolve => server.close(resolve));
}

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { chromium } from "playwright-core";

const FRAME = "[data-inline-vis-frame] iframe[srcdoc]";
const FRAME_SCRIPT = "script[data-inline-vis-copy-image]";
const PLUGIN_BUNDLE = /\/api\/v1\/plugin-app-assets\/[^/]+\/app\.js$/;
const PLUGIN_BUNDLE_MARK = "inlineVisCopyImage";
const LOCAL_BUNDLE = new URL("../dist/app.js", import.meta.url);
const VIEWPORT = { width: 1440, height: 1800 };

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    visits: { type: "string", default: "30" },
    reloads: { type: "string", default: "5" },
    served: { type: "boolean", default: false },
  },
});
const [fixturePath, otherPath] = positionals;
const serverUrl = process.env.BB_SERVER_URL;
const executablePath = process.env.BB_VERIFY_CHROMIUM;
if (!serverUrl) throw new Error("Set BB_SERVER_URL to the bb server.");
if (!executablePath || !existsSync(executablePath)) {
  throw new Error("Set BB_VERIFY_CHROMIUM to an existing Chromium executable.");
}
if (!fixturePath || !otherPath) {
  throw new Error(
    "Pass two thread paths such as /projects/<id>/threads/<id>: a thread whose last reply shows inline-vis pages that each have an element with id m, and any other thread.",
  );
}

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const localBundle = values.served ? null : readFileSync(LOCAL_BUNDLE);
let servedBundleHash = null;

async function routePluginBundle(page) {
  await page.route(PLUGIN_BUNDLE, async (route) => {
    const response = await route.fetch();
    const body = await response.body();
    if (!body.includes(PLUGIN_BUNDLE_MARK)) return route.fulfill({ response, body });
    servedBundleHash = sha256(body);
    return route.fulfill({ response, body: localBundle ?? body });
  });
}

async function goTo(page, path) {
  await page.evaluate((target) => {
    history.pushState(null, "", target);
    dispatchEvent(new PopStateEvent("popstate"));
  }, path);
  await page.waitForURL((url) => url.pathname === path);
}

function inViewport(box) {
  return box !== null && box.height > 0 && box.y >= 0 && box.y + box.height <= VIEWPORT.height;
}

async function frameState(element) {
  const box = await element.boundingBox();
  const frame = await element.contentFrame();
  if (!frame) return { kind: "detached", box };
  try {
    await frame.waitForFunction(
      (selector) => document.readyState === "complete" && document.querySelector(selector) !== null,
      FRAME_SCRIPT,
      { timeout: 15_000 },
    );
  } catch {
    return { kind: "no-script", box };
  }
  try {
    await frame.waitForFunction(
      () => (document.getElementById("m")?.offsetHeight ?? 0) > 0,
      undefined,
      { timeout: 3_000 },
    );
    return { kind: "rendered", box: await element.boundingBox() };
  } catch {
    return { kind: "blank", box: await element.boundingBox() };
  }
}

async function measureVisit(page, frameCount) {
  await page.waitForFunction(
    ([selector, count]) => document.querySelectorAll(selector).length >= count,
    [FRAME, frameCount],
    { timeout: 30_000 },
  );
  const elements = await page.locator(FRAME).elementHandles();
  const states = await Promise.all(elements.map(frameState));
  const outside = states.filter((state) => !inViewport(state.box));
  assert.deepEqual(outside, [], "every inline-vis frame must be inside the viewport");
  return states.map((state) => state.kind);
}

const browser = await chromium.launch({ executablePath, headless: true });
try {
  const page = await browser.newPage({ viewport: VIEWPORT });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await routePluginBundle(page);
  await page.goto(new URL(fixturePath, serverUrl).href);
  const frameCount = (await measureVisit(page, 1)).length;

  const tally = new Map();
  const record = (kinds) => kinds.forEach((kind) => tally.set(kind, (tally.get(kind) ?? 0) + 1));
  for (let visit = 0; visit < Number(values.visits); visit++) {
    await goTo(page, otherPath);
    await page.waitForFunction((selector) => !document.querySelector(selector), FRAME);
    await goTo(page, fixturePath);
    record(await measureVisit(page, frameCount));
  }
  for (let reload = 0; reload < Number(values.reloads); reload++) {
    await page.reload();
    record(await measureVisit(page, frameCount));
  }

  const counts = Object.fromEntries(tally);
  const total = [...tally.values()].reduce((sum, count) => sum + count, 0);
  console.log(
    JSON.stringify({
      bundle: values.served ? "served" : "local dist/app.js",
      servedBundleSha256: servedBundleHash,
      localBundleSha256: localBundle && sha256(localBundle),
      framesPerVisit: frameCount,
      frames: total,
      counts,
    }),
  );
  assert.ok(servedBundleHash, "the page loaded the inline-vis-copy-image bundle");
  assert.deepEqual(errors, []);
  assert.equal(counts.rendered, total, "every frame renders its page and carries the copy script");
} finally {
  await browser.close();
}

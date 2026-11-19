import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { chromium } from "playwright-core";

const PLUGIN_ID = "inline-vis-copy-image";
const FRAME = "[data-inline-vis-frame] iframe[srcdoc]";
const OVERLAY = "[data-inline-vis-copy-image-overlay]";
const FRAME_SCRIPT_MARK = "data-inline-vis-copy-image";
const TOP_MARGIN_PX = 120;

const serverUrl = process.env.BB_SERVER_URL;
if (!serverUrl) throw new Error("Set BB_SERVER_URL to the bb server.");
const executablePath = process.env.BB_VERIFY_CHROMIUM ?? chromium.executablePath();
if (!existsSync(executablePath)) {
  throw new Error("Set BB_VERIFY_CHROMIUM to an existing Chromium executable.");
}
const [threadId] = process.argv.slice(2);
if (!threadId) {
  throw new Error("Pass the id of a thread whose last messages show an inline-vis HTML page with an <img>.");
}

function plugin(action) {
  execFileSync("bb", ["plugin", action, PLUGIN_ID], { stdio: "pipe" });
}

async function openThread(browser) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(serverUrl);
  const anyThread = page.locator("a[data-sidebar-thread-id]").first();
  await anyThread.waitFor({ timeout: 30_000 });
  const href = await anyThread.getAttribute("href");
  await page.goto(new URL(href.replace(/thr_[a-z0-9]+/, threadId), serverUrl).href);
  await page.locator(FRAME).first().waitFor({ state: "attached", timeout: 30_000 });
  return { page, errors };
}

async function wheelIntoView(page, element) {
  const { width, height } = page.viewportSize();
  await page.mouse.move(width / 2, height / 2);
  for (let attempt = 0; attempt < 20; attempt++) {
    const box = await element.boundingBox();
    if (box.y >= TOP_MARGIN_PX && box.y <= height / 2) return;
    await page.mouse.wheel(0, box.y - TOP_MARGIN_PX * 2);
    await page.waitForTimeout(400);
  }
  throw new Error("Could not scroll the inline-vis frame into the viewport.");
}

async function frameWithImage(page) {
  await page.waitForFunction(
    ([selector, mark]) =>
      [...document.querySelectorAll(selector)].every((frame) => frame.srcdoc.includes(mark)),
    [FRAME, FRAME_SCRIPT_MARK],
    { timeout: 15_000 },
  );
  for (const element of await page.locator(FRAME).elementHandles()) {
    const frame = await element.contentFrame();
    const image = frame?.locator("img").first();
    if (!image || (await image.count()) === 0) continue;
    await wheelIntoView(page, element);
    await frame.waitForFunction(() => document.images[0].naturalWidth > 0);
    return { element, frame, image };
  }
  throw new Error(`No inline-vis frame in ${threadId} contains an <img>.`);
}

async function pagePointOf(image) {
  const box = await image.boundingBox();
  return { x: Math.round(box.x + box.width / 2), y: Math.round(box.y + box.height / 2) };
}

async function rightClickUntilCovered(page, point) {
  for (let attempt = 0; attempt < 20; attempt++) {
    await page.mouse.click(point.x, point.y, { button: "right" });
    try {
      await page.waitForFunction((selector) => document.querySelector(selector)?.naturalWidth > 0, OVERLAY, { timeout: 1_000 });
      return;
    } catch {}
  }
  throw new Error("No overlay covered the right-clicked image.");
}

async function assertEveryPageRenders(page) {
  for (const element of await page.locator(FRAME).elementHandles()) {
    const frame = await element.contentFrame();
    const height = await frame.evaluate(() => document.documentElement.getBoundingClientRect().height);
    assert.ok(height > 0, "every inline-vis page lays out at a nonzero height");
  }
}

function hitAt({ x, y }) {
  const hit = document.elementFromPoint(x, y);
  return {
    tag: hit?.tagName ?? null,
    isOverlay: hit?.hasAttribute("data-inline-vis-copy-image-overlay") ?? false,
    src: hit instanceof HTMLImageElement ? hit.currentSrc : null,
    naturalWidth: hit instanceof HTMLImageElement ? hit.naturalWidth : 0,
  };
}

const browser = await chromium.launch({ executablePath, headless: true });
try {
  plugin("enable");
  const { page, errors } = await openThread(browser);
  const { element, frame, image } = await frameWithImage(page);
  const imageSrc = await image.evaluate((node) => node.currentSrc);
  const frameHeight = (await element.boundingBox()).height;
  const point = await pagePointOf(image);

  assert.equal((await page.evaluate(hitAt, point)).tag, "IFRAME", "before the right-click the app page sees only the frame");

  await rightClickUntilCovered(page, point);
  const covered = await page.evaluate(hitAt, point);
  assert.equal(covered.isOverlay, true, "the app page's hit test at the right-click point finds the overlay");
  assert.equal(covered.src, imageSrc, "the overlay shows the image that was right-clicked");
  assert.ok(covered.naturalWidth > 0, "the overlay image is decoded");
  assert.equal(await page.locator(OVERLAY).count(), 1);

  await page.mouse.click(point.x, point.y, { button: "right" });
  assert.equal((await page.evaluate(hitAt, point)).isOverlay, true, "a second right-click on the overlay keeps it");

  const text = await frame.locator("body").boundingBox();
  await page.mouse.click(point.x, point.y);
  await page.waitForFunction((selector) => !document.querySelector(selector), OVERLAY);
  assert.equal((await page.evaluate(hitAt, point)).tag, "IFRAME", "a click on the overlay removes it");

  await page.mouse.click(point.x, point.y, { button: "right" });
  await page.waitForSelector(OVERLAY, { state: "attached" });
  await page.mouse.click(Math.round(text.x + text.width - 5), point.y);
  await page.waitForFunction((selector) => !document.querySelector(selector), OVERLAY);

  await page.mouse.click(Math.round(text.x + text.width - 5), point.y, { button: "right" });
  await page.waitForTimeout(500);
  assert.equal(await page.locator(OVERLAY).count(), 0, "a right-click beside the image places no overlay");

  assert.equal((await element.boundingBox()).height, frameHeight, "the frame kept its height");

  plugin("reload");
  await page.waitForFunction((selector) => !document.querySelector(selector), OVERLAY, { timeout: 15_000 });
  await rightClickUntilCovered(page, point);
  assert.equal((await page.evaluate(hitAt, point)).src, imageSrc, "after a plugin reload the overlay covers the image again");
  await assertEveryPageRenders(page);

  plugin("disable");
  await page.waitForFunction((selector) => !document.querySelector(selector), OVERLAY, { timeout: 15_000 });
  await assertEveryPageRenders(page);
  await page.mouse.click(point.x, point.y, { button: "right" });
  await page.waitForTimeout(1_000);
  assert.equal(await page.locator(OVERLAY).count(), 0, "a disabled plugin places no overlay");
  assert.deepEqual(errors, []);
  console.log(`PASS ${threadId}: the right-click point on ${imageSrc.slice(0, 80)} is covered by a decoded overlay image, the overlay leaves on the next press, a plugin reload keeps copying, and unloading the plugin removes the overlay while every page keeps rendering.`);
} finally {
  await browser.close();
  plugin("enable");
}

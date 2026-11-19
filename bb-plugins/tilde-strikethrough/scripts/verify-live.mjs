import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { chromium } from "playwright-core";

const PLUGIN_ID = "tilde-strikethrough";
const RENDERED = "[data-markdown-preview] del";
const SINGLE_TILDE_TEXT = "6 and then 8";
const DOUBLE_TILDE_TEXT = "removed text";

const serverUrl = process.env.BB_SERVER_URL;
if (!serverUrl) throw new Error("Set BB_SERVER_URL to the bb server.");
const executablePath = process.env.BB_VERIFY_CHROMIUM ?? chromium.executablePath();
if (!existsSync(executablePath)) {
  throw new Error("Set BB_VERIFY_CHROMIUM to an existing Chromium executable.");
}
const [threadId] = process.argv.slice(2);
if (!threadId) {
  throw new Error("Pass the id of a thread whose last message is the fixture text from the README.");
}

function setPluginEnabled(enabled) {
  execFileSync("bb", ["plugin", enabled ? "enable" : "disable", PLUGIN_ID], { stdio: "pipe" });
}

function readRendered(selector) {
  return [...document.querySelectorAll(selector)].map((element) => ({
    text: element.textContent,
    line: getComputedStyle(element).textDecorationLine,
    before: getComputedStyle(element, "::before").content,
    after: getComputedStyle(element, "::after").content,
    shown: element.getBoundingClientRect().width > 0,
  }));
}

function check(rendered, text, expected, when) {
  const matching = rendered.filter((element) => element.text === text && element.shown);
  assert.ok(matching.length > 0, `${when}: no rendered deletion reads "${text}"`);
  for (const { line, before, after } of matching) {
    assert.deepEqual({ line, before, after }, expected, `${when}: "${text}"`);
  }
  return matching.length;
}

const STRUCK = { line: "line-through", before: "none", after: "none" };
const AS_WRITTEN = { line: "none", before: '"~"', after: '"~"' };

const browser = await chromium.launch({ executablePath, headless: true });
try {
  setPluginEnabled(false);
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(serverUrl);
  const anyThread = page.locator("a[data-sidebar-thread-id]").first();
  await anyThread.waitFor({ timeout: 30_000 });
  const href = await anyThread.getAttribute("href");
  await page.goto(new URL(href.replace(/thr_[a-z0-9]+/, threadId), serverUrl).href);
  await page.locator(RENDERED).first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(1_000);

  const without = await page.evaluate(readRendered, RENDERED);
  check(without, SINGLE_TILDE_TEXT, STRUCK, "plugin disabled");
  check(without, DOUBLE_TILDE_TEXT, STRUCK, "plugin disabled");

  setPluginEnabled(true);
  await page.waitForSelector("del[data-tilde-strikethrough-single]", { timeout: 15_000 });
  const withPlugin = await page.evaluate(readRendered, RENDERED);
  const single = check(withPlugin, SINGLE_TILDE_TEXT, AS_WRITTEN, "plugin enabled");
  const double = check(withPlugin, DOUBLE_TILDE_TEXT, STRUCK, "plugin enabled");
  const asWritten = withPlugin.filter((element) => element.line === "none").map((element) => element.text);

  setPluginEnabled(false);
  await page.waitForFunction(() => !document.querySelector("del[data-tilde-strikethrough-single]"), null, { timeout: 15_000 });
  check(await page.evaluate(readRendered, RENDERED), SINGLE_TILDE_TEXT, STRUCK, "plugin disabled again");

  assert.deepEqual(errors, []);
  console.log(`PASS ${threadId}: ${single} single-tilde spans show their tildes without a line, ${double} double-tilde spans stay struck, and disabling the plugin restores bb's rendering. Shown as written: ${JSON.stringify(asWritten)}`);
} finally {
  await browser.close();
  setPluginEnabled(true);
}

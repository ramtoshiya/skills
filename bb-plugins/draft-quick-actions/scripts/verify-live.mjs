import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { chromium } from "playwright-core";

const serverUrl = process.env.BB_SERVER_URL;
const projectId = process.env.BB_VERIFY_PROJECT;
if (!serverUrl || !projectId) throw new Error("Set BB_SERVER_URL and BB_VERIFY_PROJECT before running this live check.");
const executablePath = process.env.BB_VERIFY_CHROMIUM ?? chromium.executablePath();
if (!existsSync(executablePath)) throw new Error("Set BB_VERIFY_CHROMIUM to an existing compatible Chromium executable. This check never downloads a browser.");
const bb = (args) => JSON.parse(execFileSync("bb", [...args, "--json"], { encoding: "utf8" }));
const preferences = bb(["thread-list", "prefs", "get", "rowActions"]);
assert.ok(preferences.value.includes("draft-quick-actions/run-draft"), "Enable Run draft in Customize actions before this check.");
let threadId;
let browser;
try {
  const created = bb([
    "draft", "create", "--project", projectId,
    "--provider", "claude-code", "--model", "claude-haiku-5-5",
    "--reasoning-level", "low", "--title", "Draft quick-action verification",
    "--prompt", "This is a temporary UI verification. Reply exactly: Draft action verified. Do not use tools, edit files, or start other threads.",
  ]);
  threadId = created.threadId;
  assert.ok(threadId, "The draft command did not return a thread ID.");
  assert.equal(created.held, true, "Held Drafts must be in draft mode for this check.");
  const before = bb(["thread", "queue", "list", threadId]);
  assert.equal(before.length, 1);
  const originalMessageId = before[0].id;
  assert.equal(before[0].waitingOn?.pluginId, "held-drafts");
  bb(["thread", "pin", threadId]);
  browser = await chromium.launch({ executablePath, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(serverUrl);
  await page.locator("[data-sidebar-thread-id]").first().waitFor();
  const row = page.locator(`[data-sidebar-thread-id="${threadId}"]`).first();
  await row.scrollIntoViewIfNeeded();
  await row.hover();
  const button = row.locator("xpath=../..").getByRole("button", { name: "Run draft", exact: true });
  await button.waitFor({ state: "visible" });
  const startingUrl = page.url();
  const responsePromise = page.waitForResponse((response) => response.url().includes("/plugins/draft-quick-actions/rpc/runDraft"));
  await button.click();
  const response = await responsePromise;
  assert.equal(response.ok(), true, `Run draft returned HTTP ${response.status()}`);
  assert.equal(page.url(), startingUrl, "The sidebar action navigated away from the current page.");
  const after = bb(["thread", "queue", "list", threadId]);
  assert.equal(after.some((message) => message.id === originalMessageId && message.waitingOn?.pluginId === "held-drafts"), false);
  assert.equal(after.some((message) => message.id !== originalMessageId), false, "The action created a replacement queue message.");
  assert.deepEqual(errors, []);
  console.log("PASS: one sidebar click approved the original held message without navigation or replacement messages.");
} finally {
  try {
    await browser?.close();
  } finally {
    if (threadId) {
      try {
        execFileSync("bb", ["thread", "stop", threadId], { stdio: "pipe" });
      } finally {
        execFileSync("bb", ["thread", "delete", threadId, "--yes"], { stdio: "pipe" });
        console.log("Cleaned up the temporary verification thread.");
      }
    }
  }
}

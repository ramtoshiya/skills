import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { chromium } from "playwright-core";
import { rpcContract } from "../server.ts";

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
  const extra = bb(["thread", "queue", "create", threadId, "Temporary scheduled message for draft-action verification."]);
  assert.ok(extra.id, "The additional message did not return a queue ID.");
  const scheduled = bb(["thread", "queue", "update", threadId, extra.id, "--send-at", "1h"]);
  assert.equal(scheduled.waitingOn?.kind, "time", "The extra message must wait on its schedule rather than Held Drafts.");
  bb(["thread", "pin", threadId]);
  browser = await chromium.launch({ executablePath, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const mixedQueueRead = page.waitForResponse(async (response) => {
    if (!response.url().includes("/api/") || !response.ok()) return false;
    try {
      const body = await response.json();
      return Array.isArray(body) && body.some((message) => message.id === extra.id && message.threadId === threadId);
    } catch {
      return false;
    }
  });
  await page.goto(serverUrl);
  await mixedQueueRead;
  await page.locator("[data-sidebar-thread-id]").first().waitFor();
  const row = page.locator(`[data-sidebar-thread-id="${threadId}"]`).first();
  await row.scrollIntoViewIfNeeded();
  await row.hover();
  const button = row.locator("xpath=../..").getByRole("button", { name: "Run draft", exact: true });
  assert.equal(await button.count(), 0, "A draft with an extra scheduled message must not offer Run draft.");
  bb(["thread", "queue", "delete", threadId, extra.id]);
  await button.waitFor({ state: "visible" });
  const startingUrl = page.url();
  const responsePromise = page.waitForResponse((response) => response.url().includes("/plugins/draft-quick-actions/rpc/runDraft"));
  await button.click();
  const response = await responsePromise;
  assert.equal(response.ok(), true, `Run draft returned HTTP ${response.status()}`);
  const approval = rpcContract.runDraft.output.parse(await response.json());
  assert.equal(page.url(), startingUrl, "The sidebar action navigated away from the current page.");
  const after = bb(["thread", "queue", "list", threadId]);
  assert.equal(after.some((message) => message.id === originalMessageId && message.waitingOn?.pluginId === "held-drafts"), false);
  assert.equal(after.some((message) => message.id !== originalMessageId), false, "The action created a replacement queue message.");
  bb(["thread", "wait", threadId, "--status", "idle", "--timeout", "60s"]);
  const { output } = bb(["thread", "output", threadId]);
  assert.equal(typeof output, "string", "The verification thread returned no output.");
  assert.equal(output.trim(), "Draft action verified.", "The original verification prompt did not produce its expected reply.");
  assert.deepEqual(errors, []);
  console.log(`PASS: mixed queue hid the button, removing the extra message restored it, and one click ran the original prompt without navigation or replacement messages. Approval: ${approval.kind}.`);
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

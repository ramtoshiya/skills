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

const desktop = { viewport: { width: 1440, height: 1000 } };
const tablet = { viewport: { width: 834, height: 1194 }, hasTouch: true, isMobile: true };
const phone = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true };
const threadIds = [];
let browser;

function createDraft(name) {
  const created = bb([
    "draft", "create", "--project", projectId,
    "--provider", "claude-code", "--model", "claude-haiku-5-5",
    "--reasoning-level", "low", "--title", `Draft quick-action verification (${name})`,
    "--prompt", "This is a temporary UI verification. Reply exactly: Draft action verified. Do not use tools, edit files, or start other threads.",
  ]);
  assert.ok(created.threadId, "The draft command did not return a thread ID.");
  threadIds.push(created.threadId);
  assert.equal(created.held, true, "Held Drafts must be in draft mode for this check.");
  const queue = bb(["thread", "queue", "list", created.threadId]);
  assert.equal(queue.length, 1);
  assert.equal(queue[0].waitingOn?.pluginId, "held-drafts");
  return { threadId: created.threadId, queuedMessageId: queue[0].id, updatedAt: queue[0].updatedAt };
}

async function openPage(device, path = "") {
  const context = await browser.newContext(device);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${serverUrl}${path}`);
  return { page, errors };
}

const openThread = (device, target) => openPage(device, `/projects/${projectId}/threads/${target.threadId}`);
const headerButton = (page, label = /^(Run draft|Sending draft…)$/) => page.locator("[data-thread-header-responsive-action] button", { hasText: label });
const threadMenu = (page) => page.getByRole("button", { name: "Thread actions" });

async function holdRunDraft(page) {
  const requests = [];
  let release;
  const released = new Promise((resolve) => { release = resolve; });
  await page.route("**/plugins/draft-quick-actions/rpc/runDraft", async (route) => {
    requests.push(route.request().postDataJSON());
    await released;
    await route.continue();
  });
  const response = page.waitForResponse((candidate) => candidate.url().includes("/plugins/draft-quick-actions/rpc/runDraft"));
  return { requests, release, response };
}

async function expectApproved(target, hold, { page, errors }, startingUrl) {
  const response = await hold.response;
  assert.equal(response.ok(), true, `Run draft returned HTTP ${response.status()}`);
  const envelope = await response.json();
  assert.equal(envelope.ok, true, "The RPC transport did not return a successful result.");
  const approval = rpcContract.runDraft.output.parse(envelope.result);
  assert.equal(hold.requests.length, 1, "Run draft must send exactly one request.");
  assert.deepEqual(rpcContract.runDraft.input.parse(hold.requests[0]), target);
  assert.equal(page.url(), startingUrl, "Run draft navigated away from the current page.");
  const after = bb(["thread", "queue", "list", target.threadId]);
  assert.equal(after.some((message) => message.id === target.queuedMessageId && message.waitingOn?.pluginId === "held-drafts"), false);
  assert.equal(after.some((message) => message.id !== target.queuedMessageId), false, "Run draft created a replacement queue message.");
  bb(["thread", "wait", target.threadId, "--status", "idle", "--timeout", "60s"]);
  const { output } = bb(["thread", "output", target.threadId]);
  assert.equal(typeof output, "string", "The verification thread returned no output.");
  assert.equal(output.trim(), "Draft action verified.", "The original verification prompt did not produce its expected reply.");
  assert.deepEqual(errors, []);
  return approval.kind;
}

async function desktopSidebar() {
  const target = createDraft("desktop sidebar");
  bb(["thread", "pin", target.threadId]);
  const session = await openPage(desktop);
  const { page } = session;
  await page.locator("[data-sidebar-thread-id]").first().waitFor();
  const row = page.locator(`[data-sidebar-thread-id="${target.threadId}"]`).first();
  await row.scrollIntoViewIfNeeded();
  await row.hover();
  const button = row.locator("xpath=../..").getByRole("button", { name: "Run draft", exact: true });
  await button.waitFor({ state: "visible" });
  const extra = bb(["thread", "queue", "create", target.threadId, "Temporary scheduled message for draft-action verification."]);
  assert.ok(extra.id, "The additional message did not return a queue ID.");
  const mixedQueueRead = page.waitForResponse(async (response) => {
    if (!response.url().includes("/api/") || !response.ok()) return false;
    try {
      const body = await response.json();
      return Array.isArray(body) && body.some((message) => message.id === extra.id && message.threadId === target.threadId && message.waitingOn?.kind === "time");
    } catch {
      return false;
    }
  });
  const scheduled = bb(["thread", "queue", "update", target.threadId, extra.id, "--send-at", "1h"]);
  assert.equal(scheduled.waitingOn?.kind, "time", "The extra message must wait on its schedule rather than Held Drafts.");
  await mixedQueueRead;
  await button.waitFor({ state: "detached" });
  assert.equal(await row.isVisible(), true, "The draft row disappeared rather than updating its action.");
  bb(["thread", "queue", "delete", target.threadId, extra.id]);
  await button.waitFor({ state: "visible" });
  const startingUrl = page.url();
  const hold = await holdRunDraft(page);
  await button.click();
  hold.release();
  return `desktop sidebar: mixed queue hid the button, removing the extra message restored it, one click sent the target (${await expectApproved(target, hold, session, startingUrl)})`;
}

async function headerButtonCase(device, name) {
  const target = createDraft(name);
  const session = await openThread(device, target);
  const { page } = session;
  const button = headerButton(page);
  await headerButton(page, "Run draft").waitFor({ state: "visible" });
  const hover = await page.evaluate(() => matchMedia("(hover: hover)").matches);
  assert.equal(hover, device.hasTouch !== true, "The emulated device has the wrong hover capability.");
  const startingUrl = page.url();
  const hold = await holdRunDraft(page);
  if (device.hasTouch) await button.tap();
  else await button.click();
  await headerButton(page, "Sending draft…").waitFor({ state: "visible" });
  assert.equal(await button.isDisabled(), true, "The header button must be disabled while its request is pending.");
  hold.release();
  const kind = await expectApproved(target, hold, session, startingUrl);
  await button.waitFor({ state: "detached" });
  return `${name}: header button visible with hover=${hover}, pending label and disabled state shown, one ${device.hasTouch ? "tap" : "click"} sent the target, button removed after send (${kind})`;
}

async function phoneMenu() {
  const target = createDraft("390 touch menu");
  const session = await openThread(phone, target);
  const { page } = session;
  const entries = page.getByRole("menuitem", { name: "Run draft", exact: true });
  await threadMenu(page).first().tap();
  await entries.first().waitFor({ state: "visible" });
  assert.equal(await headerButton(page).count(), 0, "Phone width must fold the header button into the thread menu.");
  const labels = await page.getByRole("menuitem").allInnerTexts();
  const count = await entries.count();
  const startingUrl = page.url();
  const hold = await holdRunDraft(page);
  await entries.first().tap();
  hold.release();
  const kind = await expectApproved(target, hold, session, startingUrl);
  await page.keyboard.press("Escape");
  await threadMenu(page).first().tap();
  await page.getByRole("menuitem").first().waitFor({ state: "visible" });
  assert.equal(await entries.count(), 0, "Run draft must leave the thread menu after the draft starts.");
  return `390 touch menu: no inline header button, thread menu listed Run draft ${count} time(s) in ${JSON.stringify(labels)}, one tap sent the target, menu entry removed after send (${kind})`;
}

const results = [];
try {
  browser = await chromium.launch({ executablePath, headless: true });
  results.push(await desktopSidebar());
  results.push(await headerButtonCase(desktop, "desktop header"));
  results.push(await headerButtonCase(tablet, "834 touch header"));
  results.push(await phoneMenu());
  for (const result of results) console.log(`PASS ${result}`);
} finally {
  try {
    await browser?.close();
  } finally {
    const failures = [];
    for (const threadId of threadIds) {
      for (const command of [["thread", "stop", threadId], ["thread", "delete", threadId, "--yes"]]) {
        try {
          execFileSync("bb", command, { stdio: "pipe" });
        } catch (error) {
          failures.push(error);
        }
      }
    }
    if (failures.length > 0) throw new AggregateError(failures, "Cleaning up the temporary verification threads failed.");
    console.log(`Cleaned up ${threadIds.length} temporary verification thread(s).`);
  }
}

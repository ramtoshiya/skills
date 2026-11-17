import assert from "node:assert/strict";
import { test } from "node:test";
import {
  createFakePluginHost,
  makeQueueEntry,
  makeThreadResponse,
  experimental_scanPublicSdkOnly,
} from "@get-bb/plugin-sdk/testing";
import plugin from "../server.ts";

const target = { threadId: "draft-thread", queuedMessageId: "draft-message", updatedAt: 10 };
const draft = () => makeQueueEntry({
  id: target.queuedMessageId,
  threadId: target.threadId,
  updatedAt: target.updatedAt,
  originPluginId: "held-drafts",
  waitingOn: { kind: "plugin", pluginId: "held-drafts", reason: "Draft" },
});
const thread = () => makeThreadResponse({ id: target.threadId, status: "pending", originPluginId: "held-drafts" });

async function setup(t, { messages = [draft()], current = thread(), send = async () => ({ ok: true, delivery: "sent" }) } = {}) {
  const { bb, harness } = createFakePluginHost({
    pluginId: "draft-quick-actions",
    sdk: {
      threads: {
        get: async () => current,
        queuedMessages: { list: async () => messages, send },
      },
    },
  });
  plugin(bb);
  t.after(() => harness.lifecycle.dispose());
  return harness;
}

test("a click sends the existing reviewed message without creating a replacement", async (t) => {
  const harness = await setup(t);
  assert.deepEqual(await harness.behavior.callRpc("runDraft", target), { kind: "sent" });
  assert.deepEqual(harness.inspection.sdk.callsTo("threads.queuedMessages.send"), [
    [{ threadId: "draft-thread", queuedMessageId: "draft-message", mode: "auto" }],
  ]);
  assert.equal(harness.inspection.sdk.callsTo("threads.spawn").length, 0);
  assert.equal(harness.inspection.sdk.callsTo("threads.queuedMessages.create").length, 0);
});

test("changed or unrelated queue entries are never sent", async (t) => {
  const cases = [
    ["removed", []],
    ["replaced", [{ ...draft(), id: "replacement" }]],
    ["edited", [{ ...draft(), updatedAt: 11 }]],
    ["multiple messages", [draft(), { ...draft(), id: "second" }]],
    ["other holder", [{ ...draft(), waitingOn: { kind: "plugin", pluginId: "other", reason: "Wait" } }]],
    ["other origin", [{ ...draft(), originPluginId: "other" }]],
    ["scheduled", [{ ...draft(), sendAt: 1000 }]],
    ["grouped", [{ ...draft(), groupWithNext: true }]],
    ["sending", [{ ...draft(), state: "claimed" }]],
    ["retry", [{ ...draft(), payload: { kind: "retry", attempt: 1, reason: "Retry", retryOfTurnRequestId: "turn" } }]],
    ["edit locked", [{ ...draft(), editable: false }]],
  ];
  for (const [name, messages] of cases) {
    await t.test(name, async (t) => {
      const harness = await setup(t, { messages });
      await assert.rejects(harness.behavior.callRpc("runDraft", target), /draft changed/i);
      assert.equal(harness.inspection.sdk.callsTo("threads.queuedMessages.send").length, 0);
    });
  }
});

test("a non-draft thread cannot be started by this action", async (t) => {
  for (const current of [
    { ...thread(), status: "active" },
    { ...thread(), archivedAt: 1 },
    { ...thread(), deletedAt: 1 },
    { ...thread(), originPluginId: "other" },
  ]) {
    const harness = await setup(t, { current });
    await assert.rejects(harness.behavior.callRpc("runDraft", target), /no longer/);
    assert.equal(harness.inspection.sdk.callsTo("threads.queuedMessages.send").length, 0);
  }
});

test("a concurrent request from another window cannot send the same draft again", async (t) => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let entered;
  const started = new Promise((resolve) => { entered = resolve; });
  const harness = await setup(t, { send: async () => { entered(); await gate; return { ok: true, delivery: "sent" }; } });
  const first = harness.behavior.callRpc("runDraft", target);
  await started;
  await assert.rejects(harness.behavior.callRpc("runDraft", target), /already being sent/);
  release();
  await first;
  assert.equal(harness.inspection.sdk.callsTo("threads.queuedMessages.send").length, 1);
});

test("a failed send releases the in-flight guard for a deliberate retry", async (t) => {
  let attempts = 0;
  const harness = await setup(t, { send: async () => {
    if (++attempts === 1) throw new Error("Machine disconnected");
    return { ok: true, delivery: "sent" };
  } });
  await assert.rejects(harness.behavior.callRpc("runDraft", target), /Machine disconnected/);
  assert.deepEqual(await harness.behavior.callRpc("runDraft", target), { kind: "sent" });
});

test("approval that still waits for provisioning is not reported as execution", async (t) => {
  const harness = await setup(t, { send: async () => ({
    ok: true,
    delivery: "queued",
    queuedMessage: { ...draft(), waitingOn: { kind: "provisioning" } },
  }) });
  assert.deepEqual(await harness.behavior.callRpc("runDraft", target), { kind: "queued", reason: "provisioning" });
});

test("RPC rejects malformed targets before reaching the queue", async (t) => {
  const harness = await setup(t);
  await assert.rejects(harness.behavior.callRpc("runDraft", { ...target, updatedAt: "10" }));
  assert.equal(harness.inspection.sdk.calls.length, 0);
});

test("the package uses public SDK APIs and declared UI and test dependencies", async () => {
  const result = await experimental_scanPublicSdkOnly(new URL("..", import.meta.url).pathname, { allow: [/^react$/, /^sonner$/, /^jsdom$/, /^@testing-library\/react$/, /^playwright-core$/] });
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.privateDependencies, []);
});

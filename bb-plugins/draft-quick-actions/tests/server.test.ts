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
const thread = () => makeThreadResponse({
  id: target.threadId,
  status: "pending",
  originPluginId: "held-drafts",
  providerId: "claude-code",
  projectId: "project",
  title: "Fix the flaky test",
  sectionId: "section",
  parentThreadId: "parent-thread",
  parentNotifications: "stuck",
});
const catalogs = {
  "claude-code": ["test-model", "claude-opus-5-5"],
  codex: ["gpt-6-luna", "gpt-6.2-sol", "shared-model"],
  other: ["shared-model"],
};
const environment = { type: "host", hostId: "host-1", workspace: { type: "personal" } };

async function setup(t, {
  messages = [draft()],
  current = thread(),
  send = async () => ({ ok: true, delivery: "sent" }),
  update = async (args) => ({ ...draft(), model: args.model, updatedAt: 20 }),
  metadata = { environment },
  spawn = async () => ({ id: "new-thread" }),
  remove = async () => ({ ok: true }),
} = {}) {
  const { bb, harness } = createFakePluginHost({
    pluginId: "draft-quick-actions",
    sdk: {
      threads: {
        get: async () => current,
        getPluginMetadata: async () => metadata,
        spawn,
        delete: remove,
        queuedMessages: { list: async () => messages, send, update },
      },
      providers: {
        catalog: async () => Object.keys(catalogs).map((id) => ({ id, displayName: id, enabled: true, available: true, info: null })),
        models: async ({ providerId }) => ({
          modelLoadError: null,
          models: catalogs[providerId].map((model) => ({ id: model, model })),
          permissionCeiling: "full",
          providers: [],
        }),
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

test("Run draft on the draft's provider changes the queued message in place and sends it", async (t) => {
  const harness = await setup(t);
  const execution = { providerId: "claude-code", model: "claude-opus-5-5", reasoningLevel: "high", serviceTier: "fast" };
  assert.deepEqual(await harness.behavior.callRpc("runDraft", { ...target, execution }), { kind: "sent" });
  assert.deepEqual(harness.inspection.sdk.callsTo("threads.queuedMessages.update"), [[{
    threadId: "draft-thread",
    queuedMessageId: "draft-message",
    expectedUpdatedAt: 10,
    model: "claude-opus-5-5",
    reasoningLevel: "high",
    serviceTier: "fast",
  }]]);
  assert.deepEqual(harness.inspection.sdk.callsTo("threads.queuedMessages.send"), [
    [{ threadId: "draft-thread", queuedMessageId: "draft-message", mode: "auto" }],
  ]);
  assert.equal(harness.inspection.sdk.callsTo("threads.spawn").length, 0);
  assert.equal(harness.inspection.sdk.callsTo("threads.delete").length, 0);
});

test("Run draft on another provider starts a copy of the draft there and deletes the draft", async (t) => {
  const content = [{ type: "text", text: "Fix the flaky test", mentions: [] }, { type: "image", url: "https://example.test/a.png" }];
  const harness = await setup(t, { messages: [{ ...draft(), content, permissionMode: "full" }] });
  const execution = { providerId: "codex", model: "gpt-6-luna", reasoningLevel: "low" };
  assert.deepEqual(await harness.behavior.callRpc("runDraft", { ...target, execution }), { kind: "replaced", threadId: "new-thread" });
  assert.deepEqual(harness.inspection.sdk.callsTo("threads.getPluginMetadata"), [[{ threadId: "draft-thread", pluginId: "held-drafts" }]]);
  assert.deepEqual(harness.inspection.sdk.callsTo("threads.spawn"), [[{
    projectId: "project",
    environment,
    input: content,
    title: "Fix the flaky test",
    parentThreadId: "parent-thread",
    parentNotifications: "stuck",
    sectionId: "section",
    providerId: "codex",
    model: "gpt-6-luna",
    reasoningLevel: "low",
    permissionMode: "full",
    origin: "plugin",
    originPluginId: "draft-quick-actions",
  }]]);
  assert.deepEqual(harness.inspection.sdk.callsTo("threads.delete"), [[{ threadId: "draft-thread", childThreadsConfirmed: false }]]);
  assert.equal(harness.inspection.sdk.callsTo("threads.queuedMessages.send").length, 0);
  assert.equal(harness.inspection.sdk.callsTo("threads.queuedMessages.update").length, 0);
});

test("plain Run draft moves a draft whose model only another provider offers to that provider", async (t) => {
  const harness = await setup(t, { messages: [{ ...draft(), model: "gpt-6.2-sol", reasoningLevel: "xhigh", serviceTier: "fast" }] });
  assert.deepEqual(await harness.behavior.callRpc("runDraft", target), { kind: "replaced", threadId: "new-thread" });
  const [[spawned]] = harness.inspection.sdk.callsTo("threads.spawn");
  assert.deepEqual(
    { providerId: spawned.providerId, model: spawned.model, reasoningLevel: spawned.reasoningLevel, serviceTier: spawned.serviceTier },
    { providerId: "codex", model: "gpt-6.2-sol", reasoningLevel: "xhigh", serviceTier: "fast" },
  );
  assert.deepEqual(harness.inspection.sdk.callsTo("threads.delete"), [[{ threadId: "draft-thread", childThreadsConfirmed: false }]]);
  assert.equal(harness.inspection.sdk.callsTo("threads.queuedMessages.send").length, 0);
});

test("plain Run draft asks for a choice when no provider or several other providers offer the model", async (t) => {
  for (const model of ["retired-model", "shared-model"]) {
    await t.test(model, async (t) => {
      const harness = await setup(t, { messages: [{ ...draft(), model }] });
      assert.deepEqual(await harness.behavior.callRpc("runDraft", target), { kind: "choose" });
      for (const call of ["threads.queuedMessages.send", "threads.queuedMessages.update", "threads.spawn", "threads.delete"]) {
        assert.equal(harness.inspection.sdk.callsTo(call).length, 0, call);
      }
    });
  }
});

test("the chooser starts on a provider that offers the draft's model", async (t) => {
  const levels = { reasoningLevel: "high", serviceTier: "default" };
  for (const [model, expected] of [
    ["test-model", { providerId: "claude-code", model: "test-model" }],
    ["gpt-6.2-sol", { providerId: "codex", model: "gpt-6.2-sol" }],
    ["shared-model", { providerId: "codex", model: "shared-model" }],
    ["retired-model", { providerId: "claude-code", model: "test-model" }],
  ]) {
    await t.test(model, async (t) => {
      const harness = await setup(t, { messages: [{ ...draft(), model, ...levels }] });
      assert.deepEqual(await harness.behavior.callRpc("chooserStart", target), {
        providerId: "claude-code",
        execution: { ...expected, ...levels },
      });
    });
  }
  const harness = await setup(t);
  await assert.rejects(harness.behavior.callRpc("chooserStart", { ...target, updatedAt: 9 }), /changed/);
});

test("a draft without a recorded environment is not moved to another provider", async (t) => {
  const harness = await setup(t, { metadata: {} });
  await assert.rejects(
    harness.behavior.callRpc("runDraft", { ...target, execution: { providerId: "codex", model: "gpt-6-luna" } }),
    /bb draft create/,
  );
  for (const call of ["threads.queuedMessages.send", "threads.spawn", "threads.delete"]) {
    assert.equal(harness.inspection.sdk.callsTo(call).length, 0, call);
  }
});

test("a failed start on the other provider leaves the draft in place", async (t) => {
  const harness = await setup(t, { spawn: async () => { throw new Error("Provider unavailable"); } });
  await assert.rejects(
    harness.behavior.callRpc("runDraft", { ...target, execution: { providerId: "codex", model: "gpt-6-luna" } }),
    /Provider unavailable/,
  );
  assert.equal(harness.inspection.sdk.callsTo("threads.delete").length, 0);
  assert.equal(harness.inspection.sdk.callsTo("threads.queuedMessages.send").length, 0);
});

test("a draft that cannot be deleted after its copy started is reported with the new thread", async (t) => {
  const harness = await setup(t, { remove: async () => { throw new Error("Thread is busy"); } });
  assert.deepEqual(
    await harness.behavior.callRpc("runDraft", { ...target, execution: { providerId: "codex", model: "gpt-6-luna" } }),
    { kind: "replaced-draft-kept", threadId: "new-thread", reason: "Thread is busy" },
  );
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
  const result = await experimental_scanPublicSdkOnly(new URL("..", import.meta.url).pathname, { allow: [/^react$/, /^react-dom$/, /^sonner$/, /^jsdom$/, /^@testing-library\/react$/, /^playwright-core$/] });
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.privateDependencies, []);
});

import assert from "node:assert/strict";
import { after, test } from "node:test";
import { Fragment, createElement } from "react";
import { JSDOM } from "jsdom";
import { makeQueueEntry } from "@get-bb/plugin-sdk/testing";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
for (const [name, value] of Object.entries({
  window: dom.window,
  document: dom.window.document,
  navigator: dom.window.navigator,
  HTMLElement: dom.window.HTMLElement,
  MutationObserver: dom.window.MutationObserver,
  IS_REACT_ACT_ENVIRONMENT: true,
})) Object.defineProperty(globalThis, name, { configurable: true, writable: true, value });
after(() => dom.window.close());

const { loadPluginApp, renderSlot } = await import("@get-bb/plugin-sdk/testing/app");
const { useSdk, useBbNavigate } = await import("@get-bb/plugin-sdk/app");
const { act, fireEvent } = await import("@testing-library/react");
const app = await loadPluginApp(() => import("../app.ts"));
const actions = new Map(app.threadActions.map((registration) => [registration.id, registration]));
const action = actions.get("run-draft");
const header = app.threadActions.filter((registration) => registration.placement === "header");
const Overlay = app.appOverlays[0].component;
const target = { threadId: "draft-thread", queuedMessageId: "draft-message", updatedAt: 10 };
const draft = () => makeQueueEntry({
  id: target.queuedMessageId,
  threadId: target.threadId,
  updatedAt: 10,
  originPluginId: "held-drafts",
  waitingOn: { kind: "plugin", pluginId: "held-drafts", reason: "Draft" },
});

function Row({ registration }) {
  const sdk = useSdk();
  const navigate = useBbNavigate();
  const data = registration.useData({ threadIds: [target.threadId, "another-thread"] });
  const item = registration.item({
    thread: { id: target.threadId, projectId: "project", status: "pending", archivedAt: null },
    data, sdk, navigate,
  });
  return item === null ? null : createElement("button", {
    disabled: item.disabled,
    onClick: () => item.run({ requestRename() {} }),
  }, item.label);
}

test("Run draft keeps its sidebar quick-action key as a menu action, and both actions also appear in the header", () => {
  assert.equal(action.placement ?? "menu", "menu", "draft-quick-actions/run-draft is the sidebar quick-action key and must stay a menu action.");
  assert.equal(actions.get("run-draft-on").placement ?? "menu", "menu");
  assert.deepEqual(header.map((registration) => registration.id).sort(), ["run-draft-header", "run-draft-on-header"]);
  assert.equal(app.appOverlays.length, 1);
});

for (const [surface, registration] of [["menu", action], ["header", actions.get("run-draft-header")]]) {
  test(`one ${surface} Run draft click sends the displayed target and blocks a second click`, async (t) => {
    let release;
    const completed = new Promise((resolve) => { release = resolve; });
    const calls = [];
    const slot = renderSlot({ component: () => createElement(Row, { registration }) }, {}, {
      sdk: { subscribe: () => () => {}, threads: { queue: { list: async () => [draft()] } } },
      rpc: { runDraft: async (input) => { calls.push(input); await completed; return { kind: "sent" }; } },
    });
    t.after(() => slot.lifecycle.unmount());
    const button = await slot.findByRole("button", { name: "Run draft" });
    await act(async () => button.click());
    assert.equal(button.disabled, true);
    assert.equal(button.textContent, "Sending draft…");
    await act(async () => button.click());
    assert.deepEqual(calls, [target]);
    await act(async () => { release(); await completed; });
    assert.equal(button.disabled, false);
    assert.equal(slot.inspection.navigateCalls.length, 0);
  });
}

test("a draft with an additional scheduled message has no unusable Run draft button", async (t) => {
  const held = draft();
  const scheduled = {
    ...draft(),
    id: "scheduled-message",
    originPluginId: null,
    state: "scheduled",
    sendAt: 1000,
    waitingOn: { kind: "time" },
  };
  const slot = renderSlot({ component: () => createElement(Row, { registration: action }) }, {}, {
    sdk: {
      subscribe: () => () => {},
      threads: { queue: { list: async ({ waitHolder }) => waitHolder ? [held] : [held, scheduled] } },
    },
  });
  t.after(() => slot.lifecycle.unmount());
  await act(async () => {});
  assert.equal(slot.queryByRole("button", { name: "Run draft" }) === null, true, "The sidebar must hide a draft whose complete queue is ineligible.");
});

test("queue events and reconnection update the button, and unmount disposes subscriptions", async () => {
  const callbacks = new Map();
  const disposed = [];
  let messages = [];
  let reads = 0;
  const slot = renderSlot({ component: () => createElement(Row, { registration: action }) }, {}, {
    sdk: {
      subscribe: ({ event, callback }) => { callbacks.set(event, callback); return () => disposed.push(event); },
      threads: { queue: { list: async () => { reads++; return messages; } } },
    },
  });
  await act(async () => {});
  assert.equal(slot.queryByRole("button"), null);
  assert.equal(reads, 1);
  messages = [draft()];
  await act(async () => {
    callbacks.get("thread:changed")({ changes: ["queue-changed"] });
    callbacks.get("thread:changed")({ changes: ["queue-changed"] });
    await new Promise((resolve) => setTimeout(resolve, 125));
  });
  assert.ok(await slot.findByRole("button", { name: "Run draft" }));
  assert.equal(reads, 2);
  messages = [];
  await act(async () => {
    callbacks.get("realtime:connection")({ state: "connected" });
    await new Promise((resolve) => setTimeout(resolve, 125));
  });
  assert.equal(slot.queryByRole("button"), null);
  slot.lifecycle.unmount();
  assert.deepEqual(disposed.sort(), ["realtime:connection", "thread:changed"]);
});

const startOnDraft = async () => ({
  providerId: "claude-code",
  execution: { providerId: "claude-code", model: "test-model", reasoningLevel: "medium", serviceTier: "default" },
});

function renderChooser(t, registration, { runDraft = async () => ({ kind: "sent" }), chooserStart = startOnDraft } = {}) {
  const calls = [];
  const slot = renderSlot({
    component: () => createElement(Fragment, null, createElement(Row, { registration }), createElement(Overlay)),
  }, {}, {
    sdk: {
      subscribe: () => () => {},
      threads: { queue: { list: async () => [draft()] } },
    },
    providers: { status: "ready", providers: [{ id: "codex", displayName: "Codex" }] },
    rpc: {
      runDraft: async (input) => { calls.push(input); return runDraft(input); },
      chooserStart: async (input) => { assert.deepEqual(input, target); return chooserStart(input); },
    },
  });
  t.after(() => slot.lifecycle.unmount());
  const open = async () => {
    const button = await slot.findByRole("button", { name: "Run draft on…" });
    await act(async () => button.click());
    await slot.findByLabelText("Provider ID");
    return slot.getByRole("dialog", { name: "Run draft on…" });
  };
  return { slot, calls, open };
}

for (const [surface, id] of [["menu", "run-draft-on"], ["header", "run-draft-on-header"]]) {
  test(`the ${surface} Run draft on… action opens the chooser on the draft's provider and model`, async (t) => {
    const { slot, calls, open } = renderChooser(t, actions.get(id));
    await open();
    assert.equal(slot.getByLabelText("Provider ID").value, "claude-code");
    assert.equal(slot.getByLabelText("Model").value, "test-model");
    await act(async () => slot.getByRole("button", { name: "Cancel" }).click());
    assert.equal(slot.queryByRole("dialog"), null);
    assert.deepEqual(calls, []);
  });
}

test("the chooser starts where the server finds the draft's model and says the draft will move", async (t) => {
  const { slot, open } = renderChooser(t, actions.get("run-draft-on"), {
    chooserStart: async () => ({
      providerId: "claude-code",
      execution: { providerId: "codex", model: "gpt-6-luna", reasoningLevel: "medium", serviceTier: "default" },
    }),
  });
  const dialog = await open();
  assert.equal(slot.getByLabelText("Provider ID").value, "codex");
  assert.equal(slot.getByLabelText("Model").value, "gpt-6-luna");
  assert.match(dialog.textContent, /new Codex thread.*deletes this draft/);
});

test("plain Run draft opens the chooser when the server cannot tell which provider to use", async (t) => {
  const { slot, calls } = renderChooser(t, action, { runDraft: async () => ({ kind: "choose" }) });
  await act(async () => (await slot.findByRole("button", { name: "Run draft" })).click());
  assert.ok(await slot.findByRole("dialog", { name: "Run draft on…" }));
  assert.deepEqual(calls, [target]);
});

test("Run sends the picked model and opens the new thread when the draft moves to another provider", async (t) => {
  const { slot, calls, open } = renderChooser(t, actions.get("run-draft-on-header"), {
    runDraft: async () => ({ kind: "replaced", threadId: "new-thread" }),
  });
  const dialog = await open();
  assert.doesNotMatch(dialog.textContent, /deletes this draft/);
  fireEvent.change(slot.getByLabelText("Provider ID"), { target: { value: "codex" } });
  fireEvent.change(slot.getByLabelText("Model"), { target: { value: "gpt-6-luna" } });
  await act(async () => slot.getByRole("button", { name: "Apply execution selection" }).click());
  assert.match(dialog.textContent, /new Codex thread.*deletes this draft/);
  await act(async () => slot.getByRole("button", { name: "Run" }).click());
  assert.deepEqual(calls, [{
    ...target,
    execution: { providerId: "codex", model: "gpt-6-luna", reasoningLevel: "medium", serviceTier: "default" },
  }]);
  assert.deepEqual(slot.inspection.navigateCalls, [{ method: "toThread", threadId: "new-thread" }]);
  assert.equal(slot.queryByRole("dialog"), null);
});

test("Escape and a tap outside the chooser close it without running the draft", async (t) => {
  const { slot, calls, open } = renderChooser(t, actions.get("run-draft-on"));
  await open();
  fireEvent.keyDown(document, { key: "Escape" });
  assert.equal(slot.queryByRole("dialog"), null);
  const dialog = await open();
  fireEvent.click(dialog);
  assert.ok(slot.queryByRole("dialog"), "A tap inside the dialog keeps it open.");
  fireEvent.click(dialog.parentElement);
  assert.equal(slot.queryByRole("dialog"), null);
  assert.deepEqual(calls, []);
});

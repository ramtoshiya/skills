import { createFakePluginHost, makeMessageDispatchHookContext, makeQueueEntry, makeThreadResponse } from "@get-bb/plugin-sdk/testing";
import { afterEach, describe, expect, it, vi } from "vitest";
import plugin from "./server";

type Host = ReturnType<typeof createFakePluginHost>;
type Row = ReturnType<typeof makeQueueEntry>;
type Sent = { threadId: string; senderThreadId?: string; inbox: boolean; text: string };

const THREADS = {
  ROOT: { projectId: "proj_a", parentThreadId: null, providerId: "claude-code", status: "idle" },
  LEAD: { projectId: "proj_a", parentThreadId: "ROOT", providerId: "claude-code", status: "active" },
  WORKER: { projectId: "proj_a", parentThreadId: "LEAD", providerId: "codex", status: "idle" },
  RELAY: { projectId: "proj_a", parentThreadId: "LEAD", providerId: "codex", status: "idle" },
  DRAFT: { projectId: "proj_a", parentThreadId: "LEAD", providerId: "codex", status: "pending" },
  GONE: { projectId: "proj_a", parentThreadId: "LEAD", providerId: "codex", status: "idle", archived: true },
  OTHER: { projectId: "proj_b", parentThreadId: null, providerId: "codex", status: "idle" },
} as const;
type Id = keyof typeof THREADS;

const NEST: Record<string, unknown> = { RELAY: { logicalParentThreadId: "WORKER" } };

function thread(id: Id) {
  const shape = THREADS[id];
  return makeThreadResponse({
    id,
    projectId: shape.projectId,
    parentThreadId: shape.parentThreadId,
    providerId: shape.providerId,
    status: shape.status,
    environmentId: `env_${id}`,
    archivedAt: "archived" in shape ? 1 : null,
  });
}

function command(id: string, cmd: string, done: { exitCode: number; output: string } | null, createdAt = 2_000) {
  const item = { type: "commandExecution", id, command: cmd, status: done ? "completed" : "inProgress" };
  return done
    ? { type: "item/completed", createdAt, data: { item: { ...item, exitCode: done.exitCode, aggregatedOutput: done.output } } }
    : { type: "item/started", createdAt, data: { item } };
}
const turnStarted = { type: "turn/started", createdAt: 1_000, data: {} };
const message = (id: string) => ({ type: "item/completed", data: { item: { type: "agentMessage", id } } });

let host: Host | null = null;

function start(
  options: {
    mailTags?: Record<string, Record<string, true>>;
    events?: Record<string, unknown[]>;
    output?: string;
    beforeUpdate?: (rows: Map<string, Row>, call: number) => void;
  } = {},
) {
  const sent: Sent[] = [];
  const rows = new Map<string, Row>();
  const deleted: string[] = [];
  const holds: Array<{ id: string; sendAt: number | null }> = [];
  const mailTags = options.mailTags ?? {};
  const events = options.events ?? {};
  const pages: number[] = [];
  let updateCalls = 0;
  host = createFakePluginHost({
    pluginId: "mail",
    sdk: {
      threads: {
        get: async ({ threadId }) => thread(threadId as Id),
        list: async (args = {}) => {
          const all = (Object.keys(THREADS) as Id[]).map(thread).filter((t) => args.archived !== false || t.archivedAt === null);
          const offset = args.offset ?? 0;
          pages.push(offset);
          return all.slice(offset, offset + (args.limit ?? all.length)) as never;
        },
        experimental_listPluginMetadata: async ({ pluginId, threadIds }) => {
          const source: Record<string, unknown> = pluginId === "nest" ? NEST : mailTags;
          return { threads: threadIds.flatMap((threadId) => (source[threadId] ? [{ threadId, metadata: source[threadId] }] : [])) } as never;
        },
        updatePluginMetadata: async (args) => {
          const current = { ...(mailTags[args.threadId] ?? {}) } as Record<string, unknown>;
          Object.assign(current, args.set ?? {});
          for (const key of args.remove ?? []) delete current[key];
          mailTags[args.threadId] = current as Record<string, true>;
          return current as never;
        },
        getPluginMetadata: async ({ threadId }) => (mailTags[threadId] ?? {}) as never,
        send: async (args) => {
          const first = args.input[0];
          sent.push({
            threadId: args.threadId,
            senderThreadId: args.senderThreadId,
            inbox: args.pluginSubmission?.pluginId === "mail",
            text: first && first.type === "text" ? first.text : "",
          });
          return { delivery: "sent" } as never;
        },
        output: async () => ({ output: options.output ?? "DONE: 42" }) as never,
        events: {
          list: async ({ threadId, types, limit }) => {
            if (Number(limit) > 100) throw new Error("HTTP 400: Thread event limit cannot exceed 100");
            return (events[threadId] ?? []).filter((event) => !types || types.includes((event as { type: string }).type as never)) as never;
          },
        },
        queuedMessages: {
          list: async ({ threadId }) => [...rows.values()].filter((row) => row.threadId === threadId) as never,
          delete: async ({ queuedMessageId }) => {
            rows.delete(queuedMessageId);
            deleted.push(queuedMessageId);
            return undefined as never;
          },
          update: async ({ queuedMessageId, sendAt, expectedUpdatedAt }) => {
            options.beforeUpdate?.(rows, ++updateCalls);
            if (rows.get(queuedMessageId)?.updatedAt !== expectedUpdatedAt) {
              throw new Error("HTTP 409: Queued message changed since editing began");
            }
            if (typeof sendAt === "number" && sendAt <= Date.now()) {
              throw new Error("HTTP 400: sendAt must be in the future; pass null to clear the send time");
            }
            const row = rows.get(queuedMessageId)!;
            const next = { ...row, sendAt: sendAt ?? null, updatedAt: row.updatedAt + 1 };
            rows.set(queuedMessageId, next);
            holds.push({ id: queuedMessageId, sendAt: sendAt ?? null });
            void host?.harness.emitThreadEvent("message.queued", { entry: next });
            return next as never;
          },
        },
      },
    },
  });
  plugin(host.bb);
  const harness = host.harness;
  async function notice(systemNotice: Record<string, unknown>, id = "row_1"): Promise<Row> {
    const row = makeQueueEntry({ id, threadId: "LEAD", updatedAt: 100, systemNotice: systemNotice as never });
    rows.set(row.id, row);
    await harness.emitThreadEvent("message.queued", { entry: row });
    return row;
  }
  return { harness, sent, rows, deleted, holds, mailTags, pages, notice, updateCalls: () => updateCalls };
}

const completed = (childId: string) => ({
  kind: "child-completed",
  subject: { kind: "thread", threadId: childId, threadName: childId, outcomes: [{ threadId: childId, status: "completed" }] },
});

afterEach(async () => {
  vi.useRealTimers();
  await host?.harness.lifecycle.dispose();
  host = null;
});

describe("inbox", () => {
  const inbox = { pluginId: "mail", data: { kind: "inbox" } };
  const heldByMail = { id: "held", waitingOn: { kind: "plugin" as const, pluginId: "mail", reason: "inbox" } };
  it.each([
    ["holds an inbox message that would start a turn", { attempt: "start-turn", experimental_submission: inbox }, "wait"],
    ["holds an inbox message sent while the recipient's turn runs", { attempt: "join-turn", experimental_submission: inbox }, "wait"],
    ["keeps an inbox message out of the turn that was running when it was held", { attempt: "join-turn", queuedMessages: [heldByMail] }, "wait"],
    ["starts a turn for a --wake message, which bb also marks as sent by mail", { attempt: "start-turn", originPluginId: "mail" }, "proceed"],
    ["keeps holding an inbox message when bb re-attempts it", { attempt: "start-turn", queuedMessages: [heldByMail] }, "wait"],
    ["starts the turn when a wake message is drained with held inbox messages", { attempt: "start-turn", queuedMessages: [heldByMail, { id: "wake", waitingOn: null }] }, "proceed"],
    ["leaves other senders alone", { attempt: "start-turn" }, "proceed"],
  ] as const)("%s", async (_name, facts, action) => {
    const { harness } = start();
    const hook = harness.registrations.hooks["message.dispatch"]!;
    const decision = await hook(makeMessageDispatchHookContext(facts as never));
    expect(decision.action).toBe(action);
  });

  it("delivers held inbox messages into the recipient's next turn", async () => {
    const { harness } = start();
    const hook = harness.registrations.hooks["message.dispatch"]!;
    harness.sdk.stub("threads.queue.list", async () => [makeQueueEntry({ id: "held", threadId: "LEAD" })] as never);
    await harness.emitThreadEvent("thread.active", { thread: thread("LEAD") });
    const joined = await hook(makeMessageDispatchHookContext({ attempt: "join-turn", queuedMessages: [heldByMail] }));
    expect(joined.action).toBe("proceed");
  });

  it("keeps holding an inbox message that a running turn ended before it was delivered", async () => {
    const { harness } = start();
    const hook = harness.registrations.hooks["message.dispatch"]!;
    harness.sdk.stub("threads.queue.list", async () => [makeQueueEntry({ id: "held", threadId: "LEAD" })] as never);
    await harness.emitThreadEvent("thread.active", { thread: thread("LEAD") });
    await hook(makeMessageDispatchHookContext({ attempt: "join-turn", queuedMessages: [heldByMail] }));
    const retried = await hook(makeMessageDispatchHookContext({ attempt: "start-turn", queuedMessages: [{ id: "held", waitingOn: null }] }));
    expect(retried.action).toBe("wait");
    await harness.emitThreadEvent("message.dispatched", { entry: makeQueueEntry({ id: "held" }) });
    const later = await hook(makeMessageDispatchHookContext({ attempt: "start-turn", queuedMessages: [{ id: "held", waitingOn: null }] }));
    expect(later.action).toBe("proceed");
  });

  it("lets the message through when reading the context throws", async () => {
    const { harness } = start();
    const hook = harness.registrations.hooks["message.dispatch"]!;
    const broken = makeMessageDispatchHookContext({ attempt: "start-turn" });
    Object.defineProperty(broken, "queuedMessages", {
      get() {
        throw new Error("boom");
      },
    });
    expect(await hook(broken)).toEqual({ action: "proceed" });
  });

  it("asks bb to recheck held messages when the recipient starts a turn", async () => {
    const { harness } = start();
    harness.sdk.stub("threads.queue.list", async () => [makeQueueEntry()] as never);
    await harness.emitThreadEvent("thread.active", { thread: thread("LEAD") });
    expect(harness.recheckCount).toBe(1);
  });
});

describe("ACP recipients", () => {
  const acp = (status: "active" | "idle" = "active") => makeThreadResponse({ id: "HERMES", providerId: "acp-hermes-agent", status });
  const claude = makeThreadResponse({ id: "CLAUDE", providerId: "claude-code", status: "active" });
  const inboxSubmission = { pluginId: "mail", data: { kind: "inbox" } };
  const heldRow = (initiator: "user" | "agent" | "system" = "agent", id = "held") => ({
    id,
    initiator,
    waitingOn: { kind: "plugin" as const, pluginId: "mail", reason: "inbox" },
  });
  const decide = (harness: ReturnType<typeof start>["harness"], facts: Record<string, unknown>) =>
    harness.registrations.hooks["message.dispatch"]!(makeMessageDispatchHookContext(facts as never));

  it.each([
    ["an agent message", { initiator: "agent" }, "wait"],
    ["a plugin or system notice", { initiator: "system" }, "wait"],
    ["a mail inbox message", { initiator: "agent", experimental_submission: inboxSubmission }, "wait"],
    ["a user message", { initiator: "user" }, "proceed"],
    ["a group that includes a user message", { initiator: "mixed", queuedMessages: [heldRow("agent", "a"), { id: "u", initiator: "user", waitingOn: null }] }, "proceed"],
  ] as const)("decides for %s that would join a running turn: %s", async (_name, facts, action) => {
    const { harness } = start();
    const decision = await decide(harness, { attempt: "join-turn", thread: acp(), ...facts });
    expect(decision.action).toBe(action);
  });

  it("starts a turn for an agent message when the recipient is idle", async () => {
    const { harness } = start();
    expect((await decide(harness, { attempt: "start-turn", initiator: "agent", thread: acp("idle") })).action).toBe("proceed");
  });

  it.each(["claude-code", "codex"])("still lets an agent message join a running %s turn", async (providerId) => {
    const { harness } = start();
    const thread = makeThreadResponse({ providerId, status: "active" });
    expect((await decide(harness, { attempt: "join-turn", initiator: "agent", thread })).action).toBe("proceed");
  });

  it("keeps a held inbox message out of the turn that a user starts, then starts its own turn when the recipient goes idle", async () => {
    const { harness } = start();
    harness.sdk.stub("threads.queue.list", async () => [makeQueueEntry({ id: "held", threadId: "HERMES" })] as never);
    const row = heldRow();
    await decide(harness, { attempt: "start-turn", initiator: "agent", thread: acp("idle"), experimental_submission: inboxSubmission });

    await harness.emitThreadEvent("thread.active", { thread: acp() });
    expect(harness.recheckCount).toBe(0);
    expect((await decide(harness, { attempt: "join-turn", initiator: "agent", thread: acp(), queuedMessages: [row] })).action).toBe("wait");

    await harness.emitThreadEvent("thread.idle", { thread: acp("idle"), lastAssistantText: null });
    expect(harness.recheckCount).toBe(1);
    expect((await decide(harness, { attempt: "start-turn", initiator: "agent", thread: acp("idle"), queuedMessages: [row] })).action).toBe("proceed");
  });

  it("holds an agent message sent into a running turn until the recipient goes idle", async () => {
    const { harness } = start();
    harness.sdk.stub("threads.queue.list", async () => [makeQueueEntry({ id: "steer", threadId: "HERMES" })] as never);
    const row = heldRow("agent", "steer");
    expect((await decide(harness, { attempt: "join-turn", initiator: "agent", thread: acp() })).action).toBe("wait");
    await harness.emitThreadEvent("message.queued", { entry: makeQueueEntry({ id: "steer", threadId: "HERMES", waitingOn: row.waitingOn }) });
    expect((await decide(harness, { attempt: "start-turn", initiator: "agent", thread: acp("idle"), queuedMessages: [row] })).action).toBe("wait");

    await harness.emitThreadEvent("thread.idle", { thread: acp("idle"), lastAssistantText: null });
    expect((await decide(harness, { attempt: "start-turn", initiator: "agent", thread: acp("idle"), queuedMessages: [row] })).action).toBe("proceed");
  });

  describe("a recheck that bb drops", () => {
    const RETRY_MS = 1_500;
    async function goIdleHolding(options: { stillHeld?: () => boolean; status?: () => "idle" | "active" } = {}) {
      vi.useFakeTimers();
      const { harness } = start();
      const stillHeld = options.stillHeld ?? (() => true);
      harness.sdk.stub("threads.queue.list", async () => (stillHeld() ? [makeQueueEntry({ id: "held", threadId: "HERMES" })] : []) as never);
      harness.sdk.stub("threads.get", async () => acp(options.status?.() ?? "idle") as never);
      await harness.emitThreadEvent("thread.idle", { thread: acp("idle"), lastAssistantText: null });
      return harness;
    }

    it("asks bb again while the held message is still waiting and the thread is idle", async () => {
      const harness = await goIdleHolding();
      expect(harness.recheckCount).toBe(1);
      await vi.advanceTimersByTimeAsync(RETRY_MS);
      expect(harness.recheckCount).toBe(2);
    });

    it("stops asking once bb has sent the held message", async () => {
      let held = true;
      const harness = await goIdleHolding({ stillHeld: () => held });
      held = false;
      await vi.advanceTimersByTimeAsync(RETRY_MS * 3);
      expect(harness.recheckCount).toBe(1);
    });

    it("stops asking when the thread has started another turn", async () => {
      let status: "idle" | "active" = "idle";
      const harness = await goIdleHolding({ status: () => status });
      status = "active";
      await vi.advanceTimersByTimeAsync(RETRY_MS * 3);
      expect(harness.recheckCount).toBe(1);
    });

    it("does not ask forever when the message never goes out", async () => {
      const harness = await goIdleHolding();
      await vi.advanceTimersByTimeAsync(60_000);
      const asked = harness.recheckCount;
      await vi.advanceTimersByTimeAsync(60_000);
      expect(harness.recheckCount).toBe(asked);
    });

    it("does not release a message that was queued after the thread went idle", async () => {
      let rows = [makeQueueEntry({ id: "held", threadId: "HERMES" })];
      vi.useFakeTimers();
      const { harness } = start();
      harness.sdk.stub("threads.queue.list", async () => rows as never);
      harness.sdk.stub("threads.get", async () => acp("idle") as never);
      await harness.emitThreadEvent("thread.idle", { thread: acp("idle"), lastAssistantText: null });
      rows = [makeQueueEntry({ id: "later", threadId: "HERMES" })];
      await vi.advanceTimersByTimeAsync(RETRY_MS);
      expect(harness.recheckCount).toBe(1);
      const row = { id: "later", initiator: "agent" as const, waitingOn: { kind: "plugin" as const, pluginId: "mail", reason: "inbox" } };
      const decision = await decide(harness, { attempt: "start-turn", initiator: "agent", thread: acp("idle"), queuedMessages: [row] });
      expect(decision.action).toBe("wait");
    });
  });

  describe("self-compaction on a Hermes thread", () => {
    const schedule = (resume?: boolean) => ({
      type: "item/completed",
      data: {
        item: {
          type: "toolCall",
          id: "t1",
          tool: "other",
          arguments: { action: "compact", ...(resume === undefined ? {} : { resume }), note: "# note" },
          status: "completed",
          result: `self_compact result\n- **status:** scheduled\n- **resume:** ${resume ?? true}`,
          presentation: { title: "self_compact" },
        },
      },
    });
    const scheduledTurn = (resume?: boolean) => [message("m2"), schedule(resume), message("m1"), turnStarted];
    const compactionTurn = [{ type: "thread/compacted", data: {} }, message("summary"), turnStarted];
    const resumeTurn = [message("resumed"), turnStarted];

    async function goIdle(events: Record<string, unknown[]>, failReads = false) {
      const started = start({ events });
      started.harness.sdk.stub("threads.queue.list", async () => [makeQueueEntry({ id: "held", threadId: "HERMES" })] as never);
      if (failReads) {
        started.harness.sdk.stub("threads.events.list", async () => {
          throw new Error("events offline");
        });
      }
      await started.harness.emitThreadEvent("thread.idle", { thread: acp("idle"), lastAssistantText: null });
      return started.harness.recheckCount;
    }

    it("keeps held messages out of the gap before the helper requests compaction", async () => {
      expect(await goIdle({ HERMES: scheduledTurn() })).toBe(0);
    });

    it("keeps holding after bb's compaction turn, until the resume message's turn ends", async () => {
      expect(await goIdle({ HERMES: [...compactionTurn, ...scheduledTurn()] })).toBe(0);
    });

    it("releases held messages when the resume turn ends", async () => {
      expect(await goIdle({ HERMES: [...resumeTurn, ...compactionTurn, ...scheduledTurn()] })).toBe(1);
    });

    it("releases held messages when the thread waits for the user with resume false", async () => {
      expect(await goIdle({ HERMES: scheduledTurn(false) })).toBe(1);
    });

    it("releases held messages when the turn did not schedule a compaction", async () => {
      expect(await goIdle({ HERMES: [message("m1"), turnStarted] })).toBe(1);
    });

    it("releases held messages when the events cannot be read", async () => {
      expect(await goIdle({ HERMES: scheduledTurn() }, true)).toBe(1);
    });
  });

  it("does not release held messages when a Claude Code thread goes idle", async () => {
    const { harness } = start();
    harness.sdk.stub("threads.queue.list", async () => [makeQueueEntry({ id: "held", threadId: "CLAUDE" })] as never);
    await harness.emitThreadEvent("thread.idle", { thread: { ...claude, status: "idle" }, lastAssistantText: null });
    expect(harness.recheckCount).toBe(0);
  });
});

describe("bb mail send", () => {
  it("sends to the inbox by default and wakes with --wake", async () => {
    const { harness, sent } = start();
    expect((await harness.runCli(["send", "WORKER", "--message", "fyi"], { threadId: "LEAD" })).exitCode).toBe(0);
    expect((await harness.runCli(["send", "WORKER", "--wake", "--message", "now"], { threadId: "LEAD" })).exitCode).toBe(0);
    expect(sent).toEqual([
      { threadId: "WORKER", senderThreadId: "LEAD", inbox: true, text: "fyi" },
      { threadId: "WORKER", senderThreadId: "LEAD", inbox: false, text: "now" },
    ]);
  });

  it.each([
    ["LEAD", "your own thread"],
    ["GONE", "archived"],
    ["DRAFT", "held draft"],
  ])("refuses to send directly to %s", async (target, reason) => {
    const { harness, sent } = start();
    const result = await harness.runCli(["send", target, "--message", "hi"], { threadId: "LEAD" });
    expect(result.exitCode).not.toBe(0);
    expect(result.stderr ?? "").toContain(reason);
    expect(sent).toEqual([]);
  });

  it("selects by the logical tree, skipping the sender, the draft, and the archived thread", async () => {
    const { harness, sent } = start();
    const result = await harness.runCli(["send", "--where", "parent=ROOT", "--message", "main moved", "--json"], { threadId: "LEAD" });
    const report = JSON.parse(result.stdout ?? "{}");
    expect(report.sent.sort()).toEqual(["RELAY", "WORKER"]);
    expect(report.skipped).toEqual([
      { id: "LEAD", reason: "sender" },
      { id: "DRAFT", reason: "draft" },
    ]);
    expect(sent.every((message) => message.text === "[mail to parent=ROOT]\n\nmain moved")).toBe(true);

    const fromRoot = JSON.parse((await harness.runCli(["who", "--where", "parent=ROOT", "--json"], { threadId: "WORKER" })).stdout ?? "{}");
    expect(fromRoot.to.sort()).toEqual(["LEAD", "RELAY"]);
    expect(fromRoot.skipped).toEqual([
      { id: "WORKER", reason: "sender" },
      { id: "DRAFT", reason: "draft" },
    ]);
  });

  it.each([
    [["parent=WORKER"], ["RELAY"]],
    [["provider=codex"], ["OTHER", "RELAY", "WORKER"]],
    [["provider=codex project=proj_a"], ["RELAY", "WORKER"]],
    [["project=proj_a", "role=reviewer"], ["WORKER"]],
    [["role=reviewer"], ["OTHER", "WORKER"]],
    [["urgent"], ["OTHER"]],
  ])("who --where %j reaches %j", async (where, expected) => {
    const { harness } = start({ mailTags: { WORKER: { "tag:role=reviewer": true }, OTHER: { "tag:role=reviewer": true, "tag:urgent": true } } });
    const argv = ["who", ...where.flatMap((term) => ["--where", term]), "--json"];
    const report = JSON.parse((await harness.runCli(argv, { threadId: "LEAD" })).stdout ?? "{}");
    expect(report.to.sort()).toEqual(expected);
  });

  it.each([["project="], ["parent"], ["bad tag!"]])("rejects the selector %j", async (term) => {
    const { harness, sent } = start();
    const result = await harness.runCli(["send", "--where", term, "--message", "hi"], { threadId: "LEAD" });
    expect(result.exitCode).not.toBe(0);
    expect(sent).toEqual([]);
  });
});

describe("bb mail tag", () => {
  it("adds, lists, and removes tags without touching other tags", async () => {
    const { harness } = start({ mailTags: { WORKER: { "tag:team=web": true } } });
    expect((await harness.runCli(["tag", "add", "WORKER", "role=reviewer", "urgent"])).stdout).toBe("role=reviewer team=web urgent");
    expect((await harness.runCli(["tag", "rm", "WORKER", "urgent"])).stdout).toBe("role=reviewer team=web");
    expect((await harness.runCli(["tag", "ls"], { threadId: "WORKER" })).stdout).toBe("role=reviewer team=web");
  });

  it("refuses a built-in selector key as a tag", async () => {
    const { harness, mailTags } = start();
    expect((await harness.runCli(["tag", "add", "WORKER", "project=x"])).exitCode).not.toBe(0);
    expect(mailTags.WORKER).toBeUndefined();
  });
});

describe("built-in notices", () => {
  it.each(["ownership-assigned", "ownership-removed", "ownership-batch"])("drops a %s notice", async (kind) => {
    const { notice, deleted } = start();
    await notice({ kind, subject: { kind: "thread", threadId: "WORKER" } });
    expect(deleted).toEqual(["row_1"]);
  });

  it("keeps environment-directory and merged completion notices", async () => {
    const { notice, deleted, holds } = start();
    await notice({ kind: "environment-directory-updated", subject: null }, "row_env");
    await notice(
      {
        kind: "child-outcome-batch",
        subject: { kind: "thread", threadId: "WORKER", outcomes: [{ threadId: "WORKER" }, { threadId: "RELAY" }] },
      },
      "row_batch",
    );
    expect(deleted).toEqual([]);
    expect(holds).toEqual([]);
  });

  it("drops the completion of a turn that ended to self-compact, even after bb's compaction turn", async () => {
    const { notice, deleted } = start({
      events: {
        WORKER: [
          message("m2"),
          { type: "thread/compacted", data: {} },
          turnStarted,
          message("m1"),
          command("c1", 'node "/x/bb-compact.mjs" run "/h/note.md" --launch-seq 3 --turn-id t1', { exitCode: 0, output: "" }),
          turnStarted,
        ],
      },
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual(["row_1"]);
  });

  describe("Hermes self-compaction", () => {
    const hermesCall = (resume?: boolean, status = "scheduled") => ({
      type: "item/completed",
      data: {
        item: {
          type: "toolCall",
          id: "t1",
          tool: "other",
          arguments: { action: "compact", ...(resume === undefined ? {} : { resume }), note: "# note" },
          status: "completed",
          result: `self_compact result\n- **status:** ${status}\n- **resume:** ${resume ?? true}`,
          presentation: { title: "self_compact" },
        },
      },
    });
    const scheduledTurn = (resume?: boolean, status?: string) => [message("m2"), hermesCall(resume, status), message("m1"), turnStarted];
    const compactionTurn = [{ type: "thread/compacted", data: {} }, message("summary"), turnStarted];

    it("drops the turn that scheduled the compaction", async () => {
      const { notice, deleted } = start({ events: { WORKER: scheduledTurn() } });
      await notice(completed("WORKER"));
      expect(deleted).toEqual(["row_1"]);
    });

    it("drops bb's compaction turn after it, which carries an agent message", async () => {
      const { notice, deleted } = start({ events: { WORKER: [...compactionTurn, ...scheduledTurn()] } });
      await notice(completed("WORKER"));
      expect(deleted).toEqual(["row_1"]);
    });

    it("delivers the completion when the child waits for the user with resume false", async () => {
      const { notice, deleted } = start({ events: { WORKER: scheduledTurn(false) } });
      await notice(completed("WORKER"));
      expect(deleted).toEqual([]);
    });

    it("delivers the completion when the schedule was refused", async () => {
      const { notice, deleted } = start({ events: { WORKER: scheduledTurn(undefined, "refused") } });
      await notice(completed("WORKER"));
      expect(deleted).toEqual([]);
    });

    it("delivers the completion of a turn that only read the note", async () => {
      const read = hermesCall();
      (read.data.item.arguments as { action: string }).action = "read";
      const { notice, deleted } = start({ events: { WORKER: [message("m1"), read, turnStarted] } });
      await notice(completed("WORKER"));
      expect(deleted).toEqual([]);
    });
  });

  it("delivers the completion of a turn whose self-compact launch failed", async () => {
    const { notice, deleted } = start({
      events: { WORKER: [message("m1"), command("c1", "node bb-compact.mjs run missing.md", { exitCode: 1, output: "note not found" }), turnStarted] },
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual([]);
  });

  it("delivers the completion of a turn that only asked about compaction with --no-resume", async () => {
    const { notice, deleted } = start({
      events: { WORKER: [command("c1", "node bb-compact.mjs run note.md --no-resume", { exitCode: 0, output: "" }), turnStarted] },
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual([]);
  });

  describe("the [no-op] marker", () => {
    it("drops a completion whose reply is only the marker", async () => {
      const { notice, deleted } = start({ output: "  [no-op]\n", events: { WORKER: [message("m1"), turnStarted] } });
      await notice(completed("WORKER"));
      expect(deleted).toEqual(["row_1"]);
    });

    it.each(["[no-op] Merged abc123 into main.", "Done. [no-op]", "[no-op] [no-op]", "no-op"])("delivers the reply %j", async (reply) => {
      const { notice, deleted } = start({ output: reply, events: { WORKER: [message("m1"), turnStarted] } });
      await notice(completed("WORKER"));
      expect(deleted).toEqual([]);
    });
  });

  it("drops a completion whose reply the parent's wait already printed", async () => {
    const { notice, deleted } = start({
      events: {
        WORKER: [message("m1"), turnStarted],
        LEAD: [command("w1", "bb thread wait WORKER --timeout 600 && bb thread output WORKER", { exitCode: 0, output: "Thread WORKER reached status idle.\nDONE: 42\n" })],
      },
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual(["row_1"]);
  });

  it("delivers a completion when the wait that printed the same reply returned before the child's turn started", async () => {
    const { notice, deleted } = start({
      events: {
        WORKER: [message("m2"), turnStarted],
        LEAD: [command("w1", "bb thread wait WORKER && bb thread output WORKER", { exitCode: 0, output: "DONE: 42" }, 500)],
      },
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual([]);
  });

  it.each([
    ["a bare wait that printed only the status", { exitCode: 0, output: "Thread WORKER reached status idle." }],
    ["a wait that timed out", { exitCode: 2, output: "Timed out waiting for WORKER." }],
  ])("delivers the completion after %s", async (_name, done) => {
    const { notice, deleted, holds } = start({ events: { LEAD: [command("w1", "bb thread wait WORKER --timeout 5 && bb thread output WORKER", done)] } });
    await notice(completed("WORKER"));
    expect(deleted).toEqual([]);
    expect(holds).toEqual([]);
  });

  it("holds the completion while the parent's wait runs, then drops it when the wait prints the reply", async () => {
    vi.useFakeTimers();
    const lead: unknown[] = [command("w1", "bb thread wait WORKER && bb thread output WORKER", null)];
    const { notice, deleted, holds } = start({ events: { LEAD: lead, WORKER: [message("m1"), turnStarted] } });
    await notice(completed("WORKER"));
    await vi.advanceTimersByTimeAsync(0);
    expect(holds).toHaveLength(1);
    expect(deleted).toEqual([]);
    lead.unshift(command("w1", "bb thread wait WORKER && bb thread output WORKER", { exitCode: 0, output: "DONE: 42" }));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(deleted).toEqual(["row_1"]);
  });

  it("releases a held completion when the parent's wait is still running at the hold limit", async () => {
    vi.useFakeTimers();
    const { notice, deleted, holds, rows } = start({ events: { LEAD: [command("w1", "bb thread wait WORKER --timeout 3600", null)] } });
    await notice(completed("WORKER"));
    await vi.advanceTimersByTimeAsync(31_000);
    expect(deleted).toEqual([]);
    expect(holds.map((hold) => hold.sendAt === null)).toEqual([false, true]);
    expect(rows.get("row_1")!.sendAt).toBeNull();
  });

  it("delivers a held notice that bb merged another child into", async () => {
    vi.useFakeTimers();
    const lead: unknown[] = [command("w1", "bb thread wait WORKER && bb thread output WORKER", null)];
    const { notice, deleted, rows } = start({ events: { LEAD: lead, WORKER: [message("m1"), turnStarted] } });
    await notice(completed("WORKER"));
    const held = rows.get("row_1")!;
    rows.set("row_1", {
      ...held,
      updatedAt: held.updatedAt + 50,
      systemNotice: {
        kind: "child-completed",
        subject: { kind: "thread", threadId: "WORKER", threadName: "WORKER", outcomes: [{ threadId: "WORKER" }, { threadId: "RELAY" }] },
      } as never,
    });
    lead.unshift(command("w1", "bb thread wait WORKER && bb thread output WORKER", { exitCode: 0, output: "DONE: 42" }));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(deleted).toEqual([]);
    expect(rows.get("row_1")!.sendAt).toBeNull();
  });

  it.each([
    [4_000, false],
    [4_001, true],
  ])("a %i-character reply is shortened: %s", async (length, shortened) => {
    const reply = `Summary line\n${"x".repeat(length - "Summary line\n".length)}`;
    const { notice, deleted, sent } = start({ output: reply });
    await notice(completed("WORKER"));
    if (!shortened) {
      expect(deleted).toEqual([]);
      expect(sent).toEqual([]);
      return;
    }
    expect(deleted).toEqual(["row_1"]);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ threadId: "LEAD", senderThreadId: "WORKER", inbox: false });
    expect(sent[0]!.text).toContain('"Summary line"');
    expect(sent[0]!.text).toContain("4,001-character");
    expect(sent[0]!.text).toContain("bb thread output WORKER");
  });

  it("delivers bb's own notice when sending the shortened one fails", async () => {
    const { harness, notice, deleted, rows } = start({ output: `Summary line\n${"x".repeat(5_000)}` });
    harness.sdk.stub("threads.send", async () => {
      throw new Error("send offline");
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual([]);
    expect(rows.get("row_1")!.sendAt).toBeNull();
  });

  describe("a conditional update that fails", () => {
    const merged = (row: Row, children: string[]): Row => ({
      ...row,
      updatedAt: row.updatedAt + 1,
      systemNotice: {
        kind: "child-completed",
        subject: { kind: "thread", threadId: children[0], threadName: children[0], outcomes: children.map((threadId) => ({ threadId, status: "completed" })) },
      } as never,
    });
    const touch = (rows: Map<string, Row>) => {
      const row = rows.get("row_1")!;
      rows.set("row_1", { ...row, updatedAt: row.updatedAt + 1 });
    };

    it("logs the error and the row's current state", async () => {
      const { notice, harness } = start({ output: "[no-op]", events: { WORKER: [message("m1"), turnStarted] }, beforeUpdate: (rows, call) => call === 1 && touch(rows) });
      await notice(completed("WORKER"));
      const warning = harness.logEntries.find((entry) => entry.level === "warn")?.message ?? "";
      expect(warning).toContain("HTTP 409: Queued message changed since editing began");
      expect(warning).toContain("row_1");
      expect(warning).toContain("updatedAt 101");
      expect(warning).toContain("expected 100");
    });

    it("decides again on the row's current contents and drops a no-op that only touched the row", async () => {
      const { notice, deleted, updateCalls } = start({ output: "[no-op]", events: { WORKER: [message("m1"), turnStarted] }, beforeUpdate: (rows, call) => call === 1 && touch(rows) });
      await notice(completed("WORKER"));
      expect(updateCalls()).toBe(2);
      expect(deleted).toEqual(["row_1"]);
    });

    it("delivers a row that bb merged another child's result into", async () => {
      const { notice, deleted, rows, updateCalls } = start({
        output: "[no-op]",
        events: { WORKER: [message("m1"), turnStarted] },
        beforeUpdate: (rows, call) => call === 1 && rows.set("row_1", merged(rows.get("row_1")!, ["WORKER", "RELAY"])),
      });
      await notice(completed("WORKER"));
      expect(deleted).toEqual([]);
      expect(updateCalls()).toBe(1);
      expect(rows.get("row_1")!.sendAt).toBeNull();
    });

    it("decides again only once", async () => {
      const { notice, deleted, updateCalls } = start({ output: "[no-op]", events: { WORKER: [message("m1"), turnStarted] }, beforeUpdate: (rows) => touch(rows) });
      await notice(completed("WORKER"));
      expect(updateCalls()).toBe(2);
      expect(deleted).toEqual([]);
    });

    it("does nothing when the row is already gone", async () => {
      const { notice, deleted, updateCalls } = start({ output: "[no-op]", events: { WORKER: [message("m1"), turnStarted] }, beforeUpdate: (rows) => rows.delete("row_1") });
      await notice(completed("WORKER"));
      expect(updateCalls()).toBe(1);
      expect(deleted).toEqual([]);
    });
  });

  it("leaves the notice to bb when reading events fails", async () => {
    const { harness, notice, deleted } = start();
    harness.sdk.stub("threads.events.list", async () => {
      throw new Error("events offline");
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual([]);
  });
});

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

function command(id: string, cmd: string, done: { exitCode: number; output: string } | null) {
  const item = { type: "commandExecution", id, command: cmd, status: done ? "completed" : "inProgress" };
  return done
    ? { type: "item/completed", data: { item: { ...item, exitCode: done.exitCode, aggregatedOutput: done.output } } }
    : { type: "item/started", data: { item } };
}
const turnStarted = { type: "turn/started", data: {} };
const message = (id: string) => ({ type: "item/completed", data: { item: { type: "agentMessage", id } } });

let host: Host | null = null;

function start(options: { mailTags?: Record<string, Record<string, true>>; events?: Record<string, unknown[]>; output?: string } = {}) {
  const sent: Sent[] = [];
  const rows = new Map<string, Row>();
  const deleted: string[] = [];
  const holds: Array<{ id: string; sendAt: number }> = [];
  const mailTags = options.mailTags ?? {};
  const events = options.events ?? {};
  const pages: number[] = [];
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
          update: async ({ queuedMessageId, sendAt }) => {
            const row = rows.get(queuedMessageId)!;
            const next = { ...row, sendAt: sendAt ?? null, updatedAt: row.updatedAt + 1 };
            rows.set(queuedMessageId, next);
            holds.push({ id: queuedMessageId, sendAt: sendAt ?? 0 });
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
  return { harness, sent, rows, deleted, holds, mailTags, pages, notice };
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
    ["lets an inbox message join a running turn", { attempt: "join-turn", experimental_submission: inbox }, "proceed"],
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

  it("keeps holding an inbox message that a running turn ended before it was delivered", async () => {
    const { harness } = start();
    const hook = harness.registrations.hooks["message.dispatch"]!;
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

  it("delivers the completion of a turn that only asked about compaction with --no-resume", async () => {
    const { notice, deleted } = start({
      events: { WORKER: [command("c1", "node bb-compact.mjs run note.md --no-resume", { exitCode: 0, output: "" }), turnStarted] },
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual([]);
  });

  it("drops a completion whose reply the parent's wait already printed", async () => {
    const { notice, deleted } = start({
      events: {
        LEAD: [command("w1", "bb thread wait WORKER --timeout 600 && bb thread output WORKER", { exitCode: 0, output: "Thread WORKER reached status idle.\nDONE: 42\n" })],
      },
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual(["row_1"]);
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
    const { notice, deleted, holds } = start({ events: { LEAD: lead } });
    await notice(completed("WORKER"));
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
    expect(holds.at(-1)!.sendAt).toBeLessThanOrEqual(Date.now());
    expect(rows.has("row_1")).toBe(true);
  });

  it("delivers a held notice that bb merged another child into", async () => {
    vi.useFakeTimers();
    const lead: unknown[] = [command("w1", "bb thread wait WORKER && bb thread output WORKER", null)];
    const { notice, deleted, rows } = start({ events: { LEAD: lead } });
    await notice(completed("WORKER"));
    const held = rows.get("row_1")!;
    rows.set("row_1", { ...held, updatedAt: held.updatedAt + 50 });
    lead.unshift(command("w1", "bb thread wait WORKER && bb thread output WORKER", { exitCode: 0, output: "DONE: 42" }));
    await vi.advanceTimersByTimeAsync(1_000);
    expect(deleted).toEqual([]);
    expect(rows.get("row_1")!.sendAt).toBeLessThanOrEqual(Date.now());
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

  it("leaves the notice to bb when reading events fails", async () => {
    const { harness, notice, deleted } = start();
    harness.sdk.stub("threads.events.list", async () => {
      throw new Error("events offline");
    });
    await notice(completed("WORKER"));
    expect(deleted).toEqual([]);
  });
});

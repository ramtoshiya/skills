import { createFakePluginHost, makeThreadResponse } from "@get-bb/plugin-sdk/testing";
import { afterEach, describe, expect, it } from "vitest";
import plugin from "./server";

type Host = ReturnType<typeof createFakePluginHost>;
type Spawned = Record<string, unknown>;
type Sent = { threadId: string; senderThreadId?: string; mode: string; text: string };

const BRIEF = "Line one of the brief.\nLine two with `backticks` and $(not a command).";

const THREADS = {
  L1: { parentThreadId: null, canSpawnChild: true },
  L2: { parentThreadId: "L1", canSpawnChild: true },
  L3: { parentThreadId: "L2", canSpawnChild: true },
  L4: { parentThreadId: "L3", canSpawnChild: false },
  L5: { parentThreadId: "L3", canSpawnChild: false, originPluginId: "nest" },
  OTHER: { parentThreadId: "L3", canSpawnChild: false, originPluginId: "nest" },
  DONE: { parentThreadId: "L3", canSpawnChild: false, originPluginId: "nest", archived: true },
} as const;
const METADATA: Record<string, Record<string, unknown>> = {
  L5: { logicalParentThreadId: "L4" },
  OTHER: { logicalParentThreadId: "L2" },
  DONE: { logicalParentThreadId: "L4" },
};

const EVENTS: Record<string, unknown[]> = {};
const MAIL_METADATA: Array<{ threadId: string; pluginId?: string; set?: Record<string, unknown> }> = [];

let host: Host | null = null;

function thread(id: keyof typeof THREADS) {
  const shape = THREADS[id];
  return makeThreadResponse({
    id,
    title: `${id} title`,
    environmentId: `env_${id}`,
    status: "idle",
    parentThreadId: shape.parentThreadId,
    canSpawnChild: shape.canSpawnChild,
    originPluginId: "originPluginId" in shape ? shape.originPluginId : null,
    archivedAt: "archived" in shape ? 1 : null,
  });
}

function start() {
  const spawned: Spawned[] = [];
  const sent: Sent[] = [];
  const reads: Array<{ hostId?: string; path: string }> = [];
  const isThread = (id: string): id is keyof typeof THREADS => id in THREADS;
  host = createFakePluginHost({
    pluginId: "nest",
    sdk: {
      threads: {
        get: async ({ threadId }) => {
          if (!isThread(threadId)) throw new Error(`no thread ${threadId}`);
          return thread(threadId);
        },
        spawn: async (args) => {
          spawned.push({ ...args });
          return makeThreadResponse({ id: "thr_new" });
        },
        send: async (args) => {
          const first = args.input[0];
          sent.push({
            threadId: args.threadId,
            senderThreadId: args.senderThreadId,
            mode: args.mode,
            text: first && first.type === "text" ? first.text : "",
          });
          return { delivery: "sent" } as never;
        },
        getPluginMetadata: async ({ threadId }) => METADATA[threadId] ?? {},
        updatePluginMetadata: async (args) => {
          MAIL_METADATA.push({ threadId: args.threadId, pluginId: args.pluginId, set: args.set });
          return (args.set ?? {}) as never;
        },
        events: {
          list: async ({ threadId, limit }) => {
            if (Number(limit) > 100) throw new Error("HTTP 400: Thread event limit cannot exceed 100");
            return (EVENTS[threadId] ?? []) as never;
          },
        },
        experimental_listPluginMetadata: async ({ threadIds }) => ({
          threads: threadIds.flatMap((threadId) => (METADATA[threadId] ? [{ threadId, metadata: METADATA[threadId] }] : [])),
        }),
        list: async (args = {}) =>
          (Object.keys(THREADS) as Array<keyof typeof THREADS>)
            .map(thread)
            .filter((candidate) => args.archived !== false || candidate.archivedAt === null)
            .filter((candidate) =>
              args.threadIds
                ? args.threadIds.includes(candidate.id)
                : args.parentThreadId
                  ? candidate.parentThreadId === args.parentThreadId
                  : candidate.originPluginId === args.originPluginId,
            ) as never,
      },
      environments: {
        get: async ({ environmentId }) => ({ id: environmentId, hostId: `host_of_${environmentId}` }) as never,
      },
      files: {
        read: async (args) => {
          reads.push({ hostId: args.hostId, path: args.path });
          return { content: BRIEF, contentEncoding: "utf8" } as never;
        },
      },
    },
  });
  plugin(host.bb);
  return { harness: host.harness, spawned, sent, reads };
}

afterEach(async () => {
  for (const key of Object.keys(EVENTS)) delete EVENTS[key];
  MAIL_METADATA.length = 0;
  await host?.harness.lifecycle.dispose();
  host = null;
});

const spawnArgs = ["spawn", "--project", "proj_x", "--provider", "claude-code", "--model", "claude-haiku-5-5", "--prompt", BRIEF];

describe("bb nest spawn", () => {
  it("starts a normal child of a caller that bb lets take one", async () => {
    const { harness, spawned } = start();
    const result = await harness.runCli(spawnArgs, { threadId: "L3" });
    expect(result.exitCode).toBe(0);
    expect(spawned).toHaveLength(1);
    expect(spawned[0]).toMatchObject({
      origin: "cli",
      parentThreadId: "L3",
      senderThreadId: "L3",
      projectId: "proj_x",
      providerId: "claude-code",
      model: "claude-haiku-5-5",
      prompt: BRIEF,
    });
    expect(spawned[0]).not.toHaveProperty("parentNotifications");
    expect(spawned[0]).not.toHaveProperty("pluginMetadata");
  });

  it.each([
    ["L4", "a thread at bb's depth limit"],
    ["L5", "a worker that nest already placed past the limit"],
  ])("starts a relay worker under the nearest capable ancestor for %s, %s", async (caller) => {
    const { harness, spawned } = start();
    const result = await harness.runCli(spawnArgs, { threadId: caller });
    expect(result.exitCode).toBe(0);
    expect(spawned[0]).toMatchObject({
      parentThreadId: "L3",
      parentNotifications: "off",
      lifecycleOwnerThreadId: caller,
      senderThreadId: caller,
      pluginMetadata: { logicalParentThreadId: caller },
    });
    const prompt = String(spawned[0]?.prompt);
    expect(prompt.endsWith(BRIEF)).toBe(true);
    expect(prompt).toContain(`@thread:${caller}`);
    expect(prompt).toContain("never message @thread:L3");
  });

  it("saves --tag values as mail tags on the new thread", async () => {
    const { harness } = start();
    const result = await harness.runCli([...spawnArgs, "--tag", "role=reviewer", "--tag", "urgent"], { threadId: "L3" });
    expect(result.exitCode).toBe(0);
    expect(MAIL_METADATA).toEqual([{ threadId: "thr_new", pluginId: "mail", set: { "tag:role=reviewer": true, "tag:urgent": true } }]);
  });

  it("reads --prompt-file on the caller's machine, relative to the caller's directory", async () => {
    const { harness, spawned, reads } = start();
    const result = await harness.runCli(
      ["spawn", "--project", "proj_x", "--prompt-file", "briefs/worker.md"],
      { threadId: "L4", cwd: "/work/repo" },
    );
    expect(result.exitCode).toBe(0);
    expect(reads).toEqual([{ hostId: "host_of_env_L4", path: "/work/repo/briefs/worker.md" }]);
    expect(String(spawned[0]?.prompt).endsWith(BRIEF)).toBe(true);
  });

  it("creates the new environment on the caller's machine", async () => {
    const { harness, spawned } = start();
    await harness.runCli([...spawnArgs, "--new-environment", "worktree", "--base-branch", "main"], { threadId: "L4" });
    expect(spawned[0]?.environment).toEqual({
      type: "host",
      hostId: "host_of_env_L4",
      workspace: { type: "managed-worktree", baseBranch: { kind: "named", name: "main" } },
    });
  });

  it.each([
    [["spawn", "--project", "proj_x", "--prompt-file", "-"], "L4"],
    [spawnArgs, undefined],
    [[...spawnArgs, "--environment", "env_1", "--new-environment", "personal"], "L4"],
    [[...spawnArgs, "--tag", "project=x"], "L3"],
  ])("refuses %j from %s without creating a thread", async (argv, threadId) => {
    const { harness, spawned } = start();
    const result = await harness.runCli(argv, threadId ? { threadId } : {});
    expect(result.exitCode).not.toBe(0);
    expect(spawned).toEqual([]);
  });
});

describe("relay", () => {
  it("delivers a relay worker's final reply to its logical parent as the worker", async () => {
    const { harness, sent } = start();
    await harness.emitThreadEvent("thread.idle", { thread: thread("L5"), lastAssistantText: "FINAL: 392" });
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ threadId: "L4", senderThreadId: "L5", mode: "auto" });
    expect(sent[0]?.text).toContain("FINAL: 392");
    expect(sent[0]?.text).toContain("needs no reply");
  });

  it("leaves threads that nest did not start to bb's own notifications", async () => {
    const { harness, sent } = start();
    await harness.emitThreadEvent("thread.idle", { thread: thread("L4"), lastAssistantText: "done" });
    await harness.emitThreadEvent("thread.failed", { thread: thread("L4"), error: "boom" });
    expect(sent).toEqual([]);
  });

  it("delivers a failure with its error", async () => {
    const { harness, sent } = start();
    await harness.emitThreadEvent("thread.failed", { thread: thread("L5"), error: "Provider exited with code 1" });
    expect(sent[0]).toMatchObject({ threadId: "L4", senderThreadId: "L5" });
    expect(sent[0]?.text).toContain("failed: Provider exited with code 1");
  });

  it("delivers a pending question with its prompt and the interaction id", async () => {
    const { harness, sent } = start();
    const interaction = {
      id: "int_1",
      threadId: "L5",
      payload: { kind: "user_question", questions: [{ id: "q", prompt: "Which number should I use?", allowFreeText: true, multiSelect: false }] },
    };
    await harness.emitThreadEvent("interaction.pending", { thread: thread("L5"), interaction: interaction as never });
    expect(sent[0]?.threadId).toBe("L4");
    expect(sent[0]?.text).toContain("is waiting on an interaction (user question, int_1).");
    expect(sent[0]?.text).toContain("Which number should I use?");
    expect(sent[0]?.text).toContain("bb thread interactions show int_1 L5");
  });

  it("replaces a reply over 4,000 characters with its first line and where to read it", async () => {
    const { harness, sent } = start();
    await harness.emitThreadEvent("thread.idle", { thread: thread("L5"), lastAssistantText: `Verdict: ship\n${"x".repeat(10_000)}` });
    expect(sent[0]?.text).toContain('10,014-character reply starts "Verdict: ship"');
    expect(sent[0]?.text).toContain("bb thread output L5");
    expect(sent[0]?.text.length).toBeLessThan(500);
  });

  it("does not relay a turn that ended to self-compact, nor bb's compaction turn after it", async () => {
    const { harness, sent } = start();
    const launch = {
      type: "item/completed",
      data: { item: { type: "commandExecution", id: "c1", command: 'node "/p/bb-compact.mjs" run "/h/note.md" --launch-seq 9 --turn-id t1', exitCode: 0 } },
    };
    EVENTS.L5 = [launch, { type: "turn/started", data: {} }];
    await harness.emitThreadEvent("thread.idle", { thread: thread("L5"), lastAssistantText: "Compaction is scheduled." });
    EVENTS.L5 = [{ type: "thread/compacted", data: {} }, { type: "turn/started", data: {} }, ...EVENTS.L5];
    await harness.emitThreadEvent("thread.idle", { thread: thread("L5"), lastAssistantText: "Compaction is scheduled." });
    expect(sent).toEqual([]);
  });

  it("relays a turn whose self-compact launch failed", async () => {
    const { harness, sent } = start();
    const failed = { type: "item/completed", data: { item: { type: "commandExecution", id: "c1", command: "node bb-compact.mjs run missing.md", exitCode: 1 } } };
    EVENTS.L5 = [{ type: "item/completed", data: { item: { type: "agentMessage", id: "m1" } } }, failed, { type: "turn/started", data: {} }];
    await harness.emitThreadEvent("thread.idle", { thread: thread("L5"), lastAssistantText: "FINAL: 8" });
    expect(sent[0]?.text).toContain("FINAL: 8");
  });

  it("relays the result when the worker's events cannot be read", async () => {
    const { harness, sent } = start();
    harness.sdk.stub("threads.events.list", async () => {
      throw new Error("events offline");
    });
    await harness.emitThreadEvent("thread.idle", { thread: thread("L5"), lastAssistantText: "FINAL: 7" });
    expect(sent[0]?.text).toContain("FINAL: 7");
  });
});

describe("logical tree", () => {
  it("lists unarchived normal children and relay workers, and leaves out relay workers of other threads", async () => {
    const { harness } = start();
    const l3 = JSON.parse((await harness.runCli(["list", "--parent", "L3", "--json"])).stdout ?? "[]");
    const l4 = JSON.parse((await harness.runCli(["list", "--parent", "L4", "--json"])).stdout ?? "[]");
    const l2 = JSON.parse((await harness.runCli(["list", "--parent", "L2", "--json"])).stdout ?? "[]");
    expect(l3.map((row: { id: string; route: string }) => [row.id, row.route])).toEqual([["L4", "child"]]);
    expect(l4.map((row: { id: string; route: string }) => [row.id, row.route])).toEqual([["L5", "relay"]]);
    expect(l2.map((row: { id: string }) => row.id).sort()).toEqual(["L3", "OTHER"]);
  });

  it("serves each relay worker's logical parent title to the sidebar badge", async () => {
    const { harness } = start();
    const result = await harness.callRpc("logicalParents", { keys: ["L5", "L4"] });
    expect(result).toEqual({ L5: { id: "L4", title: "L4 title" }, L4: null });
  });
});

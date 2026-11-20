import { describe, expect, it } from "vitest";
import { makeMessageDispatchHookContext } from "@get-bb/plugin-sdk/testing";
import { decide } from "./decision";

const catalog = ["claude-haiku-4-5-20251001", "claude-haiku-5", "claude-haiku-5-5", "claude-haiku-10", "claude-opus-8", "gpt-5.6-luna", "gpt-6-luna", "gpt-6.2-luna", "gpt-7-luna[1m]"];
const context = (model: string | null) => makeMessageDispatchHookContext({
  thread: { status: "pending" }, attempt: "start-turn", senderThreadId: "thr_agent", initiator: "agent", requestedExecution: { model },
});

describe("model admission", () => {
  it.each([
    ["claude-haiku-4-5-20251001", "claude-haiku-10"],
    ["claude-haiku-5-5[1m]", "claude-haiku-10"],
    ["gpt-5.6-luna", "gpt-6.2-luna"],
  ])("rejects %s and names %s", (model, newest) => {
    const result = decide(context(model), catalog);
    expect(result.action).toBe("reject");
    if (result.action === "reject") {
      expect(result.message).toContain(model);
      expect(result.message).toContain(newest);
    }
  });
  it.each(["claude-haiku-10", "gpt-6.2-luna", "haiku", "claude-haiku-9-9", null])("allows %s", model => {
    expect(decide(context(model), catalog)).toEqual({ action: "proceed" });
  });
  it.each([
    { attempt: "join-turn" }, { thread: { status: "idle" } },
    { initiator: "system" }, { senderThreadId: "mixed" },
    { senderThreadId: null, parentThreadId: null, initiator: "user" },
    { senderThreadId: null, parentThreadId: "thr_parent", initiator: "user", origin: "app" },
  ] satisfies Parameters<typeof makeMessageDispatchHookContext>[0][])("allows non-agent or non-first dispatch %#", overrides => {
    expect(decide(makeMessageDispatchHookContext({ ...context("gpt-5.6-luna"), ...overrides }), catalog)).toEqual({ action: "proceed" });
  });
  it("checks a CLI child when bb supplies only its parent", () => {
    const ctx = makeMessageDispatchHookContext({ ...context("gpt-5.6-luna"), senderThreadId: null, parentThreadId: "thr_parent", origin: "cli", initiator: "user" });
    expect(decide(ctx, catalog).action).toBe("reject");
  });
});

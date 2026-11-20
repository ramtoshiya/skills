import { expect, it } from "vitest";
import { createFakePluginHost, makeMessageDispatchHookContext } from "@get-bb/plugin-sdk/testing";
import plugin from "./server";

it.each(["error", "timeout"])("lets a dispatch proceed on catalog %s", async (failure) => {
  const host = createFakePluginHost({ sdk: { providers: { models: async () => {
    if (failure === "error") throw new Error("catalog unavailable");
    return new Promise(() => {});
  } } } });
  try {
    plugin(host.bb);
    const hook = host.harness.inspection.registrations.hooks["message.dispatch"];
    if (!hook) throw new Error("hook was not registered");
    const result = await hook(makeMessageDispatchHookContext({
      thread: { status: "pending" }, senderThreadId: "thr_agent", initiator: "agent",
      requestedExecution: { model: "claude-haiku-4-5-20251001" },
    }));
    expect(result).toEqual({ action: "proceed" });
    expect(host.harness.inspection.logEntries).toContainEqual(expect.objectContaining({ level: "warn", message: expect.stringContaining("Could not check model catalog") }));
  } finally {
    await host.harness.lifecycle.dispose();
  }
}, 5000);

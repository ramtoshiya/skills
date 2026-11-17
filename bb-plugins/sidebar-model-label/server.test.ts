import {
  createFakePluginHost,
  makeThreadResponse,
} from "@get-bb/plugin-sdk/testing";
import { afterEach, describe, expect, it } from "vitest";
import plugin from "./server";

type Host = ReturnType<typeof createFakePluginHost>;
let host: Host | null = null;

function executionOptions(model: string) {
  return {
    model,
    permissionMode: "full" as const,
    reasoningLevel: "high",
    serviceTier: "default",
    source: "client/turn/requested" as const,
  };
}

function catalogModel(id: string, model: string, displayName: string) {
  return {
    id,
    model,
    displayName,
    description: "",
    defaultReasoningEffort: "high",
    isDefault: false,
    reasoningDiscovery: "known" as const,
    supportedReasoningEfforts: [],
  };
}

async function start(models: Record<string, string | null | Error>) {
  host = createFakePluginHost({
    pluginId: "sidebar-model-label",
    sdk: {
      threads: {
        defaultExecutionOptions: async ({ threadId }) => {
          const model = models[threadId];
          if (model instanceof Error) throw model;
          return model == null ? null : executionOptions(model);
        },
      },
      providers: {
        models: async ({ providerId } = {}) => {
          if (providerId !== "claude-code") throw new Error("unavailable");
          return {
            modelLoadError: null,
            models: [
              catalogModel("claude-opus-5-5", "claude-opus-5-5", "Opus 5.5"),
              catalogModel("opus", "claude-opus-4-8", "Opus 4.8"),
            ],
          };
        },
      },
    },
  });
  await plugin(host.bb);
  return host.harness;
}

async function threadEvent(harness: Host["harness"], threadId: string) {
  await harness.behavior.emitThreadEvent("experimental_thread.events", {
    thread: makeThreadResponse({ id: threadId }),
    sequence: 1,
  });
}

function resolveCalls(harness: Host["harness"]) {
  return harness.inspection.sdk.callsTo("threads.defaultExecutionOptions")
    .length;
}

afterEach(async () => {
  await host?.harness.lifecycle.dispose();
  host = null;
});

describe("threadModels", () => {
  it("returns each thread's model, or null when bb has none or fails", async () => {
    const harness = await start({
      thr_a: "claude-opus-5-5",
      thr_b: null,
      thr_c: new Error("thread not found"),
    });

    await expect(
      harness.behavior.callRpc("threadModels", {
        keys: ["thr_a", "thr_b", "thr_c"],
      }),
    ).resolves.toEqual({
      thr_a: "claude-opus-5-5",
      thr_b: null,
      thr_c: null,
    });
  });
});

describe("providerModels", () => {
  it("lists display names under both the catalog id and model, and nothing for a failing provider", async () => {
    const harness = await start({});

    await expect(
      harness.behavior.callRpc("providerModels", {
        keys: ["claude-code", "missing"],
      }),
    ).resolves.toEqual({
      "claude-code": [
        { model: "claude-opus-5-5", displayName: "Opus 5.5" },
        { model: "claude-opus-4-8", displayName: "Opus 4.8" },
        { model: "opus", displayName: "Opus 4.8" },
      ],
      missing: [],
    });
  });
});

describe("model change refresh", () => {
  it("invalidates a watched thread's row only when its model changes", async () => {
    const models: Record<string, string> = { thr_a: "claude-opus-5-5" };
    const harness = await start(models);
    harness.behavior.experimental_watchRpc("threadModels", { key: "thr_a" });
    await harness.behavior.callRpc("threadModels", { keys: ["thr_a"] });

    await threadEvent(harness, "thr_a");
    expect(harness.inspection.experimental_rpcInvalidations).toEqual([]);

    models.thr_a = "claude-sonnet-5-5";
    await threadEvent(harness, "thr_a");
    await expect
      .poll(() => harness.inspection.experimental_rpcInvalidations)
      .toEqual([["thread:thr_a"]]);
  });

  it("does not read threads that no row watches", async () => {
    const harness = await start({ thr_a: "claude-opus-5-5" });
    const stop = harness.behavior.experimental_watchRpc("threadModels", {
      key: "thr_a",
    });

    await threadEvent(harness, "thr_other");
    expect(resolveCalls(harness)).toBe(0);

    stop();
    await threadEvent(harness, "thr_a");
    expect(resolveCalls(harness)).toBe(0);
    expect(harness.inspection.experimental_rpcInvalidations).toEqual([]);
  });
});

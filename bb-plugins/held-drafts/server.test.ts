import { createFakePluginHost, makeThreadResponse } from "@get-bb/plugin-sdk/testing";
import { afterEach, describe, expect, it } from "vitest";
import plugin from "./server";

type Host = ReturnType<typeof createFakePluginHost>;

let host: Host | null = null;

function start() {
  const spawned: Array<Record<string, unknown>> = [];
  host = createFakePluginHost({
    pluginId: "held-drafts",
    sdk: {
      threads: {
        spawn: async (args) => {
          spawned.push({ ...args });
          return makeThreadResponse({ id: "thr_new" });
        },
      },
    },
  });
  plugin(host.bb);
  return { harness: host.harness, spawned };
}

afterEach(async () => {
  await host?.harness.lifecycle.dispose();
  host = null;
});

const createArgs = ["create", "--project", "proj_x", "--prompt", "brief"];

describe("bb draft create environment options", () => {
  it("requests a named base branch for a new worktree", async () => {
    const { harness, spawned } = start();
    const result = await harness.runCli(
      [...createArgs, "--new-environment", "worktree", "--machine", "host_1", "--base-branch", "main"],
      {},
    );
    expect(result.exitCode).toBe(0);
    expect(spawned[0]?.environment).toEqual({
      type: "host",
      hostId: "host_1",
      workspace: { type: "managed-worktree", baseBranch: { kind: "named", name: "main" } },
    });
  });

  it.each([
    [["--new-environment", "personal", "--base-branch", "main"], "--base-branch"],
    [["--new-environment", "personal", "--machine", "host_1"], "--machine"],
    [["--machine", "host_1"], "--machine"],
  ])("refuses %j without creating a thread", async (extra, option) => {
    const { harness, spawned } = start();
    const result = await harness.runCli([...createArgs, ...extra], {});
    expect(result.exitCode).not.toBe(0);
    expect(result.stderr).toContain(option);
    expect(spawned).toEqual([]);
  });
});

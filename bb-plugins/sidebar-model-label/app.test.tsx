// @vitest-environment jsdom
import type {
  ExperimentalThreadRowMetadataRegistration,
  PluginSidebarThread,
} from "@get-bb/plugin-sdk/app";
import { loadPluginApp, renderSlot } from "@get-bb/plugin-sdk/testing/app";
import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

function sidebarThread(id: string, providerId: string): PluginSidebarThread {
  return { id, providerId, displayTitle: id } as PluginSidebarThread;
}

const threads = [
  sidebarThread("thr_opus", "claude-code"),
  sidebarThread("thr_unknown", "claude-code"),
  sidebarThread("thr_codex", "codex"),
];

function SidebarRows({
  registration,
}: {
  registration: ExperimentalThreadRowMetadataRegistration<unknown>;
}) {
  const data = registration.useData?.({ threads });
  const Item = registration.component;
  return (
    <ul>
      {threads.map((thread) => (
        <li key={thread.id} data-testid={thread.id}>
          <Item thread={thread} data={data} />
        </li>
      ))}
    </ul>
  );
}

function keysOf(input: unknown): string[] {
  return (input as { keys: string[] }).keys;
}

afterEach(cleanup);

async function renderRows(models: Record<string, string | null>) {
  const app = await loadPluginApp(() => import("./app"));
  const [registration] = app.threadRowMetadata;
  if (!registration) throw new Error("no thread row metadata registered");
  return renderSlot(
    { component: SidebarRows },
    { registration },
    {
      rpc: {
        threadModels: (input) =>
          Object.fromEntries(
            keysOf(input).map((key) => [key, models[key] ?? null]),
          ),
        providerModels: (input) =>
          Object.fromEntries(
            keysOf(input).map((key) => [
              key,
              key === "claude-code"
                ? [
                    { model: "claude-opus-5-5", displayName: "Opus 5.5" },
                    { model: "claude-sonnet-5-5", displayName: "Sonnet 5.5" },
                  ]
                : [],
            ]),
          ),
      },
    },
  );
}

describe("sidebar model label", () => {
  it("labels each row with its model and leaves unknown rows empty", async () => {
    const slot = await renderRows({
      thr_opus: "claude-opus-5-5",
      thr_codex: "gpt-6.1-sol",
    });

    const opus = await slot.findByText("Opus 5.5");
    expect(opus.getAttribute("title")).toBe("Model: Opus 5.5 (claude-opus-5-5)");
    expect(slot.getByTestId("thr_opus").textContent).toBe("Opus 5.5");
    expect(slot.getByTestId("thr_codex").textContent).toBe("gpt-6.1-sol");
    expect(slot.getByTestId("thr_unknown").textContent).toBe("");
  });

  it("reads every row in one batch per method", async () => {
    const slot = await renderRows({ thr_opus: "claude-opus-5-5" });
    await slot.findByText("Opus 5.5");

    const calls = slot.inspection.rpcCalls.map((call) => call.method);
    expect(calls.filter((method) => method === "threadModels")).toHaveLength(1);
    expect(calls.filter((method) => method === "providerModels")).toHaveLength(1);
  });

  it("updates a row when the server invalidates its thread", async () => {
    const models: Record<string, string | null> = {
      thr_opus: "claude-opus-5-5",
    };
    const slot = await renderRows(models);
    await slot.findByText("Opus 5.5");

    models.thr_opus = "claude-sonnet-5-5";
    await slot.behavior.experimental_invalidateRpc(["thread:thr_opus"]);

    await slot.findByText("Sonnet 5.5");
  });
});

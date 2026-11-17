// @vitest-environment jsdom
import type { PluginSidebarThread } from "@get-bb/plugin-sdk/app";
import {
  loadPluginApp,
  mountPluginContentScripts,
  renderSlot,
} from "@get-bb/plugin-sdk/testing/app";
import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

function sidebarThread(id: string, providerId: string): PluginSidebarThread {
  return { id, providerId, displayTitle: id } as PluginSidebarThread;
}

const threads = [
  sidebarThread("thr_opus", "claude-code"),
  sidebarThread("thr_unknown", "claude-code"),
  sidebarThread("thr_codex", "codex"),
];

function renderRows() {
  const sidebar = document.createElement("div");
  sidebar.setAttribute("data-sidebar", "content");
  sidebar.innerHTML = threads
    .map(
      ({ id }) => `
      <div data-testid="${id}"><span>
        <a data-sidebar-thread-shortcut-target data-sidebar-thread-id="${id}"></a>
        <span style="display: flex"><span class="bb-thread-title"><span>${id}</span></span></span>
      </span></div>`,
    )
    .join("");
  document.body.append(sidebar);
}

function labelOf(threadId: string): string | null {
  const label = document.querySelector(
    `[data-testid="${threadId}"] [data-sidebar-model-label]`,
  );
  return label?.textContent ?? null;
}

function keysOf(input: unknown): string[] {
  return (input as { keys: string[] }).keys;
}

const mounted: { dispose(): Promise<void> }[] = [];

afterEach(async () => {
  cleanup();
  for (const scripts of mounted.splice(0)) await scripts.dispose();
  document.body.innerHTML = "";
});

async function start(models: Record<string, string | null>) {
  renderRows();
  const app = await loadPluginApp(() => import("./app"));
  const scripts = await mountPluginContentScripts(app, {
    pluginId: "sidebar-model-label",
  });
  mounted.push(scripts.lifecycle);
  const [overlay] = app.appOverlays;
  if (!overlay) throw new Error("no app overlay registered");
  const slot = renderSlot(
    overlay,
    {},
    {
      sidebarThreads: { status: "ready", threads },
      rpc: {
        threadModels: (input) =>
          Object.fromEntries(keysOf(input).map((key) => [key, models[key] ?? null])),
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
  return { slot, scripts };
}

describe("sidebar model label", () => {
  it("labels each rendered row with its model and leaves unknown rows bare", async () => {
    await start({ thr_opus: "claude-opus-5-5", thr_codex: "gpt-6.1-sol" });

    await vi.waitFor(() => expect(labelOf("thr_opus")).toBe("Opus 5.5"));
    await vi.waitFor(() => expect(labelOf("thr_codex")).toBe("gpt-6.1-sol"));
    expect(labelOf("thr_unknown")).toBeNull();
  });

  it("reads every rendered row in one batch per method", async () => {
    const { slot } = await start({ thr_opus: "claude-opus-5-5" });
    await vi.waitFor(() => expect(labelOf("thr_opus")).toBe("Opus 5.5"));

    const calls = slot.inspection.rpcCalls.map((call) => call.method);
    expect(calls.filter((method) => method === "threadModels")).toHaveLength(1);
    expect(calls.filter((method) => method === "providerModels")).toHaveLength(1);
  });

  it("updates a row when the server invalidates its thread", async () => {
    const models: Record<string, string | null> = { thr_opus: "claude-opus-5-5" };
    const { slot } = await start(models);
    await vi.waitFor(() => expect(labelOf("thr_opus")).toBe("Opus 5.5"));

    models.thr_opus = "claude-sonnet-5-5";
    await slot.behavior.experimental_invalidateRpc(["thread:thr_opus"]);

    await vi.waitFor(() => expect(labelOf("thr_opus")).toBe("Sonnet 5.5"));
  });

  it("removes its labels when bb disposes the content script", async () => {
    const { scripts } = await start({ thr_opus: "claude-opus-5-5" });
    await vi.waitFor(() => expect(labelOf("thr_opus")).toBe("Opus 5.5"));

    await scripts.lifecycle.dispose();

    expect(document.querySelectorAll("[data-sidebar-model-label]")).toHaveLength(0);
  });
});

// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { createLabelBridge } from "./label-bridge";
import {
  createLabelLayer,
  findRows,
  mountModelLabels,
  threadIdsOf,
} from "./sidebar-dom";

function label(threads: Record<string, string>): string[] {
  const rows = findRows(document);
  createLabelLayer().render(rows, new Map(Object.entries(threads)));
  return threadIdsOf(rows);
}

function bb049RowHtml(threadId: string, title: string): string {
  return `
    <div data-sidebar-rename-row role="button" data-testid="row-${threadId}">
      <span class="leading">
        <a data-sidebar-thread-shortcut-target data-sidebar-thread-id="${threadId}" aria-label="Open ${title}"></a>
        <span class="contents">
          <span class="title-line" style="display: flex">
            <span data-sidebar-thread-provider="claude-code" role="img"></span>
            <span class="bb-thread-title min-w-0 truncate" title="${title}"><span class="truncate">${title}</span></span>
          </span>
        </span>
      </span>
      <span data-sidebar-thread-trailing></span>
    </div>`;
}

function renderSidebar(...rows: [string, string][]): HTMLElement {
  document.body.innerHTML = `<div data-sidebar="content"><div id="rows">${rows
    .map(([id, title]) => bb049RowHtml(id, title))
    .join("")}</div></div>`;
  return document.getElementById("rows")!;
}

function titleLine(threadId: string): string[] {
  const line = document.querySelector(`[data-testid="row-${threadId}"] .title-line`)!;
  return [...line.children].map((child) =>
    child.hasAttribute("data-sidebar-model-label")
      ? `label:${child.textContent}`
      : (child.getAttribute("data-sidebar-thread-provider") ? "icon" : "title"),
  );
}

function labelCount(): number {
  return document.querySelectorAll("[data-sidebar-model-label]").length;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("label layer", () => {
  it("puts the label after the title on the title line and reports each row", () => {
    renderSidebar(["thr_a", "Fix login"], ["thr_b", "Write docs"]);

    const rowIds = label({ thr_a: "Opus 5.5" });

    expect(rowIds).toEqual(["thr_a", "thr_b"]);
    expect(titleLine("thr_a")).toEqual(["icon", "title", "label:Opus 5.5"]);
    expect(titleLine("thr_b")).toEqual(["icon", "title"]);
    const anchor = document.querySelector('[data-sidebar-thread-id="thr_a"]')!;
    expect(anchor.childNodes).toHaveLength(0);
  });

  it("updates text in place and removes labels a row no longer has", () => {
    renderSidebar(["thr_a", "Fix login"]);
    const layer = createLabelLayer();
    layer.render(findRows(document), new Map([["thr_a", "Opus 5.5"]]));
    const first = document.querySelector("[data-sidebar-model-label]");

    layer.render(findRows(document), new Map([["thr_a", "Sonnet 5.5"]]));
    expect(document.querySelector("[data-sidebar-model-label]")).toBe(first);
    expect(titleLine("thr_a")).toEqual(["icon", "title", "label:Sonnet 5.5"]);

    layer.render(findRows(document), new Map());
    expect(labelCount()).toBe(0);
  });

  it("leaves a row alone when its markup does not match", () => {
    renderSidebar(
      ["thr_a", "No title"],
      ["thr_b", "Two titles"],
      ["thr_c", "Not a flex line"],
      ["thr_d", "No shortcut marker"],
    );
    const row = (id: string) => document.querySelector(`[data-testid="row-${id}"]`)!;
    row("thr_a").querySelector(".bb-thread-title")!.className = "renamed";
    const second = document.createElement("span");
    second.className = "bb-thread-title";
    row("thr_b").querySelector(".title-line")!.append(second);
    row("thr_c").querySelector<HTMLElement>(".title-line")!.style.display = "block";
    row("thr_d").querySelector("a")!.removeAttribute("data-sidebar-thread-shortcut-target");
    const before = document.body.innerHTML;

    const rowIds = label({ thr_a: "Opus", thr_b: "Opus", thr_c: "Opus", thr_d: "Opus" });

    expect(rowIds).toEqual([]);
    expect(document.body.innerHTML).toBe(before);
  });
});

describe("mountModelLabels", () => {
  function mount() {
    const bridge = createLabelBridge();
    const controller = new AbortController();
    const dispose = mountModelLabels(document, bridge, controller.signal);
    return { bridge, controller, dispose };
  }

  it("labels rows the sidebar adds later and reports their ids", async () => {
    const rows = renderSidebar(["thr_a", "Fix login"]);
    const { bridge, controller } = mount();
    bridge.setLabels(new Map([["thr_a", "Opus 5.5"], ["thr_b", "GPT-6.1-Sol"]]));
    await vi.waitFor(() => expect(titleLine("thr_a")).toContain("label:Opus 5.5"));

    rows.insertAdjacentHTML("beforeend", bb049RowHtml("thr_b", "Write docs"));

    await vi.waitFor(() => expect(titleLine("thr_b")).toEqual(["icon", "title", "label:GPT-6.1-Sol"]));
    expect(bridge.getRowIds()).toEqual(["thr_a", "thr_b"]);
    controller.abort();
  });

  it("puts the label back after the title when the host inserts nodes after it", async () => {
    renderSidebar(["thr_a", "Fix login"]);
    const { bridge, controller } = mount();
    bridge.setLabels(new Map([["thr_a", "Opus 5.5"]]));
    await vi.waitFor(() => expect(titleLine("thr_a")).toContain("label:Opus 5.5"));

    const line = document.querySelector('[data-testid="row-thr_a"] .title-line')!;
    const title = line.querySelector(".bb-thread-title")!;
    line.append(title);

    await vi.waitFor(() => expect(titleLine("thr_a")).toEqual(["icon", "title", "label:Opus 5.5"]));
    controller.abort();
  });

  it("stops reconciling once its own writes settle", async () => {
    renderSidebar(["thr_a", "Fix login"], ["thr_b", "Write docs"]);
    const { bridge, controller } = mount();
    const reads = vi.spyOn(bridge, "getLabels");
    bridge.setLabels(new Map([["thr_a", "Opus 5.5"], ["thr_b", "Sonnet 5.5"]]));
    await vi.waitFor(() => expect(labelCount()).toBe(2));
    const settled = reads.mock.calls.length;

    await new Promise((resolve) => setTimeout(resolve, 200));

    expect(reads.mock.calls.length).toBe(settled);
    controller.abort();
  });

  it("removes its labels from rows the sidebar already detached", async () => {
    const rows = renderSidebar(["thr_a", "Fix login"]);
    const { bridge, dispose } = mount();
    bridge.setLabels(new Map([["thr_a", "Opus 5.5"]]));
    await vi.waitFor(() => expect(labelCount()).toBe(1));

    rows.remove();
    dispose();

    expect(rows.querySelectorAll("[data-sidebar-model-label]")).toHaveLength(0);
  });

  it("removes every label and stops watching when the host aborts", async () => {
    const rows = renderSidebar(["thr_a", "Fix login"]);
    const { bridge, controller } = mount();
    bridge.setLabels(new Map([["thr_a", "Opus 5.5"], ["thr_b", "Opus 5.5"]]));
    await vi.waitFor(() => expect(labelCount()).toBe(1));

    controller.abort();
    expect(labelCount()).toBe(0);
    expect(bridge.getRowIds()).toEqual([]);

    rows.insertAdjacentHTML("beforeend", bb049RowHtml("thr_b", "Write docs"));
    bridge.setLabels(new Map([["thr_a", "Sonnet 5.5"]]));
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(labelCount()).toBe(0);
  });
});

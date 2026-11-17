const DOCUMENTED_THREAD_ID_ATTRIBUTE = "data-sidebar-thread-id";
const DOCUMENTED_ROW_ANCHOR = `a[data-sidebar-thread-shortcut-target][${DOCUMENTED_THREAD_ID_ATTRIBUTE}]`;
const PRIVATE_TITLE = ".bb-thread-title";
const PRIVATE_SIDEBAR_PART = "[data-sidebar]";
export const LABEL_ATTRIBUTE = "data-sidebar-model-label";
const LABEL = `[${LABEL_ATTRIBUTE}]`;

const BB_PROVIDER_ICON_WITH_MARGIN = "1.5rem";
const LABEL_SHARE_OF_ROOM_AFTER_ICON = 0.4;
const LABEL_STYLE = [
  "flex: 0 0 auto",
  "box-sizing: border-box",
  `max-width: calc((100% - ${BB_PROVIDER_ICON_WITH_MARGIN}) * ${LABEL_SHARE_OF_ROOM_AFTER_ICON})`,
  "min-width: 0",
  "padding-left: 0.375rem",
  "pointer-events: none",
  "overflow: hidden",
  "text-overflow: ellipsis",
  "white-space: nowrap",
  "font-size: 0.75rem",
  "line-height: 1rem",
  "color: var(--muted-foreground)",
].join("; ");

export interface SidebarRow {
  threadId: string;
  title: HTMLElement;
}

export function findRows(root: ParentNode): SidebarRow[] {
  const rows: SidebarRow[] = [];
  for (const anchor of root.querySelectorAll<HTMLElement>(DOCUMENTED_ROW_ANCHOR)) {
    const threadId = anchor.getAttribute(DOCUMENTED_THREAD_ID_ATTRIBUTE);
    const title = findTitleOnFlexLine(anchor);
    if (threadId && title) rows.push({ threadId, title });
  }
  return rows;
}

export function threadIdsOf(rows: readonly SidebarRow[]): string[] {
  return [...new Set(rows.map((row) => row.threadId))].sort();
}

function findTitleOnFlexLine(anchor: HTMLElement): HTMLElement | null {
  const titles = anchor.parentElement?.querySelectorAll<HTMLElement>(PRIVATE_TITLE);
  if (titles?.length !== 1) return null;
  const title = titles[0]!;
  const line = title.parentElement;
  if (!line) return null;
  const display = line.ownerDocument.defaultView?.getComputedStyle(line).display;
  return display === "flex" || display === "inline-flex" ? title : null;
}

export interface LabelLayer {
  render(rows: readonly SidebarRow[], labels: ReadonlyMap<string, string>): void;
  removeAll(): void;
}

export function createLabelLayer(): LabelLayer {
  const owned = new Set<Element>();
  return {
    render(rows, labels) {
      const shown = new Set<Element>();
      for (const { threadId, title } of rows) {
        const text = labels.get(threadId);
        if (text === undefined) continue;
        const next = title.nextElementSibling;
        const label = next && owned.has(next) ? next : createLabel(title.ownerDocument);
        owned.add(label);
        if (label.textContent !== text) label.textContent = text;
        if (title.nextElementSibling !== label) title.after(label);
        shown.add(label);
      }
      for (const label of owned) {
        if (shown.has(label)) continue;
        label.remove();
        owned.delete(label);
      }
    },
    removeAll() {
      for (const label of owned) label.remove();
      owned.clear();
    },
  };
}

function createLabel(document: Document): HTMLSpanElement {
  const label = document.createElement("span");
  label.setAttribute(LABEL_ATTRIBUTE, "");
  label.style.cssText = LABEL_STYLE;
  return label;
}

export function affectsRows(record: MutationRecord): boolean {
  if (record.type === "attributes") return true;
  if (isOwnLabelChange(record)) return false;
  const target = record.target;
  if (isElement(target) && target.closest(PRIVATE_SIDEBAR_PART)) return true;
  return [...record.addedNodes].some(
    (node) =>
      isElement(node) &&
      (node.matches(DOCUMENTED_ROW_ANCHOR) || node.querySelector(DOCUMENTED_ROW_ANCHOR) !== null),
  );
}

function isOwnLabelChange(record: MutationRecord): boolean {
  const insideLabel = isElement(record.target) && record.target.closest(LABEL) !== null;
  const changed = [...record.addedNodes, ...record.removedNodes];
  const onlyLabelsMoved =
    changed.length > 0 && changed.every((node) => isElement(node) && node.matches(LABEL));
  return insideLabel || onlyLabelsMoved;
}

function isElement(node: Node): node is Element {
  return node.nodeType === 1;
}

export interface LabelSource {
  getLabels(): ReadonlyMap<string, string>;
  subscribeLabels(listener: () => void): () => void;
  setRowIds(threadIds: readonly string[]): void;
}

export function mountModelLabels(
  document: Document,
  source: LabelSource,
  signal: AbortSignal,
): () => void {
  const view = document.defaultView;
  if (!view || signal.aborted) return () => {};
  const layer = createLabelLayer();
  let frame: number | null = null;
  let disposed = false;

  const reconcileOncePerFrame = () => {
    frame = null;
    if (disposed) return;
    const rows = findRows(document);
    layer.render(rows, source.getLabels());
    source.setRowIds(threadIdsOf(rows));
  };
  const schedule = () => {
    if (frame === null && !disposed) frame = view.requestAnimationFrame(reconcileOncePerFrame);
  };

  const sidebarMayRemountAnywhere = document.body;
  const observer = new view.MutationObserver((records) => {
    if (records.some(affectsRows)) schedule();
  });
  observer.observe(sidebarMayRemountAnywhere, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: [DOCUMENTED_THREAD_ID_ATTRIBUTE],
  });
  const unsubscribe = source.subscribeLabels(schedule);
  schedule();

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    observer.disconnect();
    unsubscribe();
    signal.removeEventListener("abort", dispose);
    if (frame !== null) view.cancelAnimationFrame(frame);
    layer.removeAll();
    source.setRowIds([]);
  };
  signal.addEventListener("abort", dispose, { once: true });
  return dispose;
}

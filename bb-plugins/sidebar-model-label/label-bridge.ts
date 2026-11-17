import type { LabelSource } from "./sidebar-dom";

export interface LabelBridge extends LabelSource {
  setLabels(labels: ReadonlyMap<string, string>): void;
  getRowIds(): readonly string[];
  subscribeRowIds(listener: () => void): () => void;
}

export function createLabelBridge(): LabelBridge {
  let labels: ReadonlyMap<string, string> = new Map();
  let rowIds: readonly string[] = [];
  const labelListeners = new Set<() => void>();
  const rowIdListeners = new Set<() => void>();

  return {
    getLabels: () => labels,
    setLabels(next) {
      if (sameLabels(labels, next)) return;
      labels = next;
      for (const listener of [...labelListeners]) listener();
    },
    subscribeLabels(listener) {
      labelListeners.add(listener);
      return () => labelListeners.delete(listener);
    },
    getRowIds: () => rowIds,
    setRowIds(next) {
      if (next.length === rowIds.length && next.every((id, index) => id === rowIds[index])) {
        return;
      }
      rowIds = [...next];
      for (const listener of [...rowIdListeners]) listener();
    },
    subscribeRowIds(listener) {
      rowIdListeners.add(listener);
      return () => rowIdListeners.delete(listener);
    },
  };
}

function sameLabels(
  a: ReadonlyMap<string, string>,
  b: ReadonlyMap<string, string>,
): boolean {
  if (a.size !== b.size) return false;
  for (const [key, value] of a) if (b.get(key) !== value) return false;
  return true;
}

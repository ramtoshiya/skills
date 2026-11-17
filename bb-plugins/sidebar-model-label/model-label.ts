import type { CatalogModel } from "./contract";

export interface ModelLabel {
  text: string;
  title: string;
}

const DEFAULT_LABEL: ModelLabel = {
  text: "Default",
  title: "Model: provider default",
};

export function describeModel(
  model: string | null,
  catalog: readonly CatalogModel[],
): ModelLabel | null {
  if (model === null) return null;
  const id = model.trim();
  if (id === "" || id.toLowerCase() === "default") return DEFAULT_LABEL;

  const displayName =
    catalog.find((entry) => entry.model === id)?.displayName.trim() ?? "";
  const text = isNamed(displayName) ? lastSegment(displayName) : id;
  const title =
    displayName === "" || displayName === id
      ? `Model: ${id}`
      : `Model: ${displayName} (${id})`;
  return { text, title };
}

function isNamed(displayName: string): boolean {
  return displayName !== "" && !/^default\b/i.test(displayName);
}

function lastSegment(displayName: string): string {
  return displayName.split(" · ").at(-1)?.trim() || displayName;
}

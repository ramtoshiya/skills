import type { CatalogModel } from "./contract";

export function describeModel(
  model: string | null,
  catalog: readonly CatalogModel[],
): string | null {
  if (model === null) return null;
  const id = model.trim();
  if (id === "" || id.toLowerCase() === "default") return "Default";

  const displayName =
    catalog.find((entry) => entry.model === id)?.displayName.trim() ?? "";
  return isNamed(displayName) ? lastSegment(displayName) : id;
}

function isNamed(displayName: string): boolean {
  return displayName !== "" && !/^default\b/i.test(displayName);
}

function lastSegment(displayName: string): string {
  return displayName.split(" · ").at(-1)?.trim() || displayName;
}

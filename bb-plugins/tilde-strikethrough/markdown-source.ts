export const PRIVATE_MARKDOWN_ROOT = "[data-markdown-preview]";
const PRIVATE_REACT_FIBER_KEY = "__reactFiber$";
const PRIVATE_REACT_PROPS_KEY = "__reactProps$";
const PRIVATE_SOURCE_PROP = "content";

type Fiber = Record<string, unknown>;

export function markdownSourceOf(root: Element): string | null {
  for (
    let component = asRecord(lastRenderedFiberOf(root)?.return);
    component && typeof component.type !== "string";
    component = asRecord(component.return)
  ) {
    const source = asRecord(component.memoizedProps)?.[PRIVATE_SOURCE_PROP];
    if (typeof source === "string") return source;
  }
  return null;
}

function lastRenderedFiberOf(element: Element): Fiber | null {
  const reactFields = element as unknown as Record<string, unknown>;
  const fieldStartingWith = (prefix: string) =>
    reactFields[Object.keys(reactFields).find((key) => key.startsWith(prefix)) ?? ""];
  const fiber = asRecord(fieldStartingWith(PRIVATE_REACT_FIBER_KEY));
  const alternate = asRecord(fiber?.alternate);
  const lastRenderedProps = fieldStartingWith(PRIVATE_REACT_PROPS_KEY);
  return alternate?.memoizedProps === lastRenderedProps &&
    fiber?.memoizedProps !== lastRenderedProps
    ? alternate
    : fiber;
}

function asRecord(value: unknown): Fiber | null {
  return typeof value === "object" && value !== null ? (value as Fiber) : null;
}

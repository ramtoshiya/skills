import { parseDeletedSpans, singleTildeFlags, type DeletedSpan } from "./deleted-spans";
import { PRIVATE_MARKDOWN_ROOT, markdownSourceOf } from "./markdown-source";

export const SINGLE_TILDE_ATTRIBUTE = "data-tilde-strikethrough-single";
const MARKED = `del[${SINGLE_TILDE_ATTRIBUTE}]`;
const STYLE = `
${MARKED} { text-decoration: none; }
${MARKED}::before, ${MARKED}::after { content: "~"; }
`;

export function mountTildeStrikethrough(document: Document, signal: AbortSignal): void {
  const view = document.defaultView;
  if (!view || signal.aborted) return;

  const style = document.createElement("style");
  style.textContent = STYLE;
  document.head.append(style);

  const parsedRoots = new WeakMap<Element, { source: string; spans: DeletedSpan[] }>();
  let scheduledFrame: number | null = null;

  function deletedSpansOf(root: Element): DeletedSpan[] {
    const source = markdownSourceOf(root);
    if (source === null) return [];
    const parsed = parsedRoots.get(root);
    if (parsed?.source === source) return parsed.spans;
    const spans = parseDeletedSpans(source);
    parsedRoots.set(root, { source, spans });
    return spans;
  }

  function markSingleTildes() {
    scheduledFrame = null;
    const renderedByRoot = new Map<Element, HTMLElement[]>();
    for (const rendered of document.querySelectorAll<HTMLElement>(`${PRIVATE_MARKDOWN_ROOT} del`)) {
      const root = rendered.closest(PRIVATE_MARKDOWN_ROOT);
      if (!root) continue;
      const siblings = renderedByRoot.get(root);
      if (siblings) siblings.push(rendered);
      else renderedByRoot.set(root, [rendered]);
    }
    for (const [root, rendered] of renderedByRoot) {
      const single = singleTildeFlags(
        deletedSpansOf(root),
        rendered.map((element) => element.textContent ?? ""),
      );
      rendered.forEach((element, index) => {
        element.toggleAttribute(SINGLE_TILDE_ATTRIBUTE, single[index]);
      });
    }
  }

  const observer = new view.MutationObserver(() => {
    scheduledFrame ??= view.requestAnimationFrame(markSingleTildes);
  });
  observer.observe(document.body, { childList: true, characterData: true, subtree: true });
  markSingleTildes();

  signal.addEventListener(
    "abort",
    () => {
      observer.disconnect();
      if (scheduledFrame !== null) view.cancelAnimationFrame(scheduledFrame);
      style.remove();
      for (const element of document.querySelectorAll(MARKED)) {
        element.removeAttribute(SINGLE_TILDE_ATTRIBUTE);
      }
    },
    { once: true },
  );
}

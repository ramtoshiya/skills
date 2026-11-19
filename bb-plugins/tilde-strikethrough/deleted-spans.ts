import type { Nodes } from "mdast";
import { fromMarkdown } from "mdast-util-from-markdown";
import { gfmFromMarkdown } from "mdast-util-gfm";
import { toString } from "mdast-util-to-string";
import { gfm } from "micromark-extension-gfm";

export interface DeletedSpan {
  text: string;
  tildes: 1 | 2;
}

export function parseDeletedSpans(source: string): DeletedSpan[] {
  const spans: DeletedSpan[] = [];
  collect(
    fromMarkdown(source, { extensions: [gfm()], mdastExtensions: [gfmFromMarkdown()] }),
    source,
    spans,
  );
  return spans;
}

function collect(node: Nodes, source: string, spans: DeletedSpan[]) {
  if (node.type === "delete" && node.position?.start.offset !== undefined) {
    const secondCharacter = source[node.position.start.offset + 1];
    spans.push({ text: toString(node), tildes: secondCharacter === "~" ? 2 : 1 });
  }
  if ("children" in node) {
    for (const child of node.children) collect(child, source, spans);
  }
}

export function singleTildeFlags(spans: DeletedSpan[], renderedTexts: string[]): boolean[] {
  let firstUnused = 0;
  return renderedTexts.map((rendered) => {
    const match = spans.findIndex(
      (span, index) => index >= firstUnused && sameWords(span.text, rendered),
    );
    if (match === -1) return false;
    firstUnused = match + 1;
    return spans[match]?.tildes === 1;
  });
}

function sameWords(a: string, b: string): boolean {
  return collapseSpace(a) === collapseSpace(b);
}

function collapseSpace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

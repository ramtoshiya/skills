import { describe, expect, it } from "vitest";
import { parseDeletedSpans, singleTildeFlags } from "./deleted-spans";

describe("parseDeletedSpans", () => {
  it("reports a range written with single tildes as one single-tilde span", () => {
    expect(parseDeletedSpans("Range: v3~6 and then 8~10 stay plain.")).toEqual([
      { text: "6 and then 8", tildes: 1 },
    ]);
  });

  it("reports text between double tildes as a double-tilde span", () => {
    expect(parseDeletedSpans("Struck: ~~removed text~~ stays struck.")).toEqual([
      { text: "removed text", tildes: 2 },
    ]);
  });

  it("keeps the order of mixed spans across blocks", () => {
    const source = ["a~b~c and ~~d~~", "", "> quoted e~f~g", "", "- item ~~h~~"].join("\n");

    expect(parseDeletedSpans(source)).toEqual([
      { text: "b", tildes: 1 },
      { text: "d", tildes: 2 },
      { text: "f", tildes: 1 },
      { text: "h", tildes: 2 },
    ]);
  });

  it("reports the text of a span without its inner markup", () => {
    expect(parseDeletedSpans("from ~**bold** and `code`~ on")).toEqual([
      { text: "bold and code", tildes: 1 },
    ]);
  });

  it("reports nothing for tildes that Markdown does not strike through", () => {
    expect(parseDeletedSpans("`p~q~r` and x~**y**~z and one ~ alone")).toEqual([]);
  });
});

describe("singleTildeFlags", () => {
  const spans = parseDeletedSpans("v3~6 to 8~10, ~~gone~~, a~b~c");

  it("flags each rendered deletion that came from single tildes", () => {
    expect(singleTildeFlags(spans, ["6 to 8", "gone", "b"])).toEqual([true, false, true]);
  });

  it("leaves a rendered deletion that the source does not explain unflagged", () => {
    expect(singleTildeFlags(spans, ["from raw html", "6 to 8", "gone"])).toEqual([
      false,
      true,
      false,
    ]);
  });

  it("skips a source span that was not rendered", () => {
    expect(singleTildeFlags(spans, ["gone", "b"])).toEqual([false, true]);
  });

  it("pairs repeated text in order", () => {
    const repeated = parseDeletedSpans("~same~ then ~~same~~");

    expect(singleTildeFlags(repeated, ["same", "same"])).toEqual([true, false]);
  });

  it("ignores differences in white space", () => {
    const wrapped = parseDeletedSpans("v3~6 and\nthen 8~10");

    expect(singleTildeFlags(wrapped, ["6 and then 8"])).toEqual([true]);
  });
});

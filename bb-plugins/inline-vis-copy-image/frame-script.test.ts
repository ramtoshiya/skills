// @vitest-environment jsdom
import { afterAll, afterEach, describe, expect, it } from "vitest";
import { parseFrameMessage } from "./frame-message";
import { FRAME_SCRIPT, withFrameScript, withoutFrameScript } from "./frame-script";

const FRAME_SIZE = { width: 400, height: 300 };

const listening = new AbortController();
const posted: unknown[] = [];
window.addEventListener("message", (event) => posted.push(event.data), {
  signal: listening.signal,
});

afterEach(() => {
  posted.length = 0;
  document.body.innerHTML = "";
});

afterAll(() => listening.abort());

const messagesDelivered = () => new Promise((resolve) => setTimeout(resolve, 20));

function loadFrame(body: string) {
  const element = document.createElement("iframe");
  document.body.append(element);
  const frame = element.contentWindow as Window & typeof globalThis;
  frame.document.body.innerHTML = body;
  frame.eval(FRAME_SCRIPT);
  const fire = (selector: string, type: string, at = { clientX: 0, clientY: 0 }) =>
    frame.document
      .querySelector(selector)!
      .dispatchEvent(new frame.MouseEvent(type, { bubbles: true, ...at }));
  const received = async () => {
    await messagesDelivered();
    return posted.map((message) => parseFrameMessage(message, FRAME_SIZE));
  };
  return { fire, received };
}

describe("frame script", () => {
  it("reports the image and the point of a right-click on an image", async () => {
    const frame = loadFrame(`<img src="http://bb.test/files/chart.png">`);

    frame.fire("img", "contextmenu", { clientX: 120, clientY: 45 });

    expect(await frame.received()).toEqual([
      { kind: "image-context-menu", src: "http://bb.test/files/chart.png", x: 120, y: 45 },
    ]);
  });

  it("stays silent for a right-click outside an image", async () => {
    const frame = loadFrame(`<p>text</p><img src="chart.png">`);

    frame.fire("p", "contextmenu");

    expect(await frame.received()).toEqual([]);
  });

  it("reports every pointer press", async () => {
    const frame = loadFrame(`<p>text</p>`);

    frame.fire("p", "pointerdown");

    expect(await frame.received()).toEqual([{ kind: "pointer-down" }]);
  });
});

describe("frame message", () => {
  const request = { inlineVisCopyImage: "image-context-menu", src: "https://example.test/a.png", x: 1, y: 2 };

  it("accepts web and inline image addresses", () => {
    expect(parseFrameMessage(request, FRAME_SIZE)?.kind).toBe("image-context-menu");
    expect(
      parseFrameMessage({ ...request, src: "data:image/png;base64,AAAA" }, FRAME_SIZE)?.kind,
    ).toBe("image-context-menu");
  });

  it.each([
    ["a script address", { ...request, src: "javascript:alert(1)" }],
    ["a blob address the app page cannot load", { ...request, src: "blob:null/1234" }],
    ["a point outside the frame", { ...request, x: FRAME_SIZE.width + 1 }],
    ["a point that is not a number", { ...request, y: "2" }],
    ["another sender's message", { jsonrpc: "2.0", method: "inline-vis/height" }],
  ])("rejects %s", (_name, message) => {
    expect(parseFrameMessage(message, FRAME_SIZE)).toBeNull();
  });
});

describe("frame document", () => {
  const page = "<!doctype html><p>chart</p>";

  it("adds the script once and removes it again", () => {
    const withScript = withFrameScript(page);

    expect(withScript).not.toBe(page);
    expect(withScript.startsWith(page)).toBe(true);
    expect(withFrameScript(withScript)).toBe(withScript);
    expect(withoutFrameScript(withScript)).toBe(page);
    expect(withoutFrameScript(page)).toBe(page);
  });
});

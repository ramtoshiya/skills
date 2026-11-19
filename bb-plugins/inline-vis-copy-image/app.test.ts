// @vitest-environment jsdom
import { loadPluginApp, mountPluginContentScripts } from "@get-bb/plugin-sdk/testing/app";
import { afterEach, describe, expect, it, vi } from "vitest";
import { withFrameScript } from "./frame-script";

const OVERLAY = "[data-inline-vis-copy-image-overlay]";
const PAGE = "<!doctype html><img src='chart.png'>";
const FRAME_BOX = { left: 100, top: 150, width: 400, height: 300 };
const mounted: { dispose(): Promise<void> }[] = [];

afterEach(async () => {
  for (const scripts of mounted.splice(0)) await scripts.dispose();
  document.body.innerHTML = "";
});

function addInlineVisFrame(page = PAGE): HTMLIFrameElement {
  const holder = document.createElement("div");
  holder.setAttribute("data-inline-vis-frame", "");
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-scripts allow-forms");
  frame.srcdoc = page;
  frame.getBoundingClientRect = () => ({ ...FRAME_BOX, x: 100, y: 150 }) as DOMRect;
  Object.defineProperties(frame, {
    clientWidth: { value: FRAME_BOX.width },
    clientHeight: { value: FRAME_BOX.height },
  });
  holder.append(frame);
  document.body.append(holder);
  return frame;
}

async function start() {
  const app = await loadPluginApp(() => import("./app"));
  const scripts = await mountPluginContentScripts(app, { pluginId: "inline-vis-copy-image" });
  mounted.push(scripts.lifecycle);
  return scripts;
}

function receive(source: Window | null, data: unknown) {
  window.dispatchEvent(new MessageEvent("message", { source, data }));
}

function rightClickImage(frame: HTMLIFrameElement, x = 60, y = 40) {
  receive(frame.contentWindow, {
    inlineVisCopyImage: "image-context-menu",
    src: "http://bb.test/files/chart.png",
    x,
    y,
  });
}

const overlays = () => [...document.querySelectorAll<HTMLImageElement>(OVERLAY)];

describe("inline vis copy image", () => {
  it("adds its script to a frame that is already on the page", async () => {
    const frame = addInlineVisFrame();

    await start();

    expect(frame.srcdoc).toBe(withFrameScript(PAGE));
  });

  it("adds its script to a frame bb renders later and again when bb rewrites the page", async () => {
    await start();

    const frame = addInlineVisFrame();
    await vi.waitFor(() => expect(frame.srcdoc).toBe(withFrameScript(PAGE)));

    frame.srcdoc = "<p>next</p>";
    await vi.waitFor(() => expect(frame.srcdoc).toBe(withFrameScript("<p>next</p>")));
  });

  it("leaves other frames alone", async () => {
    const other = document.createElement("iframe");
    other.srcdoc = PAGE;
    document.body.append(other);

    await start();

    expect(other.srcdoc).toBe(PAGE);
  });

  it("covers the right-clicked point with the same image in the app page", async () => {
    const frame = addInlineVisFrame();
    await start();

    rightClickImage(frame, 60, 40);

    const [overlay, ...rest] = overlays();
    expect(rest).toEqual([]);
    expect(overlay!.src).toBe("http://bb.test/files/chart.png");
    expect(overlay!.style.position).toBe("fixed");
    expect(overlay!.style.opacity).toBe("0");
    const left = parseFloat(overlay!.style.left);
    const top = parseFloat(overlay!.style.top);
    const size = parseFloat(overlay!.style.width);
    expect(left).toBeLessThan(160);
    expect(left + size).toBeGreaterThan(160);
    expect(top).toBeLessThan(190);
    expect(top + size).toBeGreaterThan(190);
  });

  it("keeps one overlay when another image is right-clicked", async () => {
    const frame = addInlineVisFrame();
    await start();

    rightClickImage(frame, 60, 40);
    rightClickImage(frame, 200, 100);

    expect(overlays()).toHaveLength(1);
    expect(parseFloat(overlays()[0]!.style.left)).toBeGreaterThan(260);
  });

  it("ignores a request from a window that is not an inline vis frame", async () => {
    addInlineVisFrame();
    const other = document.createElement("iframe");
    document.body.append(other);
    await start();

    rightClickImage(other);

    expect(overlays()).toEqual([]);
  });

  it("removes the overlay on the next press in the app page or in a frame", async () => {
    const frame = addInlineVisFrame();
    await start();

    rightClickImage(frame);
    document.body.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    expect(overlays()).toEqual([]);

    rightClickImage(frame);
    receive(frame.contentWindow, { inlineVisCopyImage: "pointer-down" });
    expect(overlays()).toEqual([]);
  });

  it("keeps the overlay for a second right-click on it and removes it on a click", async () => {
    const frame = addInlineVisFrame();
    await start();
    rightClickImage(frame);
    const [overlay] = overlays();

    overlay!.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 2 }));
    expect(overlays()).toHaveLength(1);

    overlay!.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    overlay!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(overlays()).toEqual([]);
  });

  it("restores the page and removes the overlay when bb disposes the plugin", async () => {
    const frame = addInlineVisFrame();
    const scripts = await start();
    rightClickImage(frame);

    await scripts.lifecycle.dispose();

    expect(overlays()).toEqual([]);
    expect(frame.srcdoc).toBe(PAGE);
  });
});

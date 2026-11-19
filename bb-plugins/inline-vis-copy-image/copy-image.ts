import { parseFrameMessage } from "./frame-message";
import { hasFrameScript, withFrameScript } from "./frame-script";

const PRIVATE_INLINE_VIS_FRAME = "[data-inline-vis-frame] iframe[srcdoc]";
export const OVERLAY_ATTRIBUTE = "data-inline-vis-copy-image-overlay";
const OVERLAY_SIZE_PX = 16;
const OVERLAY_STYLE = [
  "position: fixed",
  `width: ${OVERLAY_SIZE_PX}px`,
  `height: ${OVERLAY_SIZE_PX}px`,
  "opacity: 0",
  "z-index: 2147483647",
].join("; ");

export function mountCopyImage(document: Document, signal: AbortSignal): void {
  const view = document.defaultView;
  if (!view) return;
  let overlay: HTMLImageElement | null = null;

  const inlineVisFrames = () =>
    document.querySelectorAll<HTMLIFrameElement>(PRIVATE_INLINE_VIS_FRAME);

  // Chromium leaves a frame blank if its srcdoc changes before the first load.
  const awaitingBbPageLoad = new WeakSet<HTMLIFrameElement>();

  function deferScriptUntilBbPageLoads() {
    for (const frame of inlineVisFrames()) {
      if (!hasFrameScript(frame.srcdoc)) awaitingBbPageLoad.add(frame);
    }
  }

  function removeOverlay() {
    overlay?.remove();
    overlay = null;
  }

  function coverPoint(frame: HTMLIFrameElement, src: string, x: number, y: number) {
    removeOverlay();
    const box = frame.getBoundingClientRect();
    const image = document.createElement("img");
    image.setAttribute(OVERLAY_ATTRIBUTE, "");
    image.alt = "";
    image.draggable = false;
    image.referrerPolicy = "no-referrer";
    image.style.cssText = OVERLAY_STYLE;
    image.style.left = `${box.left + frame.clientLeft + x - OVERLAY_SIZE_PX / 2}px`;
    image.style.top = `${box.top + frame.clientTop + y - OVERLAY_SIZE_PX / 2}px`;
    image.addEventListener("click", removeOverlay);
    image.src = src;
    document.body.append(image);
    overlay = image;
  }

  view.addEventListener(
    "message",
    (event) => {
      const frame = [...inlineVisFrames()].find(
        (candidate) => candidate.contentWindow === event.source,
      );
      if (!frame) return;
      const message = parseFrameMessage(event.data, {
        width: frame.clientWidth,
        height: frame.clientHeight,
      });
      if (message?.kind === "pointer-down") removeOverlay();
      if (message?.kind === "image-context-menu") {
        coverPoint(frame, message.src, message.x, message.y);
      }
    },
    { signal },
  );

  document.addEventListener(
    "pointerdown",
    (event) => {
      if (event.target !== overlay) removeOverlay();
    },
    { capture: true, signal },
  );

  document.addEventListener(
    "load",
    (event) => {
      const frame = event.target;
      if (!(frame instanceof view.HTMLIFrameElement) || !awaitingBbPageLoad.delete(frame)) return;
      frame.srcdoc = withFrameScript(frame.srcdoc);
    },
    { capture: true, signal },
  );

  const observer = new view.MutationObserver(deferScriptUntilBbPageLoads);
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["srcdoc"],
  });
  deferScriptUntilBbPageLoads();

  signal.addEventListener(
    "abort",
    () => {
      observer.disconnect();
      removeOverlay();
    },
    { once: true },
  );
}

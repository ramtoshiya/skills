import { MESSAGE_KEY } from "./frame-message";

export const FRAME_SCRIPT = `(function () {
  document.addEventListener("contextmenu", function (event) {
    var image = event.target;
    if (!(image instanceof HTMLImageElement)) return;
    parent.postMessage({ ${MESSAGE_KEY}: "image-context-menu", src: image.currentSrc || image.src, x: event.clientX, y: event.clientY }, "*");
  }, true);
  document.addEventListener("pointerdown", function () {
    parent.postMessage({ ${MESSAGE_KEY}: "pointer-down" }, "*");
  }, true);
})();`;

const SCRIPT_TAG = `<script data-inline-vis-copy-image>${FRAME_SCRIPT}</script>`;

export function withFrameScript(srcdoc: string): string {
  return srcdoc.endsWith(SCRIPT_TAG) ? srcdoc : srcdoc + SCRIPT_TAG;
}

export function withoutFrameScript(srcdoc: string): string {
  return srcdoc.endsWith(SCRIPT_TAG) ? srcdoc.slice(0, -SCRIPT_TAG.length) : srcdoc;
}

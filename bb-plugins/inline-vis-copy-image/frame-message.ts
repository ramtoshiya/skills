export const MESSAGE_KEY = "inlineVisCopyImage";

export type FrameMessage =
  | { kind: "image-context-menu"; src: string; x: number; y: number }
  | { kind: "pointer-down" };

export interface FrameSize {
  width: number;
  height: number;
}

const COPYABLE_SRC = /^(?:https?:|data:image\/)/i;

export function parseFrameMessage(data: unknown, frame: FrameSize): FrameMessage | null {
  if (typeof data !== "object" || data === null) return null;
  const message = data as Record<string, unknown>;
  const kind = message[MESSAGE_KEY];
  if (kind === "pointer-down") return { kind };
  if (kind !== "image-context-menu") return null;
  const { src, x, y } = message;
  if (typeof src !== "string" || !COPYABLE_SRC.test(src)) return null;
  if (!isWithin(x, frame.width) || !isWithin(y, frame.height)) return null;
  return { kind, src, x, y };
}

function isWithin(value: unknown, limit: number): value is number {
  return typeof value === "number" && value >= 0 && value <= limit;
}

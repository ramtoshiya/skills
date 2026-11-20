import type { MessageDispatchHookContext, MessageDispatchHookDecision } from "@get-bb/plugin-sdk";

type Context = Pick<MessageDispatchHookContext, "attempt" | "thread" | "senderThreadId" | "parentThreadId" | "origin" | "initiator" | "requestedExecution">;
type Versioned = { family: string; version: number[] };

function parse(id: string): Versioned | null {
  const claude = /^claude-([a-z]+)-(\d+(?:-\d+)*)$/.exec(id);
  if (claude) {
    const parts = claude[2].split("-");
    if (parts.length > 1 && /^\d{8}$/.test(parts[parts.length - 1])) parts.pop();
    return { family: `claude-${claude[1]}`, version: parts.map(Number) };
  }
  const gpt = /^gpt-(\d+(?:\.\d+)?)-([a-z]+)$/.exec(id);
  return gpt ? { family: `gpt-${gpt[2]}`, version: gpt[1].split(".").map(Number) } : null;
}

function compare(a: number[], b: number[]): number {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const difference = (a[i] ?? 0) - (b[i] ?? 0);
    if (difference) return difference;
  }
  return 0;
}

export function eligible(ctx: Context): boolean {
  return ctx.attempt === "start-turn" && ctx.thread.status === "pending" && ctx.initiator !== "system" && ctx.initiator !== "mixed" && ctx.senderThreadId !== "mixed" && (Boolean(ctx.senderThreadId) || (Boolean(ctx.parentThreadId) && ctx.origin !== "app"));
}

export function decide(ctx: Context, ids: readonly string[]): MessageDispatchHookDecision {
  const model = ctx.requestedExecution.model;
  if (!eligible(ctx) || !model) return { action: "proceed" };
  const base = model.replace(/\[[^\[\]]+\]$/, "");
  const requested = parse(base);
  if (!requested || !ids.includes(base)) return { action: "proceed" };
  let newest = base;
  let version = requested.version;
  for (const id of ids) {
    const candidate = parse(id);
    if (candidate && candidate.family === requested.family && compare(candidate.version, version) > 0) {
      newest = id;
      version = candidate.version;
    }
  }
  return newest === base ? { action: "proceed" } : {
    action: "reject",
    message: `${model} is older than ${newest}. Start a new thread with ${newest}, or use the newest-model script from the worker-routing skill.`,
  };
}

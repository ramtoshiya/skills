import type { BbPluginApi } from "@get-bb/plugin-sdk";
import type { DraftTarget } from "./server.ts";

type QueuedMessage = Awaited<ReturnType<BbPluginApi["sdk"]["threads"]["queue"]["list"]>>[number];

export function selectDraft(messages: readonly QueuedMessage[]): DraftTarget | null {
  if (messages.length !== 1) return null;
  const message = messages[0];
  if (
    message === undefined ||
    message.state !== "waiting" ||
    message.waitingOn?.kind !== "plugin" ||
    message.waitingOn.pluginId !== "held-drafts" ||
    message.originPluginId !== "held-drafts" ||
    message.payload.kind !== "inline" ||
    message.sendAt !== null ||
    message.groupWithNext ||
    !message.editable
  ) return null;
  return {
    threadId: message.threadId,
    queuedMessageId: message.id,
    updatedAt: message.updatedAt,
  };
}

export function indexDrafts(messages: readonly QueuedMessage[]): ReadonlyMap<string, DraftTarget> {
  const groups = Map.groupBy(messages, (message) => message.threadId);
  const drafts = new Map<string, DraftTarget>();
  for (const [threadId, group] of groups) {
    const target = selectDraft(group);
    if (target !== null) drafts.set(threadId, target);
  }
  return drafts;
}

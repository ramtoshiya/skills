import type { BbPluginApi } from "@get-bb/plugin-sdk";
import type { DraftTarget, Execution } from "./server.ts";

export type QueuedMessage = Awaited<ReturnType<BbPluginApi["sdk"]["threads"]["queue"]["list"]>>[number];

export type ModelCatalogs = ReadonlyMap<string, ReadonlySet<string>>;

export type RunRequest =
  | { kind: "pick"; execution: Execution }
  | { kind: "as-queued"; catalogs: ModelCatalogs };

export type RunPlan =
  | { kind: "send" }
  | { kind: "update"; execution: Execution }
  | { kind: "replace"; execution: Execution }
  | { kind: "refuse"; message: string };

export function findDraft(messages: readonly QueuedMessage[]): QueuedMessage | null {
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
  return message;
}

export function draftTarget(message: QueuedMessage): DraftTarget {
  return { threadId: message.threadId, queuedMessageId: message.id, updatedAt: message.updatedAt };
}

export function indexDrafts(messages: readonly QueuedMessage[]): ReadonlyMap<string, QueuedMessage> {
  const groups = Map.groupBy(messages, (message) => message.threadId);
  const drafts = new Map<string, QueuedMessage>();
  for (const [threadId, group] of groups) {
    const message = findDraft(group);
    if (message !== null) drafts.set(threadId, message);
  }
  return drafts;
}

export function planRun({ providerId, message, request }: {
  providerId: string;
  message: Pick<QueuedMessage, "model" | "reasoningLevel" | "serviceTier">;
  request: RunRequest;
}): RunPlan {
  if (request.kind === "pick") {
    const { execution } = request;
    if (execution.providerId !== providerId) return { kind: "replace", execution };
    const unchanged =
      execution.model === message.model &&
      (execution.reasoningLevel ?? message.reasoningLevel) === message.reasoningLevel &&
      (execution.serviceTier ?? message.serviceTier) === message.serviceTier;
    return unchanged ? { kind: "send" } : { kind: "update", execution };
  }
  if (request.catalogs.get(providerId)?.has(message.model) === true) return { kind: "send" };
  const offeredBy = [...request.catalogs].filter(([, models]) => models.has(message.model)).map(([id]) => id);
  const [only] = offeredBy;
  if (offeredBy.length === 1 && only !== undefined) {
    return {
      kind: "replace",
      execution: {
        providerId: only,
        model: message.model,
        reasoningLevel: message.reasoningLevel,
        serviceTier: message.serviceTier,
      },
    };
  }
  return {
    kind: "refuse",
    message: `The draft's model ${message.model} is not offered by its provider ${providerId}${
      offeredBy.length > 1 ? ` and is offered by several others (${offeredBy.join(", ")})` : " or any other enabled provider"
    }. Use Run draft on… to choose a model.`,
  };
}

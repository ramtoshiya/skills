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
  | { kind: "choose" };

type QueuedExecution = Pick<QueuedMessage, "model" | "reasoningLevel" | "serviceTier">;

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

const queuedExecution = (providerId: string, message: QueuedExecution): Required<Execution> => ({
  providerId,
  model: message.model,
  reasoningLevel: message.reasoningLevel,
  serviceTier: message.serviceTier,
});

function offeringProviders(providerId: string, model: string, catalogs: ModelCatalogs): string[] {
  if (catalogs.get(providerId)?.has(model) === true) return [providerId];
  return [...catalogs].filter(([, models]) => models.has(model)).map(([id]) => id);
}

export function planRun({ providerId, message, request }: {
  providerId: string;
  message: QueuedExecution;
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
  const offeredBy = offeringProviders(providerId, message.model, request.catalogs);
  const [only] = offeredBy;
  if (offeredBy.length !== 1 || only === undefined) return { kind: "choose" };
  return only === providerId ? { kind: "send" } : { kind: "replace", execution: queuedExecution(only, message) };
}

export function startingExecution({ providerId, message, catalogs }: {
  providerId: string;
  message: QueuedExecution;
  catalogs: ModelCatalogs;
}): Required<Execution> {
  const [offering] = offeringProviders(providerId, message.model, catalogs);
  if (offering !== undefined) return queuedExecution(offering, message);
  const [providerDefault = message.model] = catalogs.get(providerId) ?? [];
  return { ...queuedExecution(providerId, message), model: providerDefault };
}

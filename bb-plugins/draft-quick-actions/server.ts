import { defineRpcContract, type BbPluginApi } from "@get-bb/plugin-sdk";
import { z } from "zod";
import { findDraft, planRun, type ModelCatalogs, type QueuedMessage, type RunRequest } from "./drafts.ts";

type Sdk = BbPluginApi["sdk"];
type Thread = Awaited<ReturnType<Sdk["threads"]["get"]>>;
type SpawnEnvironment = Parameters<Sdk["threads"]["spawn"]>[0]["environment"];

const targetSchema = z.object({
  threadId: z.string().min(1),
  queuedMessageId: z.string().min(1),
  updatedAt: z.number().int().nonnegative(),
}).strict();

const executionSchema = z.object({
  providerId: z.string().min(1),
  model: z.string().min(1),
  reasoningLevel: z.string().optional(),
  serviceTier: z.string().optional(),
}).strict();

const heldDraftsMetadataSchema = z.object({
  environment: z.discriminatedUnion("type", [
    z.object({ type: z.literal("project-default") }).strict(),
    z.object({
      type: z.literal("host"),
      hostId: z.string().min(1).optional(),
      workspace: z.discriminatedUnion("type", [
        z.object({ type: z.literal("personal") }).strict(),
        z.object({
          type: z.literal("managed-worktree"),
          baseBranch: z.discriminatedUnion("kind", [
            z.object({ kind: z.literal("default") }).strict(),
            z.object({ kind: z.literal("named"), name: z.string().min(1) }).strict(),
          ]),
        }).strict(),
      ]),
    }).strict(),
  ]) satisfies z.ZodType<SpawnEnvironment>,
});

export type DraftTarget = z.infer<typeof targetSchema>;
export type Execution = z.infer<typeof executionSchema>;

export const rpcContract = defineRpcContract({
  runDraft: {
    input: targetSchema.extend({ execution: executionSchema.optional() }).strict(),
    output: z.discriminatedUnion("kind", [
      z.object({ kind: z.literal("sent") }),
      z.object({ kind: z.literal("queued"), reason: z.string() }),
      z.object({ kind: z.literal("replaced"), threadId: z.string() }),
      z.object({ kind: z.literal("replaced-draft-kept"), threadId: z.string(), reason: z.string() }),
    ]),
  },
});

export type RunResult = z.infer<typeof rpcContract.runDraft.output>;

export default function plugin(bb: BbPluginApi) {
  const sending = new Set<string>();

  async function loadCatalogs(thread: Thread): Promise<ModelCatalogs> {
    const enabled = (await bb.sdk.providers.catalog()).filter((provider) => provider.enabled && provider.available);
    const providerIds = [...new Set([thread.providerId, ...enabled.map((provider) => provider.id)])];
    const results = await Promise.allSettled(
      providerIds.map((providerId) => bb.sdk.providers.models({ providerId, projectId: thread.projectId })),
    );
    const catalogs = new Map<string, ReadonlySet<string>>();
    results.forEach((result, index) => {
      const providerId = providerIds[index];
      if (providerId === undefined) return;
      if (result.status === "fulfilled") catalogs.set(providerId, new Set(result.value.models.map((model) => model.model)));
      else if (providerId === thread.providerId) throw result.reason;
    });
    return catalogs;
  }

  async function send(threadId: string, queuedMessageId: string): Promise<RunResult> {
    const result = await bb.sdk.threads.queuedMessages.send({ threadId, queuedMessageId, mode: "auto" });
    if (result.delivery === "sent") return { kind: "sent" };
    const waiting = result.queuedMessage.waitingOn;
    return {
      kind: "queued",
      reason: waiting?.kind === "plugin" ? waiting.reason : waiting?.kind ?? "queued",
    };
  }

  async function replace(thread: Thread, message: QueuedMessage, execution: Execution): Promise<RunResult> {
    const metadata = heldDraftsMetadataSchema.safeParse(
      await bb.sdk.threads.getPluginMetadata({ threadId: thread.id, pluginId: "held-drafts" }),
    );
    if (!metadata.success) {
      throw new Error(
        "This draft was created before Held Drafts recorded its environment, so it cannot move to another provider. Recreate it with bb draft create, or choose a model from its own provider.",
      );
    }
    const spawned = await bb.sdk.threads.spawn({
      projectId: thread.projectId,
      environment: metadata.data.environment,
      input: message.content,
      ...(thread.title === null ? {} : { title: thread.title }),
      ...(thread.parentThreadId === null ? {} : { parentThreadId: thread.parentThreadId }),
      parentNotifications: thread.parentNotifications,
      sectionId: thread.sectionId,
      ...execution,
      permissionMode: message.permissionMode,
    });
    try {
      await bb.sdk.threads.delete({ threadId: thread.id, childThreadsConfirmed: false });
    } catch (cause) {
      return { kind: "replaced-draft-kept", threadId: spawned.id, reason: cause instanceof Error ? cause.message : String(cause) };
    }
    return { kind: "replaced", threadId: spawned.id };
  }

  bb.rpc.register(rpcContract, {
    async runDraft({ execution, ...target }): Promise<RunResult> {
      if (sending.has(target.threadId)) {
        throw new Error("This draft is already being sent.");
      }
      sending.add(target.threadId);
      try {
        const thread = await bb.sdk.threads.get({ threadId: target.threadId });
        if (thread.status !== "pending" || thread.archivedAt !== null || thread.deletedAt !== null || thread.originPluginId !== "held-drafts") {
          throw new Error("This thread is no longer an unstarted Held Drafts draft.");
        }
        const message = findDraft(await bb.sdk.threads.queuedMessages.list({ threadId: target.threadId }));
        if (message === null || message.id !== target.queuedMessageId || message.updatedAt !== target.updatedAt) {
          throw new Error("The draft changed. Refresh the list and review it before sending.");
        }
        const request: RunRequest = execution === undefined
          ? { kind: "as-queued", catalogs: await loadCatalogs(thread) }
          : { kind: "pick", execution };
        const plan = planRun({ providerId: thread.providerId, message, request });
        switch (plan.kind) {
          case "send":
            return await send(thread.id, message.id);
          case "update": {
            const { providerId: _, ...fields } = plan.execution;
            const updated = await bb.sdk.threads.queuedMessages.update({
              threadId: thread.id,
              queuedMessageId: message.id,
              expectedUpdatedAt: message.updatedAt,
              ...fields,
            });
            return await send(thread.id, updated.id);
          }
          case "replace":
            return await replace(thread, message, plan.execution);
          case "refuse":
            throw new Error(plan.message);
          default: {
            const exhaustive: never = plan;
            return exhaustive;
          }
        }
      } finally {
        sending.delete(target.threadId);
      }
    },
  });
}

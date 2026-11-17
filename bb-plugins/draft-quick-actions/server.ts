import { defineRpcContract, type BbPluginApi } from "@get-bb/plugin-sdk";
import { z } from "zod";
import { selectDraft } from "./drafts.ts";

const targetSchema = z.object({
  threadId: z.string().min(1),
  queuedMessageId: z.string().min(1),
  updatedAt: z.number().int().nonnegative(),
}).strict();

export type DraftTarget = z.infer<typeof targetSchema>;

export const rpcContract = defineRpcContract({
  runDraft: {
    input: targetSchema,
    output: z.discriminatedUnion("kind", [
      z.object({ kind: z.literal("sent") }),
      z.object({ kind: z.literal("queued"), reason: z.string() }),
    ]),
  },
});

export default function plugin(bb: BbPluginApi) {
  const sending = new Set<string>();

  bb.rpc.register(rpcContract, {
    async runDraft(target): Promise<z.infer<typeof rpcContract.runDraft.output>> {
      if (sending.has(target.threadId)) {
        throw new Error("This draft is already being sent.");
      }
      sending.add(target.threadId);
      try {
        const thread = await bb.sdk.threads.get({ threadId: target.threadId });
        if (thread.status !== "pending" || thread.archivedAt !== null || thread.deletedAt !== null || thread.originPluginId !== "held-drafts") {
          throw new Error("This thread is no longer an unstarted Held Drafts draft.");
        }
        const messages = await bb.sdk.threads.queuedMessages.list({ threadId: target.threadId });
        const current = selectDraft(messages);
        if (current === null || current.queuedMessageId !== target.queuedMessageId || current.updatedAt !== target.updatedAt) {
          throw new Error("The draft changed. Refresh the list and review it before sending.");
        }
        const result = await bb.sdk.threads.queuedMessages.send({
          threadId: target.threadId,
          queuedMessageId: target.queuedMessageId,
          mode: "auto",
        });
        if (result.delivery === "sent") return { kind: "sent" };
        const waiting = result.queuedMessage.waitingOn;
        return {
          kind: "queued",
          reason: waiting?.kind === "plugin" ? waiting.reason : waiting?.kind ?? "queued",
        };
      } finally {
        sending.delete(target.threadId);
      }
    },
  });
}

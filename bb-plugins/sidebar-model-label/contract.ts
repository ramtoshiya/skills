import { defineRpcContract } from "@get-bb/plugin-sdk";
import { z } from "zod";

export const MAX_THREAD_KEYS = 2000;
export const MAX_PROVIDER_KEYS = 100;

const catalogModelSchema = z.object({
  model: z.string(),
  displayName: z.string(),
});
export type CatalogModel = z.infer<typeof catalogModelSchema>;

export const withinThreadKeyLimit = (threadIds: readonly string[]) =>
  threadIds.slice(0, MAX_THREAD_KEYS);
export const withinProviderKeyLimit = (providerIds: readonly string[]) =>
  providerIds.slice(0, MAX_PROVIDER_KEYS);
export const threadTag = (threadId: string) => `thread:${threadId}`;

export const rpcContract = defineRpcContract({
  threadModels: {
    input: z
      .object({ keys: z.array(z.string().min(1)).max(MAX_THREAD_KEYS) })
      .strict(),
    output: z.record(z.string(), z.string().nullable()),
    keyTags: (threadId) => [threadTag(threadId)],
  },
  providerModels: {
    input: z
      .object({ keys: z.array(z.string().min(1)).max(MAX_PROVIDER_KEYS) })
      .strict(),
    output: z.record(z.string(), z.array(catalogModelSchema)),
  },
});

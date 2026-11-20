import { defineRpcContract } from "@get-bb/plugin-sdk";
import { z } from "zod";

export const MAX_THREAD_KEYS = 2000;

const logicalParentSchema = z.object({ id: z.string(), title: z.string() }).nullable();
export type LogicalParent = z.infer<typeof logicalParentSchema>;

export const rpcContract = defineRpcContract({
  logicalParents: {
    input: z.object({ keys: z.array(z.string().min(1)).max(MAX_THREAD_KEYS) }).strict(),
    output: z.record(z.string(), logicalParentSchema),
  },
});

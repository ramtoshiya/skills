import { defineRpcContract } from "@get-bb/plugin-sdk";
import { z } from "zod";

const failure = z
  .object({
    ok: z.literal(false),
    code: z.enum(["unavailable", "guardrail", "generation", "error"]),
    message: z.string().min(1),
  })
  .strict();

export const hostContract = defineRpcContract({
  "titles.status": {
    input: z.object({}).strict(),
    output: z.discriminatedUnion("ready", [
      z.object({ ready: z.literal(true) }).strict(),
      z.object({ ready: z.literal(false), message: z.string().min(1) }).strict(),
    ]),
  },
  "titles.complete": {
    input: z.object({ prompt: z.string().min(1) }).strict(),
    output: z.union([z.object({ ok: z.literal(true), text: z.string() }).strict(), failure]),
  },
});

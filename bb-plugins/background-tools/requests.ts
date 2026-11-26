import { randomUUID } from "node:crypto";
import { watch } from "node:fs";
import { access, appendFile, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { z } from "zod";
import type { MoveResult } from "./result.ts";

const answerSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("moved"), tools: z.array(z.string()) }),
  z.object({ kind: z.literal("nothing") }),
  z.object({ kind: z.literal("refused"), tools: z.array(z.string()) }),
]);

async function readAnswer(path: string): Promise<MoveResult | null> {
  try {
    return answerSchema.safeParse(JSON.parse(await readFile(path, "utf8"))).data ?? null;
  } catch {
    return null;
  }
}

export async function askSession(storage: string, timeoutMs = 5_000): Promise<MoveResult> {
  const requests = join(storage, "background-requests");
  if (!(await access(requests).then(() => true, () => false))) return { kind: "no-session" };
  const id = randomUUID();
  const name = `background-answer-${id}`;
  const answerPath = join(storage, name);
  const answered = new Promise<MoveResult>((resolve) => {
    const finish = (result: MoveResult) => {
      clearTimeout(timer);
      watcher.close();
      resolve(result);
    };
    const watcher = watch(storage, (_event, file) => {
      if (file !== name) return;
      void readAnswer(answerPath).then((answer) => { if (answer) finish(answer); });
    });
    const timer = setTimeout(() => finish({ kind: "no-session" }), timeoutMs);
  });
  await appendFile(requests, `${id}\n`);
  const result = await answered;
  await rm(answerPath, { force: true });
  return result;
}

import { readdir, rm } from "node:fs/promises";
import { createConnection } from "node:net";
import { join } from "node:path";
import type { MovedTask, MoveResult } from "./result.ts";

type Reply = { ok: true; tasks: MovedTask[] } | { ok: false; error: string };

function askSession(socketPath: string): Promise<Reply | "gone"> {
  return new Promise((resolve) => {
    let received = "";
    const connection = createConnection(socketPath);
    connection.setEncoding("utf8");
    connection.setTimeout(10_000, () => connection.destroy(new Error("The session did not answer in time.")));
    connection.on("data", (chunk) => { received += chunk; });
    connection.on("end", () => {
      try {
        resolve(JSON.parse(received) as Reply);
      } catch {
        resolve({ ok: false, error: "The session closed without an answer." });
      }
    });
    connection.on("error", (error: NodeJS.ErrnoException) => {
      if (error.code === "ECONNREFUSED" || error.code === "ENOENT") resolve("gone");
      else resolve({ ok: false, error: error.message });
    });
  });
}

export async function moveForegroundTools(socketDir: string, threadId: string): Promise<MoveResult> {
  const names = await readdir(socketDir).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return [];
    throw error;
  });
  const sockets = names.filter((name) => name.startsWith(`${threadId}.`) && name.endsWith(".sock"));
  const answers = await Promise.all(sockets.map(async (name) => {
    const socketPath = join(socketDir, name);
    const answer = await askSession(socketPath);
    if (answer === "gone") await rm(socketPath, { force: true });
    return answer;
  }));
  const replies = answers.filter((answer) => answer !== "gone");
  if (replies.length === 0) return { kind: "no-session" };
  const tasks = replies.flatMap((reply) => reply.ok ? reply.tasks : []);
  if (tasks.length > 0) return { kind: "moved", tasks };
  const failure = replies.find((reply) => !reply.ok);
  if (failure) throw new Error(failure.error);
  return { kind: "nothing" };
}

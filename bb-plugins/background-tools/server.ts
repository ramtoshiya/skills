import { PluginCliError, cliCommand, defineCli, defineRpcContract, type BbPluginApi } from "@get-bb/plugin-sdk";
import { z } from "zod";
import { askSession } from "./requests.ts";
import { describeResult, type MoveResult } from "./result.ts";
import { CLAUDE_CODE_PROVIDERS, isClaudeCodeProvider } from "./providers.ts";

const resultSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("moved"), tools: z.array(z.string()) }),
  z.object({ kind: z.literal("nothing") }),
  z.object({ kind: z.literal("refused"), tools: z.array(z.string()) }),
  z.object({ kind: z.literal("no-session") }),
]) satisfies z.ZodType<MoveResult>;

export const rpcContract = defineRpcContract({
  move: { input: z.object({ threadId: z.string().min(1) }).strict(), output: resultSchema },
});

export default function plugin(bb: BbPluginApi) {
  async function move(threadId: string): Promise<MoveResult> {
    const { providerId } = await bb.sdk.threads.get({ threadId });
    if (!isClaudeCodeProvider(providerId)) {
      throw new Error(`Only ${CLAUDE_CODE_PROVIDERS.join(" and ")} threads can move a command to the background, not ${providerId}.`);
    }
    const { storageRootPath } = await bb.sdk.threads.storageLocation({ threadId });
    return askSession(storageRootPath);
  }

  bb.rpc.register(rpcContract, { move: ({ threadId }) => move(threadId) });

  bb.cli.register(defineCli({
    name: "background",
    summary: "Move a Claude Code thread's running command to the background",
    commands: {
      move: cliCommand({
        summary: "Move the running Bash command of a thread to the background, as Ctrl+B does in Claude Code",
        positionals: [{ name: "thread-id", description: "Defaults to the calling thread" }],
        options: { json: { type: "boolean", description: "Print the result as JSON" } },
        async run(input, ctx) {
          const threadId = input.positionals["thread-id"] ?? ctx.threadId;
          if (!threadId) throw new PluginCliError("No thread id", { code: "usage", hint: "Pass a thread id." });
          const result = await move(threadId);
          return {
            exitCode: result.kind === "moved" ? 0 : 1,
            stdout: input.options.json ? JSON.stringify(result) : describeResult(result),
          };
        },
      }),
    },
  }));
}

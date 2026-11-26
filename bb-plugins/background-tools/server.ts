import { PluginCliError, cliCommand, defineCli, defineRpcContract, type BbPluginApi } from "@get-bb/plugin-sdk";
import { access, constants } from "node:fs/promises";
import { join } from "node:path";
import { z } from "zod";
import { describeResult, type MoveResult } from "./result.ts";
import { moveForegroundTools } from "./sessions.ts";
import { CLAUDE_CODE_PROVIDERS, isClaudeCodeProvider } from "./providers.ts";

const resultSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("moved"), tasks: z.array(z.object({ taskId: z.string(), description: z.string() })) }),
  z.object({ kind: z.literal("nothing") }),
  z.object({ kind: z.literal("no-session") }),
]) satisfies z.ZodType<MoveResult>;

export const rpcContract = defineRpcContract({
  move: { input: z.object({ threadId: z.string().min(1) }).strict(), output: resultSchema },
});

export default function plugin(bb: BbPluginApi) {
  // Short because macOS limits a Unix socket path to 103 bytes.
  const socketDir = `/tmp/bb-background-tools-${process.getuid?.() ?? 0}`;

  async function isServerHost(hostId: string): Promise<boolean> {
    return hostId === (await bb.sdk.system.config()).primaryHostId;
  }

  async function findExecutableShim(): Promise<string | null> {
    const { plugins } = await bb.sdk.plugins.list();
    const own = plugins.find((candidate) => candidate.id === bb.pluginId);
    if (!own) return null;
    const shim = join(own.rootDir, "shim.cjs");
    return access(shim, constants.X_OK).then(() => shim, () => null);
  }

  for (const providerId of CLAUDE_CODE_PROVIDERS) {
    bb.providers.experimental_contributeEnv(providerId, async ({ threadId, hostId }) => {
      if (threadId === null || !(await isServerHost(hostId))) return [];
      const shim = await findExecutableShim();
      if (shim === null) {
        bb.log.warn("shim.cjs is missing or not executable, so Claude Code starts without it");
        return [];
      }
      const reason = "Lets a running tool move to the background";
      return [
        { name: "BB_CLAUDE_CODE_EXECUTABLE", value: shim, reason },
        { name: "BB_BACKGROUND_TOOLS_PROVIDER", value: providerId, reason },
        { name: "BB_BACKGROUND_TOOLS_SOCKET_DIR", value: socketDir, reason },
      ];
    });
  }

  async function move(threadId: string): Promise<MoveResult> {
    const { providerId } = await bb.sdk.threads.get({ threadId });
    if (!isClaudeCodeProvider(providerId)) {
      throw new Error(`Only ${CLAUDE_CODE_PROVIDERS.join(" and ")} threads can move a tool to the background, not ${providerId}.`);
    }
    return moveForegroundTools(socketDir, threadId);
  }

  bb.rpc.register(rpcContract, { move: ({ threadId }) => move(threadId) });

  bb.cli.register(defineCli({
    name: "background",
    summary: "Move a Claude Code thread's running tools to the background",
    commands: {
      move: cliCommand({
        summary: "Move the foreground commands and agents of a thread to the background, as Ctrl+B does in Claude Code",
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

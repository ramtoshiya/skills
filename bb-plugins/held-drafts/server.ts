import {
  PluginCliError,
  cliCommand,
  defineCli,
  type BbPluginApi,
  type MessageDispatchHookContext,
} from "@get-bb/plugin-sdk";

type HoldMode = "draft" | "direct";
type SpawnEnvironment = Parameters<BbPluginApi["sdk"]["threads"]["spawn"]>[0]["environment"];

export function shouldHold(
  ctx: MessageDispatchHookContext,
  pluginId: string,
  mode: HoldMode,
): boolean {
  const first = ctx.queuedMessages[0];
  if (first?.waitingOn?.kind === "plugin" && first.waitingOn.pluginId === pluginId) {
    return true;
  }
  return (
    mode === "draft" &&
    ctx.originPluginId === pluginId &&
    ctx.thread.status === "pending"
  );
}

async function resolveHostId(
  bb: BbPluginApi,
  machine: string | undefined,
  threadId: string | undefined,
): Promise<string> {
  if (machine !== undefined) return machine;
  if (threadId !== undefined) {
    const thread = await bb.sdk.threads.get({ threadId });
    if (thread.environmentId !== null) {
      const environment = await bb.sdk.environments.get({
        environmentId: thread.environmentId,
      });
      return environment.hostId;
    }
  }
  const connected = (await bb.sdk.hosts.list()).filter(
    (host) => host.status === "connected",
  );
  if (connected.length === 1) return connected[0]!.id;
  throw new PluginCliError("cannot choose a machine for the worktree", {
    code: "machine_required",
    hint: "Add --machine <host-id>. Run `bb machine list` to find it.",
  });
}

export default async function plugin(bb: BbPluginApi) {
  const settings = bb.settings.define({
    mode: {
      type: "select",
      label: "New threads",
      options: ["draft", "direct"],
      experimental_optionLabels: {
        draft: "Hold the first message until a person sends it",
        direct: "Send the first message immediately",
      },
      default: "draft",
    },
  });

  bb.experimental_hooks.on("message.dispatch", async (ctx) => {
    const { mode } = await settings.get();
    return shouldHold(ctx, bb.pluginId, mode as HoldMode)
      ? { action: "wait", reason: "Draft" }
      : { action: "proceed" };
  });

  bb.cli.register(
    defineCli({
      name: "draft",
      summary: "Create a thread whose first message waits for a person to send it",
      commands: {
        create: cliCommand({
          summary: "Create a held draft thread",
          description:
            "The thread appears with its message in the Queue. Send now dispatches it, and deleting the thread discards it. With the plugin's mode setting at direct, the message is sent immediately instead.",
          options: {
            prompt: {
              type: "string",
              required: true,
              description: "The full first message",
            },
            project: {
              type: "string",
              description: "Project ID. Defaults to the calling thread's project",
            },
            title: { type: "string", description: "Thread title" },
            provider: {
              type: "string",
              description: "Provider ID. Omit for the project's remembered provider",
            },
            model: { type: "string", description: "Model ID" },
            "reasoning-level": { type: "string", description: "Reasoning level ID" },
            "permission-mode": {
              type: "enum",
              values: ["accept-edits", "auto", "full"],
              description: "Permission mode",
            },
            "new-environment": {
              type: "enum",
              values: ["worktree", "personal"],
              description:
                "Create a fresh environment when the draft is sent. Omit for the project default",
            },
            machine: {
              type: "string",
              description:
                "Host ID for --new-environment worktree. Defaults to the calling thread's machine, then the only connected machine",
            },
            "base-branch": {
              type: "string",
              description: "Base branch for --new-environment worktree",
            },
            json: { type: "boolean", description: "Print the created thread as JSON" },
          },
          constraints: [
            { kind: "requires", option: "base-branch", needs: ["new-environment"] },
          ],
          async run({ options }, ctx) {
            const projectId = options.project ?? ctx.projectId;
            if (projectId === undefined) {
              throw new PluginCliError("no project to create the draft in", {
                code: "project_required",
                hint: "Add --project <project-id>. Run `bb project list` to find it.",
              });
            }
            const hostId =
              options["new-environment"] === "worktree"
                ? await resolveHostId(bb, options.machine, ctx.threadId)
                : undefined;
            const environment: SpawnEnvironment =
              options["new-environment"] === undefined
                ? { type: "project-default" }
                : {
                    type: "host",
                    ...(hostId === undefined ? {} : { hostId }),
                    workspace:
                      options["new-environment"] === "personal"
                        ? { type: "personal" }
                        : {
                            type: "managed-worktree",
                            baseBranch:
                              options["base-branch"] === undefined
                                ? { kind: "default" }
                                : { kind: "named", name: options["base-branch"] },
                          },
                  };
            const { mode } = await settings.get();
            const result = await bb.sdk.threads.spawn({
              projectId,
              environment,
              pluginMetadata: { environment },
              prompt: options.prompt,
              ...(options.title === undefined ? {} : { title: options.title }),
              ...(options.provider === undefined ? {} : { providerId: options.provider }),
              ...(options.model === undefined ? {} : { model: options.model }),
              ...(options["reasoning-level"] === undefined
                ? {}
                : { reasoningLevel: options["reasoning-level"] }),
              ...(options["permission-mode"] === undefined
                ? {}
                : { permissionMode: options["permission-mode"] }),
            });
            const threadId = result.id;
            const held = mode === "draft";
            return {
              exitCode: 0,
              stdout: options.json
                ? `${JSON.stringify({ threadId, held })}\n`
                : held
                  ? `Created draft ${threadId}. It waits in the Queue until someone sends it.\n`
                  : `Created ${threadId} and sent its first message (mode: direct).\n`,
            };
          },
        }),
      },
    }),
  );
}

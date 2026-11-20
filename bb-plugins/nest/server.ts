import { PluginCliError, cliCommand, defineCli, type BbPluginApi } from "@get-bb/plugin-sdk";
import { rpcContract, type LogicalParent } from "./contract";
import {
  TURN_EVENT_TYPES,
  UsageError,
  chooseRoute,
  endedToSelfCompact,
  mailTagKeys,
  parseEnvironment,
  parseMetadata,
  parsePrompt,
  preamble,
  relayText,
  resolvePath,
  type EnvironmentChoice,
  type Outcome,
  type PromptSource,
  type Route,
  type ThreadLink,
  waitingOutcome,
} from "./nest";

type Sdk = BbPluginApi["sdk"];
type Thread = Awaited<ReturnType<Sdk["threads"]["get"]>>;
type ListedThread = Awaited<ReturnType<Sdk["threads"]["list"]>>[number];
type SpawnEnvironment = Parameters<Sdk["threads"]["spawn"]>[0]["environment"];

const PAGE = 200;
const MAX_ANCESTORS = 64;
const EVENT_LIMIT = 100;
const MAIL_PLUGIN_ID = "mail";

function chunks<T>(items: readonly T[], size: number): T[][] {
  const result: T[][] = [];
  for (let index = 0; index < items.length; index += size) result.push(items.slice(index, index + size));
  return result;
}

function threadTitle(thread: Pick<ListedThread, "id" | "title" | "titleFallback">): string {
  return thread.title ?? thread.titleFallback ?? thread.id;
}

function usage<T>(parse: () => T): T {
  try {
    return parse();
  } catch (error) {
    if (error instanceof UsageError) throw new PluginCliError(error.message, { code: "usage", hint: error.hint });
    throw error;
  }
}

export default function plugin(bb: BbPluginApi) {
  /** bb accepts a child only under a thread whose `canSpawnChild` is true. */
  async function lineage(caller: Thread): Promise<ThreadLink[]> {
    const links: ThreadLink[] = [];
    let thread: Thread | null = caller;
    while (thread !== null && links.length < MAX_ANCESTORS) {
      links.push({ id: thread.id, canSpawnChild: thread.canSpawnChild });
      if (thread.canSpawnChild || thread.parentThreadId === null) break;
      thread = await bb.sdk.threads.get({ threadId: thread.parentThreadId });
    }
    return links;
  }

  async function hostOf(thread: Thread): Promise<string> {
    if (thread.environmentId === null) {
      throw new PluginCliError(`Thread ${thread.id} has no environment, so its machine is unknown.`, { code: "no_environment" });
    }
    const environment = await bb.sdk.environments.get({ environmentId: thread.environmentId });
    return environment.hostId;
  }

  async function spawnEnvironment(choice: EnvironmentChoice, hostId: () => Promise<string>): Promise<SpawnEnvironment> {
    switch (choice.kind) {
      case "project-default":
        return { type: "project-default" };
      case "reuse":
        return { type: "reuse", environmentId: choice.environmentId };
      case "path":
        return { type: "host", hostId: await hostId(), workspace: { type: "unmanaged", path: choice.path } };
      case "new":
        return {
          type: "host",
          hostId: await hostId(),
          workspace:
            choice.workspace === "personal"
              ? { type: "personal" }
              : {
                  type: "managed-worktree",
                  baseBranch: choice.baseBranch ? { kind: "named", name: choice.baseBranch } : { kind: "default" },
                },
        };
    }
  }

  async function readBrief(source: PromptSource, cwd: string | undefined, hostId: () => Promise<string>): Promise<string> {
    if (source.kind === "text") return source.text;
    const path = usage(() => resolvePath(source.path, cwd));
    const file = await bb.sdk.files.read({ hostId: await hostId(), path });
    const text = file.contentEncoding === "base64" ? Buffer.from(file.content, "base64").toString("utf8") : file.content;
    if (text.trim() === "") throw new PluginCliError(`${path} is empty.`, { code: "empty_brief" });
    return text;
  }

  async function endedToSelfCompactSafely(threadId: string): Promise<boolean> {
    try {
      return endedToSelfCompact(
        await bb.sdk.threads.events.list({ threadId, order: "desc", limit: String(EVENT_LIMIT), types: [...TURN_EVENT_TYPES] }),
      );
    } catch (error) {
      bb.log.warn(`Could not read ${threadId}'s events, so its result is relayed: ${String(error)}`);
      return false;
    }
  }

  async function relay(thread: Pick<Thread, "id" | "originPluginId">, outcome: Outcome): Promise<void> {
    if (thread.originPluginId !== bb.pluginId) return;
    const metadata = parseMetadata(await bb.sdk.threads.getPluginMetadata({ threadId: thread.id }));
    if (metadata === null) return;
    if (outcome.kind === "completed" && (await endedToSelfCompactSafely(thread.id))) {
      bb.log.info(`Not relaying ${thread.id}: its turn ended to self-compact.`);
      return;
    }
    try {
      await bb.sdk.threads.send({
        threadId: metadata.logicalParentThreadId,
        mode: "auto",
        senderThreadId: thread.id,
        input: [{ type: "text", text: relayText(thread.id, outcome), mentions: [] }],
      });
    } catch (error) {
      bb.log.warn(`Could not relay ${outcome.kind} from ${thread.id} to ${metadata.logicalParentThreadId}: ${String(error)}`);
    }
  }

  bb.events.on("thread.idle", ({ thread, lastAssistantText }) => relay(thread, { kind: "completed", reply: lastAssistantText }));
  bb.events.on("thread.failed", ({ thread, error }) => relay(thread, { kind: "failed", error }));
  bb.events.on("interaction.pending", ({ thread, interaction }) => relay(thread, waitingOutcome(interaction)));

  async function listAll(filter: { parentThreadId: string } | { originPluginId: string }): Promise<ListedThread[]> {
    const all: ListedThread[] = [];
    for (let offset = 0; ; offset += PAGE) {
      const page = await bb.sdk.threads.list({ ...filter, archived: false, includeHidden: true, limit: PAGE, offset });
      all.push(...page);
      if (page.length < PAGE) return all;
    }
  }

  async function logicalParents(threadIds: readonly string[]): Promise<Map<string, string>> {
    const parents = new Map<string, string>();
    for (const chunk of chunks(threadIds, PAGE)) {
      const { threads } = await bb.sdk.threads.experimental_listPluginMetadata({ threadIds: chunk });
      for (const { threadId, metadata } of threads) {
        const parsed = parseMetadata(metadata);
        if (parsed) parents.set(threadId, parsed.logicalParentThreadId);
      }
    }
    return parents;
  }

  async function logicalChildren(parentId: string): Promise<Array<{ thread: ListedThread; route: Route["kind"] }>> {
    const [physical, relayed] = await Promise.all([
      listAll({ parentThreadId: parentId }),
      listAll({ originPluginId: bb.pluginId }),
    ]);
    const candidates = new Map([...physical, ...relayed].map((thread) => [thread.id, thread]));
    const parents = await logicalParents([...candidates.keys()]);
    const children: Array<{ thread: ListedThread; route: Route["kind"] }> = [];
    for (const thread of candidates.values()) {
      const logical = parents.get(thread.id);
      if (logical === parentId) children.push({ thread, route: "relay" });
      else if (logical === undefined && thread.parentThreadId === parentId) children.push({ thread, route: "child" });
    }
    return children.sort((a, b) => a.thread.createdAt - b.thread.createdAt);
  }

  bb.cli.register(
    defineCli({
      name: "nest",
      summary: "Start worker threads at any depth",
      description:
        "bb rejects a child thread below four levels. bb nest spawn starts a normal child when bb allows one. Otherwise it starts the worker under the nearest ancestor that can take it and relays the worker's results to the caller.",
      commands: {
        spawn: cliCommand({
          summary: "Start a worker of the calling thread (BB_THREAD_ID)",
          options: {
            project: { type: "string", description: "Project ID. Defaults to BB_PROJECT_ID" },
            environment: { type: "string", description: "Existing environment ID or unmanaged workspace path" },
            "new-environment": { type: "enum", values: ["personal", "worktree"], description: "Create a fresh environment of this kind" },
            "base-branch": { type: "string", description: "Base branch for --new-environment worktree" },
            provider: { type: "string", description: "Provider ID" },
            model: { type: "string", description: "Model ID" },
            "reasoning-level": { type: "string", description: "Reasoning level the model lists" },
            title: { type: "string", description: "Thread title" },
            tag: {
              type: "string",
              repeatable: true,
              description: "Mail tag for the new thread, as key=value or a bare word, such as role=reviewer. Repeat for more",
            },
            prompt: { type: "string", description: "Brief text" },
            "prompt-file": {
              type: "string",
              description: "Read the brief from this file on the calling machine. Plugin commands cannot read multi-line stdin, so - is rejected",
            },
            "parent-self": { type: "boolean", description: "Accepted and implied. The calling thread is always the parent" },
            json: { type: "boolean", description: "Print the new thread as JSON" },
          },
          constraints: [{ kind: "exactly-one", options: ["prompt", "prompt-file"] }],
          async run({ options }, ctx) {
            if (!ctx.threadId) {
              throw new PluginCliError("bb nest spawn needs BB_THREAD_ID, because it starts a worker of the calling thread.", {
                code: "no_caller",
                hint: "Outside an agent thread, use bb thread spawn.",
              });
            }
            const environment = usage(() =>
              parseEnvironment({
                environment: options.environment,
                newEnvironment: options["new-environment"],
                baseBranch: options["base-branch"],
              }),
            );
            const promptSource = usage(() => parsePrompt({ prompt: options.prompt, promptFile: options["prompt-file"] }));
            const tags = usage(() => mailTagKeys((options.tag as string[] | undefined) ?? []));
            const projectId = options.project ?? ctx.projectId;
            if (!projectId) throw new PluginCliError("Pass --project <id>.", { code: "no_project" });

            const caller = await bb.sdk.threads.get({ threadId: ctx.threadId });
            let host: Promise<string> | undefined;
            const hostId = () => (host ??= hostOf(caller));
            const brief = await readBrief(promptSource, ctx.cwd, hostId);
            const route = chooseRoute(await lineage(caller));
            const base = {
              projectId,
              environment: await spawnEnvironment(environment, hostId),
              senderThreadId: caller.id,
              ...(options.provider ? { providerId: options.provider } : {}),
              ...(options.model ? { model: options.model } : {}),
              ...(options["reasoning-level"] ? { reasoningLevel: options["reasoning-level"] } : {}),
              ...(options.title ? { title: options.title } : {}),
            };
            let thread: Thread;
            try {
              thread =
                route.kind === "child"
                  ? await bb.sdk.threads.spawn({ ...base, origin: "cli", parentThreadId: route.parentThreadId, prompt: brief })
                  : await bb.sdk.threads.spawn({
                      ...base,
                      parentThreadId: route.hostThreadId,
                      parentNotifications: "off",
                      lifecycleOwnerThreadId: route.logicalParentThreadId,
                      pluginMetadata: { logicalParentThreadId: route.logicalParentThreadId },
                      prompt: `${preamble(route)}${brief}`,
                    });
            } catch (error) {
              throw new PluginCliError(`Failed to create thread: ${error instanceof Error ? error.message : String(error)}`, {
                code: "spawn_failed",
              });
            }
            let tagError: string | null = null;
            if (Object.keys(tags).length > 0) {
              try {
                await bb.sdk.threads.updatePluginMetadata({ threadId: thread.id, pluginId: MAIL_PLUGIN_ID, set: tags });
              } catch (error) {
                tagError = error instanceof Error ? error.message : String(error);
              }
            }
            if (options.json) return { exitCode: 0, stdout: JSON.stringify({ ...thread, nest: route, ...(tagError ? { tagError } : {}) }, null, 2) };
            const tagWarning = tagError ? `\nThe thread started without its tags (${tagError}). Add them with bb mail tag add ${thread.id} <tags>.` : "";
            const notice =
              route.kind === "child"
                ? "You will be notified when this thread is done."
                : `bb's depth limit placed it under ${route.hostThreadId}. Nest relays each of its turn results, failures, and questions to this thread.`;
            return { exitCode: 0, stdout: `Thread spawned: ${thread.id}\n${notice}${tagWarning}` };
          },
        }),
        list: cliCommand({
          summary: "List a thread's unarchived workers, including those started past bb's depth limit",
          options: {
            parent: { type: "string", description: "Thread whose workers to list. Defaults to BB_THREAD_ID" },
            json: { type: "boolean", description: "Print JSON" },
          },
          async run({ options }, ctx) {
            const parentId = options.parent ?? ctx.threadId;
            if (!parentId) throw new PluginCliError("Pass --parent <threadId>.", { code: "no_parent" });
            const rows = (await logicalChildren(parentId)).map(({ thread, route }) => ({
              id: thread.id,
              status: thread.status,
              route,
              physicalParentThreadId: thread.parentThreadId,
              title: threadTitle(thread),
            }));
            if (options.json) return { exitCode: 0, stdout: JSON.stringify(rows, null, 2) };
            if (rows.length === 0) return { exitCode: 0, stdout: `No unarchived workers of ${parentId}.` };
            return {
              exitCode: 0,
              stdout: rows.map((row) => `${row.id}  ${row.status.padEnd(8)}  ${row.route.padEnd(5)}  ${row.title}`).join("\n"),
            };
          },
        }),
      },
    }),
  );

  bb.rpc.register(rpcContract, {
    async logicalParents({ keys }) {
      const result: Record<string, LogicalParent> = Object.fromEntries(keys.map((key) => [key, null]));
      const parents = await logicalParents(keys);
      const titles = new Map<string, string>();
      for (const chunk of chunks([...new Set(parents.values())], PAGE)) {
        for (const thread of await bb.sdk.threads.list({ threadIds: chunk, includeHidden: true, limit: PAGE })) {
          titles.set(thread.id, threadTitle(thread));
        }
      }
      for (const [threadId, parentId] of parents) result[threadId] = { id: parentId, title: titles.get(parentId) ?? parentId };
      return result;
    },
  });
}

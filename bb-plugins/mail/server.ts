import { PluginCliError, cliCommand, defineCli, type BbPluginApi } from "@get-bb/plugin-sdk";
import {
  COMMAND_EVENT_TYPES,
  TURN_EVENT_TYPES,
  UsageError,
  chooseRecipients,
  classifyNotice,
  commandRuns,
  decideCompletion,
  inboxDecision,
  lastTurnCommands,
  launchedSelfCompaction,
  logicalAncestors,
  nestLogicalParent,
  parseSelector,
  parseTag,
  tagKey,
  tagsOf,
  waitState,
  type Candidate,
  type CompletionFacts,
  type Recipients,
  type Term,
} from "./mail";

type Sdk = BbPluginApi["sdk"];
type Thread = Awaited<ReturnType<Sdk["threads"]["get"]>>;
type ListedThread = Awaited<ReturnType<Sdk["threads"]["list"]>>[number];
type Row = Awaited<ReturnType<Sdk["threads"]["queuedMessages"]["list"]>>[number];

const PAGE = 200;
const NEST_PLUGIN_ID = "nest";
const HOLD_LIMIT_MS = 30_000;
const POLL_MS = 1_000;
const RELEASE_MARGIN_MS = 5_000;

function chunks<T>(items: readonly T[], size: number): T[][] {
  const result: T[][] = [];
  for (let index = 0; index < items.length; index += size) result.push(items.slice(index, index + size));
  return result;
}

function usage<T>(parse: () => T): T {
  try {
    return parse();
  } catch (error) {
    if (error instanceof UsageError) throw new PluginCliError(error.message, { code: "usage" });
    throw error;
  }
}

function describeTerms(terms: readonly Term[]): string {
  return terms.map((term) => (term.kind === "tag" ? term.tag : `${term.key}=${term.value}`)).join(" ");
}

export default function plugin(bb: BbPluginApi) {
  function guard(label: string, work: () => Promise<void>): Promise<void> {
    return work().catch((error: unknown) => bb.log.warn(`${label}: ${error instanceof Error ? error.message : String(error)}`));
  }

  bb.experimental_hooks.on("message.dispatch", (context) => {
    try {
      return inboxDecision(context, bb.pluginId);
    } catch (error) {
      bb.log.warn(`message.dispatch: ${error instanceof Error ? error.message : String(error)}. Letting the message through.`);
      return { action: "proceed" };
    }
  });

  bb.events.on("thread.active", ({ thread }) =>
    guard("thread.active", async () => {
      const held = await bb.sdk.threads.queue.list({ waitHolder: `plugin:${bb.pluginId}`, threadId: thread.id });
      if (held.length > 0) await bb.experimental_hooks.recheck("message.dispatch");
    }),
  );

  async function currentRow(row: Row): Promise<Row | null> {
    const rows = await bb.sdk.threads.queuedMessages.list({ threadId: row.threadId });
    return rows.find((candidate) => candidate.id === row.id) ?? null;
  }

  async function release(row: Row): Promise<void> {
    await bb.sdk.threads.queuedMessages.update({
      threadId: row.threadId,
      queuedMessageId: row.id,
      expectedUpdatedAt: row.updatedAt,
      sendAt: Date.now(),
    });
  }

  async function completionFacts(parentId: string, childId: string, holdExpired: boolean): Promise<CompletionFacts> {
    const [childEvents, parentEvents, output] = await Promise.all([
      bb.sdk.threads.events.list({ threadId: childId, order: "desc", limit: String(PAGE), types: [...TURN_EVENT_TYPES] }),
      bb.sdk.threads.events.list({ threadId: parentId, order: "desc", limit: String(PAGE), types: [...COMMAND_EVENT_TYPES] }),
      bb.sdk.threads.output({ threadId: childId }),
    ]);
    const reply = output.output ?? null;
    return {
      childId,
      reply,
      compacting: launchedSelfCompaction(lastTurnCommands(childEvents)),
      wait: waitState(commandRuns(parentEvents), childId, reply),
      holdExpired,
    };
  }

  /** bb merges another child's outcome into a pending notice without an event, so mail acts only while the row is unchanged. */
  async function settleCompletion(row: Row, childId: string, deadline: number, held: boolean): Promise<void> {
    const decision = decideCompletion(await completionFacts(row.threadId, childId, Date.now() >= deadline));
    const now = await currentRow(row);
    if (now === null) return;
    const target = { threadId: now.threadId, queuedMessageId: now.id };
    const note = `parent=${now.threadId} child=${childId} row=${now.id}`;
    if (now.updatedAt !== row.updatedAt) {
      if (held) await release(now);
      bb.log.info(`completion delivered: bb merged more outcomes into the notice ${note}`);
      return;
    }
    switch (decision.action) {
      case "deliver":
        if (held) await release(now);
        bb.log.info(`completion delivered ${note}`);
        return;
      case "drop":
        await bb.sdk.threads.queuedMessages.delete(target);
        bb.log.info(`completion dropped (${decision.reason}) ${note}`);
        return;
      case "shorten":
        await bb.sdk.threads.queuedMessages.delete(target);
        await bb.sdk.threads.send({
          threadId: now.threadId,
          mode: "auto",
          senderThreadId: childId,
          input: [{ type: "text", text: decision.text, mentions: [] }],
        });
        bb.log.info(`completion shortened ${note}`);
        return;
      case "hold": {
        const holding = held
          ? now
          : await bb.sdk.threads.queuedMessages.update({ ...target, expectedUpdatedAt: now.updatedAt, sendAt: deadline + RELEASE_MARGIN_MS });
        if (!held) bb.log.info(`completion held while the parent's bb thread wait runs ${note}`);
        setTimeout(() => void guard("completion hold", () => settleCompletion(holding, childId, deadline, true)), POLL_MS);
        return;
      }
    }
  }

  bb.events.on("message.queued", ({ entry }) =>
    guard("message.queued", async () => {
      const notice = classifyNotice(entry.systemNotice);
      switch (notice.kind) {
        case "other":
          return;
        case "reparent":
          await bb.sdk.threads.queuedMessages.delete({ threadId: entry.threadId, queuedMessageId: entry.id });
          bb.log.info(`reparent notice dropped parent=${entry.threadId} row=${entry.id}`);
          return;
        case "completion":
          await settleCompletion(entry, notice.childId, Date.now() + HOLD_LIMIT_MS, false);
          return;
      }
    }),
  );

  async function unarchivedThreads(): Promise<ListedThread[]> {
    const all: ListedThread[] = [];
    for (let offset = 0; ; offset += PAGE) {
      const page = await bb.sdk.threads.list({ archived: false, includeHidden: true, limit: PAGE, offset });
      all.push(...page);
      if (page.length < PAGE) return all;
    }
  }

  async function metadataOf(pluginId: string, threadIds: readonly string[]): Promise<Map<string, unknown>> {
    const result = new Map<string, unknown>();
    for (const chunk of chunks(threadIds, PAGE)) {
      const { threads } = await bb.sdk.threads.experimental_listPluginMetadata({ pluginId, threadIds: chunk });
      for (const { threadId, metadata } of threads) result.set(threadId, metadata);
    }
    return result;
  }

  async function candidates(): Promise<Candidate[]> {
    const threads = await unarchivedThreads();
    const ids = threads.map((thread) => thread.id);
    const [nest, mail] = await Promise.all([metadataOf(NEST_PLUGIN_ID, ids), metadataOf(bb.pluginId, ids)]);
    const parentOf = new Map(threads.map((thread) => [thread.id, nestLogicalParent(nest.get(thread.id)) ?? thread.parentThreadId]));
    return threads.map((thread) => ({
      id: thread.id,
      projectId: thread.projectId,
      environmentId: thread.environmentId,
      branch: thread.environmentBranchName ?? null,
      providerId: thread.providerId,
      status: thread.status,
      ancestors: logicalAncestors(thread.id, parentOf),
      tags: tagsOf(mail.get(thread.id)),
    }));
  }

  async function select(where: readonly string[], senderId: string | undefined): Promise<{ terms: Term[]; recipients: Recipients }> {
    const terms = usage(() => parseSelector(where));
    return { terms, recipients: chooseRecipients(await candidates(), terms, senderId) };
  }

  async function addressable(threadId: string, senderId: string | undefined): Promise<Thread> {
    const thread = await bb.sdk.threads.get({ threadId });
    if (thread.id === senderId) throw new PluginCliError("That is your own thread.", { code: "self" });
    if (thread.archivedAt !== null) throw new PluginCliError(`${thread.id} is archived.`, { code: "archived" });
    if (thread.status === "pending") {
      throw new PluginCliError(`${thread.id} has not sent its first message, as a held draft. Mail does not start it.`, { code: "draft" });
    }
    return thread;
  }

  async function readMessage(text: string | undefined, file: string | undefined, callerId: string | undefined, cwd: string | undefined): Promise<string> {
    if (file === undefined) {
      if (text === undefined || text.trim() === "") throw new PluginCliError("Give the message with --message or --message-file.", { code: "usage" });
      return text;
    }
    if (file === "-") {
      throw new PluginCliError("--message-file - is not supported, because plugin commands cannot read standard input.", {
        code: "usage",
        hint: "Read the message into a variable with read -r -d '' msg <<'EOF' and pass --message \"$msg\", or pass a file path.",
      });
    }
    const path = file.startsWith("/") ? file : cwd ? `${cwd.replace(/\/+$/, "")}/${file}` : null;
    if (path === null) throw new PluginCliError(`Cannot resolve ${file}. Pass an absolute path.`, { code: "usage" });
    if (!callerId) throw new PluginCliError("--message-file needs BB_THREAD_ID to know which machine to read from.", { code: "usage" });
    const caller = await bb.sdk.threads.get({ threadId: callerId });
    if (caller.environmentId === null) throw new PluginCliError(`${callerId} has no environment.`, { code: "no_environment" });
    const { hostId } = await bb.sdk.environments.get({ environmentId: caller.environmentId });
    const read = await bb.sdk.files.read({ hostId, path });
    const content = read.contentEncoding === "base64" ? Buffer.from(read.content, "base64").toString("utf8") : read.content;
    if (content.trim() === "") throw new PluginCliError(`${path} is empty.`, { code: "usage" });
    return content;
  }

  function skippedLine({ id, reason }: Recipients["skipped"][number]): string {
    return `${id}  skipped: ${reason === "sender" ? "the sender" : "held draft"}`;
  }

  async function changeTags(threadId: string, raw: readonly string[], change: "add" | "rm"): Promise<string[]> {
    const tags = usage(() => raw.map(parseTag));
    const keys = tags.map(tagKey);
    const metadata = await bb.sdk.threads.updatePluginMetadata(
      change === "add" ? { threadId, set: Object.fromEntries(keys.map((key) => [key, true])) } : { threadId, remove: keys },
    );
    return tagsOf(metadata);
  }

  const whereOption = {
    type: "string",
    repeatable: true,
    description:
      "Selector terms, all of which must match: project=, parent= (any logical ancestor, so it reaches every descendant), env=, branch=, provider=, status=, or a tag such as role=reviewer",
  } as const;

  bb.cli.register(
    defineCli({
      name: "mail",
      summary: "Message threads without waking them, or many threads at once",
      description:
        "bb mail send leaves the message in the recipient's inbox, which shows it when the recipient's next turn starts. Add --wake to start a turn now. Select recipients by thread id or with --where.",
      commands: {
        send: cliCommand({
          summary: "Send a message to one thread or to every thread a selector matches",
          positionals: [{ name: "thread", description: "Recipient thread id. Use --where instead to select many" }],
          options: {
            where: whereOption,
            wake: { type: "boolean", description: "Start the recipient's turn now. Without it the message waits for the recipient's next turn" },
            message: { type: "string", description: "Message text" },
            "message-file": { type: "string", description: "Read the message from this file on the calling machine" },
            json: { type: "boolean", description: "Print JSON" },
          },
          constraints: [{ kind: "exactly-one", options: ["message", "message-file"] }],
          async run({ options, positionals }, ctx) {
            const thread = positionals.thread as string | undefined;
            const where = (options.where as string[] | undefined) ?? [];
            if ((thread === undefined) === (where.length === 0)) {
              throw new PluginCliError("Name one recipient thread or pass --where, not both.", { code: "usage" });
            }
            const text = await readMessage(options.message as string | undefined, options["message-file"] as string | undefined, ctx.threadId, ctx.cwd);
            let ids: string[];
            let skipped: Recipients["skipped"] = [];
            let body = text;
            if (thread !== undefined) {
              ids = [(await addressable(thread, ctx.threadId)).id];
            } else {
              const { terms, recipients } = await select(where, ctx.threadId);
              ids = recipients.to.map(({ id }) => id);
              skipped = recipients.skipped;
              body = `[mail to ${describeTerms(terms)}]\n\n${text}`;
            }
            const wake = options.wake === true;
            const failed: Array<{ id: string; error: string }> = [];
            for (const id of ids) {
              try {
                await bb.sdk.threads.send({
                  threadId: id,
                  mode: "auto",
                  ...(ctx.threadId ? { senderThreadId: ctx.threadId } : {}),
                  ...(wake ? {} : { originPluginId: bb.pluginId }),
                  input: [{ type: "text", text: body, mentions: [] }],
                });
              } catch (error) {
                failed.push({ id, error: error instanceof Error ? error.message : String(error) });
              }
            }
            const sent = ids.filter((id) => !failed.some((failure) => failure.id === id));
            const delivery = wake ? "wake" : "inbox";
            const exitCode = failed.length > 0 ? 1 : 0;
            if (options.json) return { exitCode, stdout: JSON.stringify({ delivery, sent, skipped, failed }, null, 2) };
            const lines = [
              `Sent to ${sent.length} thread${sent.length === 1 ? "" : "s"} (${delivery}).`,
              ...sent,
              ...skipped.map(skippedLine),
              ...failed.map(({ id, error }) => `${id}  failed: ${error}`),
            ];
            return { exitCode, stdout: lines.join("\n") };
          },
        }),
        who: cliCommand({
          summary: "List the threads a selector reaches, without sending",
          options: { where: { ...whereOption, required: true }, json: { type: "boolean", description: "Print JSON" } },
          async run({ options }, ctx) {
            const { recipients } = await select(options.where as string[], ctx.threadId);
            if (options.json) {
              return { exitCode: 0, stdout: JSON.stringify({ to: recipients.to.map(({ id }) => id), skipped: recipients.skipped }, null, 2) };
            }
            const lines = [...recipients.to.map(({ id, status }) => `${id}  ${status}`), ...recipients.skipped.map(skippedLine)];
            return { exitCode: 0, stdout: lines.length > 0 ? lines.join("\n") : "No unarchived thread matches." };
          },
        }),
        "tag add": cliCommand({
          summary: "Add tags to a thread",
          positionals: [
            { name: "thread", description: "Thread id", required: true },
            { name: "tags", description: "Tags, as key=value or a bare word", variadic: true },
          ],
          async run({ positionals }) {
            const tags = await changeTags(positionals.thread as string, positionals.tags as string[], "add");
            return { exitCode: 0, stdout: tags.join(" ") };
          },
        }),
        "tag rm": cliCommand({
          summary: "Remove tags from a thread",
          positionals: [
            { name: "thread", description: "Thread id", required: true },
            { name: "tags", description: "Tags to remove", variadic: true },
          ],
          async run({ positionals }) {
            const tags = await changeTags(positionals.thread as string, positionals.tags as string[], "rm");
            return { exitCode: 0, stdout: tags.join(" ") };
          },
        }),
        "tag ls": cliCommand({
          summary: "List a thread's tags",
          positionals: [{ name: "thread", description: "Thread id. Defaults to BB_THREAD_ID" }],
          async run({ positionals }, ctx) {
            const threadId = (positionals.thread as string | undefined) ?? ctx.threadId;
            if (!threadId) throw new PluginCliError("Name a thread.", { code: "usage" });
            return { exitCode: 0, stdout: tagsOf(await bb.sdk.threads.getPluginMetadata({ threadId })).join(" ") };
          },
        }),
      },
    }),
  );
}

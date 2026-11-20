import { z } from "zod";

export class UsageError extends Error {}

export const FACT_KEYS = ["project", "parent", "env", "branch", "provider", "status"] as const;
export type FactKey = (typeof FACT_KEYS)[number];

const TAG_PATTERN = /^[A-Za-z0-9_.:/-]+(=[^\s=]+)?$/;

function isFactKey(key: string): key is FactKey {
  return (FACT_KEYS as readonly string[]).includes(key);
}

export function parseTag(raw: string): string {
  const tag = raw.trim();
  if (!TAG_PATTERN.test(tag)) {
    throw new UsageError(`Invalid tag "${raw}". Use key=value or a bare word of letters, digits, and . _ : / -`);
  }
  const key = tag.split("=")[0]!;
  if (isFactKey(key)) throw new UsageError(`"${key}" is a built-in selector, not a tag. Pick another key.`);
  return tag;
}

export type Term = { kind: "fact"; key: FactKey; value: string } | { kind: "tag"; tag: string };

export function parseSelector(values: readonly string[]): Term[] {
  const words = values.flatMap((value) => value.split(/\s+/)).filter((word) => word !== "");
  if (words.length === 0) throw new UsageError("--where needs at least one term, such as project=<id> or role=reviewer.");
  return words.map((word): Term => {
    const [key, ...rest] = word.split("=");
    if (key !== undefined && isFactKey(key)) {
      const value = rest.join("=");
      if (value === "") throw new UsageError(`${key}= needs a value.`);
      return { kind: "fact", key, value };
    }
    return { kind: "tag", tag: parseTag(word) };
  });
}

export interface Candidate {
  id: string;
  projectId: string;
  environmentId: string | null;
  branch: string | null;
  providerId: string;
  status: string;
  ancestors: readonly string[];
  tags: readonly string[];
}

const FACTS: Record<FactKey, (candidate: Candidate) => readonly (string | null)[]> = {
  project: (candidate) => [candidate.projectId],
  parent: (candidate) => candidate.ancestors,
  env: (candidate) => [candidate.environmentId],
  branch: (candidate) => [candidate.branch],
  provider: (candidate) => [candidate.providerId],
  status: (candidate) => [candidate.status],
};

export function matches(terms: readonly Term[], candidate: Candidate): boolean {
  return terms.every((term) =>
    term.kind === "tag" ? candidate.tags.includes(term.tag) : FACTS[term.key](candidate).includes(term.value),
  );
}

export type SkipReason = "sender" | "draft";

export interface Recipients {
  to: Candidate[];
  skipped: Array<{ id: string; reason: SkipReason }>;
}

export function chooseRecipients(candidates: readonly Candidate[], terms: readonly Term[], senderId: string | undefined): Recipients {
  const result: Recipients = { to: [], skipped: [] };
  for (const candidate of candidates) {
    if (!matches(terms, candidate)) continue;
    if (candidate.id === senderId) result.skipped.push({ id: candidate.id, reason: "sender" });
    else if (candidate.status === "pending") result.skipped.push({ id: candidate.id, reason: "draft" });
    else result.to.push(candidate);
  }
  return result;
}

export function logicalAncestors(threadId: string, parentOf: ReadonlyMap<string, string | null>): string[] {
  const ancestors: string[] = [];
  const seen = new Set([threadId]);
  let parent = parentOf.get(threadId) ?? null;
  while (parent !== null && !seen.has(parent)) {
    ancestors.push(parent);
    seen.add(parent);
    parent = parentOf.get(parent) ?? null;
  }
  return ancestors;
}

const TAG_KEY_PREFIX = "tag:";

export function tagKey(tag: string): string {
  return `${TAG_KEY_PREFIX}${tag}`;
}

export function tagsOf(metadata: unknown): string[] {
  if (typeof metadata !== "object" || metadata === null) return [];
  return Object.entries(metadata)
    .filter(([key, value]) => key.startsWith(TAG_KEY_PREFIX) && value === true)
    .map(([key]) => key.slice(TAG_KEY_PREFIX.length))
    .sort();
}

const nestMetadataSchema = z.object({ logicalParentThreadId: z.string().min(1) });

export function nestLogicalParent(metadata: unknown): string | null {
  const parsed = nestMetadataSchema.safeParse(metadata);
  return parsed.success ? parsed.data.logicalParentThreadId : null;
}

export const INBOX_REASON = "Mail inbox: delivered when this thread's next turn starts.";

export type DispatchDecision = { action: "proceed" } | { action: "wait"; reason: string };

export const INBOX_SUBMISSION = { kind: "inbox" } as const;

export interface DispatchFacts {
  attempt: "join-turn" | "start-turn";
  experimental_submission: { pluginId: string } | null;
  queuedMessages: ReadonlyArray<QueueRow>;
}

export interface QueueRow {
  id: string;
  waitingOn: { kind: string; pluginId?: string } | null;
}

export function heldByMail(row: QueueRow, mailPluginId: string): boolean {
  return row.waitingOn?.kind === "plugin" && row.waitingOn.pluginId === mailPluginId;
}

export interface InboxMemory {
  /** Rows mail held. bb passes the submission marker only on a message's first attempt, and a row released into a turn that ended first comes back without mail's wait. */
  held: ReadonlySet<string>;
  /** Held rows that were waiting when the recipient's current turn started, so they may join it. */
  releasable: ReadonlySet<string>;
}

export function inboxDecision(facts: DispatchFacts, mailPluginId: string, memory: InboxMemory): DispatchDecision {
  const waits = (row: QueueRow) =>
    (heldByMail(row, mailPluginId) || memory.held.has(row.id)) && !(facts.attempt === "join-turn" && memory.releasable.has(row.id));
  const inbox =
    facts.queuedMessages.length > 0 ? facts.queuedMessages.every(waits) : facts.experimental_submission?.pluginId === mailPluginId;
  return inbox ? { action: "wait", reason: INBOX_REASON } : { action: "proceed" };
}

const REPARENT_KINDS = new Set(["ownership-assigned", "ownership-removed", "ownership-batch"]);

const noticeSchema = z.object({
  kind: z.string(),
  subject: z
    .object({ kind: z.string(), threadId: z.string().optional(), outcomes: z.array(z.object({ threadId: z.string() })).optional() })
    .nullable()
    .optional(),
});

export type NoticeClass = { kind: "reparent" } | { kind: "completion"; childId: string } | { kind: "other" };

export function classifyNotice(systemNotice: unknown): NoticeClass {
  const parsed = noticeSchema.safeParse(systemNotice);
  if (!parsed.success) return { kind: "other" };
  const { kind, subject } = parsed.data;
  if (REPARENT_KINDS.has(kind)) return { kind: "reparent" };
  if (kind === "child-completed" && subject?.kind === "thread" && subject.threadId && subject.outcomes?.length === 1) {
    return { kind: "completion", childId: subject.threadId };
  }
  return { kind: "other" };
}

const itemSchema = z.object({
  type: z.string(),
  id: z.string(),
  command: z.string().optional(),
  exitCode: z.number().nullable().optional(),
  aggregatedOutput: z.string().nullable().optional(),
  arguments: z.object({ action: z.string().optional(), resume: z.boolean().optional() }).passthrough().optional().catch(undefined),
  result: z.string().nullable().optional().catch(undefined),
  presentation: z.object({ title: z.string().optional() }).passthrough().optional().catch(undefined),
});
const eventSchema = z.object({
  type: z.string(),
  createdAt: z.number().optional(),
  data: z.object({ item: itemSchema.optional() }).passthrough().nullable().optional(),
});
type Item = z.infer<typeof itemSchema>;

function parseEvent(raw: unknown): { type: string; createdAt: number | null; item: Item | null } | null {
  const parsed = eventSchema.safeParse(raw);
  return parsed.success ? { type: parsed.data.type, createdAt: parsed.data.createdAt ?? null, item: parsed.data.data?.item ?? null } : null;
}

export const TURN_EVENT_TYPES = ["turn/started", "item/completed", "thread/compacted"] as const;
export const COMMAND_EVENT_TYPES = ["item/started", "item/completed"] as const;

/** bb compacts in a turn of its own, which the self-compact helper can request before mail reads the events. */
export function lastTurnItems(eventsNewestFirst: readonly unknown[]): Item[] {
  let finished: Item[] = [];
  let compaction = false;
  for (const raw of eventsNewestFirst) {
    const event = parseEvent(raw);
    if (event === null) continue;
    if (event.type === "thread/compacted") compaction = true;
    else if (event.type === "item/completed" && event.item) finished.push(event.item);
    else if (event.type === "turn/started") {
      if (finished.length > 0 && !compaction) return finished;
      finished = [];
      compaction = false;
    }
  }
  return finished;
}

const SELF_COMPACT_RUN = /bb-compact\.mjs["']?\s+run\b/;
const HERMES_SCHEDULED = /\*\*status:\*\*\s*scheduled\b/;

/**
 * Claude Code runs the helper as a command. Hermes calls its self_compact tool, which only schedules the compaction.
 * With `resume: false` the child then waits for the user, so its completion is real.
 */
export function launchedSelfCompaction(items: readonly Item[]): boolean {
  return items.some((item) =>
    item.type === "commandExecution"
      ? item.exitCode === 0 && item.command !== undefined && SELF_COMPACT_RUN.test(item.command) && !item.command.includes("--no-resume")
      : item.type === "toolCall" &&
        item.presentation?.title === "self_compact" &&
        item.arguments?.action === "compact" &&
        item.arguments.resume !== false &&
        HERMES_SCHEDULED.test(item.result ?? ""),
  );
}

export function latestTurnStart(eventsNewestFirst: readonly unknown[]): number | null {
  for (const raw of eventsNewestFirst) {
    const event = parseEvent(raw);
    if (event?.type === "turn/started") return event.createdAt;
  }
  return null;
}

export interface FinishedCommand {
  command: string;
  exitCode: number | null;
}

export interface CommandRun extends FinishedCommand {
  running: boolean;
  output: string;
  endedAt: number | null;
}

export function commandRuns(eventsNewestFirst: readonly unknown[]): CommandRun[] {
  const runs = new Map<string, CommandRun>();
  for (const raw of eventsNewestFirst) {
    const event = parseEvent(raw);
    const item = event?.item;
    if (!item || item.type !== "commandExecution" || item.command === undefined) continue;
    const known = runs.get(item.id);
    if (event.type === "item/completed") {
      runs.set(item.id, { command: item.command, running: false, exitCode: item.exitCode ?? null, output: item.aggregatedOutput ?? "", endedAt: event.createdAt });
    } else if (event.type === "item/started" && known === undefined) {
      runs.set(item.id, { command: item.command, running: true, exitCode: null, output: "", endedAt: null });
    }
  }
  return [...runs.values()];
}

export type WaitState = "returned" | "running" | "not-returned";

function squash(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

const REPLY_PROBE_CHARS = 300;

/**
 * `bb thread wait` prints only a status line, so only a command that also prints the reply, such as
 * `bb thread wait <id> && bb thread output <id>`, returned the result. It returned this turn's result only if it
 * ended after the child's turn started.
 */
export function waitState(runsNewestFirst: readonly CommandRun[], childId: string, reply: string | null, childTurnStartedAt: number | null): WaitState {
  const wait = runsNewestFirst.find((run) => /\bbb thread wait\b/.test(run.command) && run.command.includes(childId));
  if (wait === undefined) return "not-returned";
  if (wait.running) return "running";
  const probe = squash(reply ?? "").slice(0, REPLY_PROBE_CHARS);
  const thisTurn = childTurnStartedAt !== null && wait.endedAt !== null && wait.endedAt >= childTurnStartedAt;
  return thisTurn && wait.exitCode === 0 && probe !== "" && squash(wait.output).includes(probe) ? "returned" : "not-returned";
}

export const BB_EXCERPT_LIMIT = 4000;
const FIRST_LINE_LIMIT = 200;

export function shortCompletion(childId: string, reply: string | null): string | null {
  const text = reply?.trim() ?? "";
  if (text.length <= BB_EXCERPT_LIMIT) return null;
  const firstLine = text.split("\n").find((line) => line.trim() !== "")!.trim();
  const clipped = firstLine.length > FIRST_LINE_LIMIT ? `${firstLine.slice(0, FIRST_LINE_LIMIT)}…` : firstLine;
  return `[mail] @thread:${childId} completed with a ${text.length.toLocaleString("en-US")}-character reply that starts "${clipped}". Read it with \`bb thread output ${childId}\`.`;
}

export type CompletionDecision =
  | { action: "deliver" }
  | { action: "drop"; reason: "self-compaction" | "wait-returned" }
  | { action: "hold" }
  | { action: "shorten"; text: string };

export interface CompletionFacts {
  childId: string;
  reply: string | null;
  compacting: boolean;
  wait: WaitState;
  holdExpired: boolean;
}

export function decideCompletion(facts: CompletionFacts): CompletionDecision {
  if (facts.compacting) return { action: "drop", reason: "self-compaction" };
  if (facts.wait === "returned") return { action: "drop", reason: "wait-returned" };
  if (facts.wait === "running" && !facts.holdExpired) return { action: "hold" };
  const text = shortCompletion(facts.childId, facts.reply);
  return text === null ? { action: "deliver" } : { action: "shorten", text };
}

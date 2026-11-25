import { z } from "zod";

export type EnvironmentChoice =
  | { kind: "project-default" }
  | { kind: "reuse"; environmentId: string }
  | { kind: "path"; path: string }
  | { kind: "new"; workspace: "personal" | "worktree"; baseBranch: string | null };

export type PromptSource = { kind: "text"; text: string } | { kind: "file"; path: string };

export interface SpawnFlags {
  project?: string;
  environment?: string;
  newEnvironment?: "personal" | "worktree";
  baseBranch?: string;
  provider?: string;
  model?: string;
  reasoningLevel?: string;
  title?: string;
  prompt?: string;
  promptFile?: string;
}

export class UsageError extends Error {
  constructor(message: string, readonly hint?: string) {
    super(message);
  }
}

export const STDIN_HINT =
  "bb plugin commands cannot read multi-line stdin. Read the brief into a variable first: " +
  "read -r -d '' brief <<'BRIEF' (brief lines) BRIEF, then run bb nest spawn ... --prompt \"$brief\". " +
  "Or pass a file with --prompt-file <path>.";

export function parseEnvironment(flags: SpawnFlags): EnvironmentChoice {
  const value = flags.environment?.trim();
  if (value && flags.newEnvironment) throw new UsageError("Choose only one of --environment and --new-environment.");
  if (flags.baseBranch?.trim() && flags.newEnvironment !== "worktree") {
    throw new UsageError("--base-branch requires --new-environment worktree.");
  }
  if (flags.newEnvironment) {
    return { kind: "new", workspace: flags.newEnvironment, baseBranch: flags.baseBranch?.trim() || null };
  }
  if (!value) return { kind: "project-default" };
  return value.includes("/") || value.startsWith("~") || value.startsWith(".")
    ? { kind: "path", path: value }
    : { kind: "reuse", environmentId: value };
}

export function parsePrompt(flags: SpawnFlags): PromptSource {
  if (flags.promptFile === "-") throw new UsageError("--prompt-file - is not supported.", STDIN_HINT);
  if (flags.promptFile !== undefined) return { kind: "file", path: flags.promptFile };
  if (flags.prompt === undefined || flags.prompt.trim() === "") {
    throw new UsageError("Give the brief with --prompt-file <path> or --prompt <text>.", STDIN_HINT);
  }
  return { kind: "text", text: flags.prompt };
}

export function resolvePath(path: string, cwd: string | undefined): string {
  if (path.startsWith("/")) return path;
  if (!cwd) throw new UsageError(`Cannot resolve the relative path ${path}. Pass an absolute path.`);
  return `${cwd.replace(/\/+$/, "")}/${path}`;
}

export interface ThreadLink {
  id: string;
  canSpawnChild: boolean;
}

export type Route =
  | { kind: "child"; parentThreadId: string }
  | { kind: "relay"; hostThreadId: string; logicalParentThreadId: string };

type Lineage = readonly [caller: ThreadLink, ...ancestors: ThreadLink[]];

export function chooseRoute(lineage: Lineage): Route {
  const [caller, ...ancestors] = lineage;
  if (caller.canSpawnChild) return { kind: "child", parentThreadId: caller.id };
  const host = ancestors.find((thread) => thread.canSpawnChild);
  if (!host) throw new Error(`No ancestor of ${caller.id} can take a child thread.`);
  return { kind: "relay", hostThreadId: host.id, logicalParentThreadId: caller.id };
}

const metadataSchema = z.object({ logicalParentThreadId: z.string().min(1) });
export type NestMetadata = z.infer<typeof metadataSchema>;

export function parseMetadata(value: unknown): NestMetadata | null {
  const parsed = metadataSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

export function preamble(route: Extract<Route, { kind: "relay" }>): string {
  const parent = `@thread:${route.logicalParentThreadId}`;
  const host = `@thread:${route.hostThreadId}`;
  return [
    `[nest] Your logical parent is ${parent}, which started you with \`bb nest spawn\`. bb allows only four thread levels, so you run under ${host}, and \`bb status\` shows that thread as your parent with notifications off.`,
    `Every turn you end is delivered to ${parent} automatically as your result, including failures and questions. Do not send results with \`bb thread tell\`, and never message ${host}. Start your own workers with \`bb nest spawn\`.`,
    "",
    "Brief:",
    "",
  ].join("\n");
}

export const RELAY_EXCERPT_LIMIT = 4000;
const FIRST_LINE_LIMIT = 200;

function replyText(workerId: string, reply: string | null): string {
  const text = reply?.trim();
  if (!text) return "No final output was recorded.";
  if (text.length <= RELAY_EXCERPT_LIMIT) return `Final reply:\n\n${text}`;
  const firstLine = text.split("\n").find((line) => line.trim() !== "")!.trim();
  const clipped = firstLine.length > FIRST_LINE_LIMIT ? `${firstLine.slice(0, FIRST_LINE_LIMIT)}…` : firstLine;
  return `Its ${text.length.toLocaleString("en-US")}-character reply starts "${clipped}". Read it with \`bb thread output ${workerId}\`.`;
}

export type Outcome =
  | { kind: "completed"; reply: string | null }
  | { kind: "failed"; error: string | null }
  | { kind: "waiting"; interactionId: string; interactionKind: string | null; questions: string[] };

const interactionPayloadSchema = z.object({
  kind: z.string(),
  questions: z.array(z.object({ prompt: z.string() })).optional(),
});

export function waitingOutcome(interaction: { id: string; payload: unknown }): Outcome {
  const payload = interactionPayloadSchema.safeParse(interaction.payload);
  return {
    kind: "waiting",
    interactionId: interaction.id,
    interactionKind: payload.success ? payload.data.kind.replaceAll("_", " ") : null,
    questions: payload.success ? (payload.data.questions ?? []).map(({ prompt }) => prompt) : [],
  };
}

export const NO_OP_MARKER = "[no-op]";

export const WORKER_INSTRUCTIONS = `Another thread started you as its worker, and each turn you end reaches it as your result. When you end a turn only to wait, for your own workers or for a background command, reply with exactly \`${NO_OP_MARKER}\`. Nest and Mail do not pass that reply on, and the result you wait for starts your next turn.`;

export function relayText(workerId: string, outcome: Outcome): string {
  const worker = `@thread:${workerId}`;
  const header = `[nest] Automatic report from your worker ${worker}. It needs no reply or acknowledgement.`;
  switch (outcome.kind) {
    case "completed":
      return `${header}\n\n${worker} completed a turn. ${replyText(workerId, outcome.reply)}`;
    case "failed":
      return `${header}\n\n${worker} failed${outcome.error?.trim() ? `: ${outcome.error.trim()}` : "."}\n\nReview it with \`bb thread log ${workerId}\` before deciding next steps.`;
    case "waiting": {
      const questions = outcome.questions.map((question) => `\n- ${question}`).join("");
      return `${header}\n\n${worker} is waiting on an interaction (${outcome.interactionKind ? `${outcome.interactionKind}, ` : ""}${outcome.interactionId}).${questions ? `\n${questions}` : ""}\n\nRead it with \`bb thread interactions show ${outcome.interactionId} ${workerId}\` and resolve it with the matching \`bb thread interactions\` command (answer, approve, grant, deny, or respond).`;
    }
  }
}

const TAG_PATTERN = /^[A-Za-z0-9_.:/-]+(=[^\s=]+)?$/;
const MAIL_SELECTOR_KEYS = new Set(["project", "parent", "env", "branch", "provider", "status"]);

export function mailTagKeys(tags: readonly string[]): Record<string, true> {
  const keys: Record<string, true> = {};
  for (const raw of tags) {
    const tag = raw.trim();
    if (!TAG_PATTERN.test(tag)) throw new UsageError(`Invalid tag "${raw}". Use key=value or a bare word of letters, digits, and . _ : / -`);
    if (MAIL_SELECTOR_KEYS.has(tag.split("=")[0]!)) throw new UsageError(`"${tag}" uses a built-in mail selector key. Pick another key.`);
    keys[`tag:${tag}`] = true;
  }
  return keys;
}

const itemSchema = z.object({
  type: z.string(),
  command: z.string().optional(),
  exitCode: z.number().nullable().optional(),
});
const eventSchema = z.object({
  type: z.string(),
  data: z.object({ item: itemSchema.optional() }).passthrough().nullable().optional(),
});

export const TURN_EVENT_TYPES = ["turn/started", "item/completed", "thread/compacted"] as const;
const SELF_COMPACT_RUN = /bb-compact\.mjs["']?\s+run\b/;

type Item = z.infer<typeof itemSchema>;

function launchedResumingSelfCompaction(item: Item): boolean {
  return (
    item.type === "commandExecution" &&
    item.exitCode === 0 &&
    item.command !== undefined &&
    SELF_COMPACT_RUN.test(item.command) &&
    !item.command.includes("--no-resume")
  );
}

export function endedToSelfCompact(eventsNewestFirst: readonly unknown[]): boolean {
  let launched = false;
  let items = 0;
  let compaction = false;
  for (const raw of eventsNewestFirst) {
    const parsed = eventSchema.safeParse(raw);
    if (!parsed.success) continue;
    const { type, data } = parsed.data;
    if (type === "thread/compacted") compaction = true;
    else if (type === "item/completed" && data?.item) {
      items += 1;
      if (launchedResumingSelfCompaction(data.item)) launched = true;
    } else if (type === "turn/started") {
      if (items > 0 && !compaction) break;
      launched = false;
      items = 0;
      compaction = false;
    }
  }
  return launched;
}

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

/**
 * `lineage` is the caller followed by its ancestors, nearest first. bb accepts a child only under a thread whose
 * `canSpawnChild` is true, so a caller that cannot take one borrows the nearest ancestor that can.
 */
export function chooseRoute(lineage: readonly ThreadLink[]): Route {
  const [caller, ...ancestors] = lineage;
  if (!caller) throw new Error("chooseRoute needs the caller thread");
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
    `Every turn you end is delivered to ${parent} automatically as your result, including failures and questions. Do not send results with \`bb thread tell\`, and never message ${host}. While you wait for your own workers, keep your turn open with \`bb thread wait\`, as a child whose parent notifications are auto does. Start your own workers with \`bb nest spawn\`.`,
    "",
    "Brief:",
    "",
  ].join("\n");
}

export const RELAY_EXCERPT_LIMIT = 4000;
const TRUNCATION_MARKER = "\n\n[... output truncated ...]";

function excerpt(text: string | null): string {
  const trimmed = text?.trim();
  if (!trimmed) return "No final output was recorded.";
  if (trimmed.length <= RELAY_EXCERPT_LIMIT) return trimmed;
  return `${trimmed.slice(0, RELAY_EXCERPT_LIMIT - TRUNCATION_MARKER.length).trimEnd()}${TRUNCATION_MARKER}`;
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

export function relayText(workerId: string, outcome: Outcome): string {
  const worker = `@thread:${workerId}`;
  const header = `[nest] Automatic report from your worker ${worker}. It needs no reply or acknowledgement.`;
  switch (outcome.kind) {
    case "completed":
      return `${header}\n\n${worker} completed a turn. Final reply:\n\n${excerpt(outcome.reply)}\n\nRead the whole reply with \`bb thread output ${workerId}\`.`;
    case "failed":
      return `${header}\n\n${worker} failed${outcome.error?.trim() ? `: ${outcome.error.trim()}` : "."}\n\nReview it with \`bb thread log ${workerId}\` before deciding next steps.`;
    case "waiting": {
      const questions = outcome.questions.map((question) => `\n- ${question}`).join("");
      return `${header}\n\n${worker} is waiting on an interaction (${outcome.interactionKind ? `${outcome.interactionKind}, ` : ""}${outcome.interactionId}).${questions ? `\n${questions}` : ""}\n\nRead it with \`bb thread interactions show ${outcome.interactionId} ${workerId}\` and resolve it with the matching \`bb thread interactions\` command (answer, approve, grant, deny, or respond).`;
    }
  }
}

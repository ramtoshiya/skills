export type MoveResult =
  | { kind: "moved"; tools: string[] }
  | { kind: "nothing" }
  | { kind: "refused"; tools: string[] }
  | { kind: "no-session" };

export function describeResult(result: MoveResult): string {
  switch (result.kind) {
    case "moved":
      return `Moved to the background: ${result.tools.join(", ")}`;
    case "nothing":
      return "Nothing to move. No command is running.";
    case "refused":
      return `Only a running Bash command can move to the background, and ${result.tools.join(", ")} is running.`;
    case "no-session":
      return "No Claude Code session of this thread answered. Check that the background-tools Claude Code plugin is installed and enabled.";
    default: {
      const exhaustive: never = result;
      return exhaustive;
    }
  }
}

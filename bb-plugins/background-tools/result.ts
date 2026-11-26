export type MovedTask = { taskId: string; description: string };

export type MoveResult =
  | { kind: "moved"; tasks: MovedTask[] }
  | { kind: "nothing" }
  | { kind: "no-session" };

export function describeResult(result: MoveResult): string {
  switch (result.kind) {
    case "moved":
      return `Moved to the background: ${result.tasks.map((task) => task.description || task.taskId).join(", ")}`;
    case "nothing":
      return "Nothing to move. A command can be moved once it has run for a few seconds.";
    case "no-session":
      return "Cannot reach a Claude Code process for this thread. If the thread was running before the plugin was installed, run `bb thread stop <thread-id>`, then send the next message.";
    default: {
      const exhaustive: never = result;
      return exhaustive;
    }
  }
}

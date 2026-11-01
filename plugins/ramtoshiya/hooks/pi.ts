import { execFile } from "node:child_process";
import { appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type {
	AgentBeforeSettleEventResult,
	ExtensionAPI,
	ToolCallEventResult,
} from "@earendil-works/pi-coding-agent";

const packageGuardScript = fileURLToPath(new URL("./global-package-guard.py", import.meta.url));
const gitHygieneScript = fileURLToPath(new URL("./git-hygiene-guard.py", import.meta.url));
const runner = [
	"run", "--offline", "--no-project", "--managed-python", "--python", ">=3.11",
	"--no-config", "--exclude-newer", "3 days", "python",
];
const unavailable: ToolCallEventResult = {
	block: true,
	reason:
		"Package/Python guard could not verify this command. Check uv, a cached uv-managed Python >=3.11, " +
		"and the guard source. The command was not executed.",
};

// Guard output past maxBuffer kills the child, so the buffer is the 1 GiB hard
// limit. Output past the soft limit is still used and logged, because Pi's
// terminal UI does not keep extension stderr. commit-trailer-guard.py writes the
// same log.
export const hardLimit = 1024 ** 3;

export function sizeWarningLog() {
	return join(process.env.XDG_STATE_HOME || join(homedir(), ".local/state"), "ramtoshiya", "size-warnings.log");
}

export function checkSize(name: string, bytes: number, softLimit: number) {
	if (bytes <= softLimit) return;
	try {
		const log = sizeWarningLog();
		mkdirSync(dirname(log), { recursive: true });
		appendFileSync(log, `${new Date().toISOString()} warning: ${name} is ${bytes} bytes, over the soft limit of ${softLimit} bytes\n`);
	} catch {
		// A log failure must not change the guard decision.
	}
}

export default function hooks(pi: ExtensionAPI) {
	packageGuard(pi);
	gitHygieneGuard(pi);
}

function packageGuard(pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "bash") return;

		// Normalize Pi's event to the existing hook protocol. Never execute the proposed command.
		const payload = JSON.stringify({ tool_name: "Bash", tool_input: event.input, cwd: ctx.cwd });
		return new Promise<ToolCallEventResult | undefined>((resolve) => {
			const child = execFile(
				"uv",
				[...runner, packageGuardScript],
				{ cwd: ctx.cwd, signal: ctx.signal, timeout: 5_000, maxBuffer: hardLimit, encoding: "utf8" },
				(error, stdout) => {
					if (error) return resolve({ ...unavailable });
					checkSize("Pi package guard output", Buffer.byteLength(stdout), 64 * 1024);
					if (!stdout.trim()) return resolve(undefined);
					try {
						const output = JSON.parse(stdout).hookSpecificOutput;
						if (
							output?.permissionDecision !== "deny" ||
							typeof output.permissionDecisionReason !== "string" ||
							!output.permissionDecisionReason.trim()
						) {
							return resolve({ ...unavailable });
						}
						resolve({ block: true, reason: output.permissionDecisionReason });
					} catch {
						resolve({ ...unavailable });
					}
				},
			);
			child.stdin?.on("error", () => {
				child.kill();
				resolve({ ...unavailable });
			});
			child.stdin?.end(payload);
		});
	});
}

function gitHygieneGuard(pi: ExtensionAPI) {
	// Pi has no stop_hook_active. One warning per run plays that role: the
	// continuation requested here stays in the same run, and agent_settled ends it.
	let warned = false;
	pi.on("agent_settled", () => {
		warned = false;
	});
	pi.on("agent_before_settle", async (event, ctx) => {
		if (warned || event.outcome !== "completed") return;
		const reason = await stopReason(ctx.cwd, ctx.signal);
		if (!reason) return;
		warned = true;
		const result: AgentBeforeSettleEventResult = {
			entries: [{ type: "custom_message", customType: "git-hygiene", content: reason, display: true }],
			continue: true,
		};
		return result;
	});
}

// Any failure allows the stop, matching the Claude/Codex hook.
function stopReason(cwd: string, signal: AbortSignal | undefined) {
	const payload = JSON.stringify({ hook_event_name: "Stop", cwd, stop_hook_active: false });
	return new Promise<string | undefined>((resolve) => {
		const child = execFile(
			"uv",
			[...runner, gitHygieneScript],
			{ cwd, signal, timeout: 10_000, maxBuffer: hardLimit, encoding: "utf8" },
			(error, stdout) => {
				if (error || !stdout.trim()) return resolve(undefined);
				checkSize("Pi Git hygiene guard output", Buffer.byteLength(stdout), 256 * 1024);
				try {
					const output = JSON.parse(stdout);
					const blocked = output?.decision === "block" && typeof output.reason === "string" && output.reason.trim();
					resolve(blocked ? output.reason : undefined);
				} catch {
					resolve(undefined);
				}
			},
		);
		child.stdin?.on("error", () => {
			child.kill();
			resolve(undefined);
		});
		child.stdin?.end(payload);
	});
}

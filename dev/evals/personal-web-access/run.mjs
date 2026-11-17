import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const [outputPath, ...selected] = process.argv.slice(2);
const launchers = {
	claude: (prompt) => ["claude", ["-p", "--tools", "", "--no-session-persistence", prompt]],
	codex: (prompt, cwd, reply) => ["codex", ["exec", "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check", "-C", cwd, "-o", reply, prompt]],
};
const hosts = selected.length ? selected : Object.keys(launchers);
if (!outputPath || hosts.some((host) => !launchers[host])) {
	console.error("Usage: node dev/evals/personal-web-access/run.mjs <new-output-directory> [claude] [codex]");
	process.exit(2);
}
const output = resolve(outputPath);
if (existsSync(output)) {
	console.error(`${output} already exists. Pass a new directory so earlier replies are not mixed in.`);
	process.exit(2);
}
const suite = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "cases.json"), "utf8"));
const frame = "This is a planning evaluation. Do not run commands, edit files, or start servers. "
	+ "Answer as you would before doing the work: the exact addresses each listener binds and how you obtain them, "
	+ "the commands you would run to start and verify it, and what you would tell me at the end.\n\nRequest: ";

function launch(host, item) {
	const cwd = join(output, host, item.id);
	mkdirSync(cwd, { recursive: true });
	const reply = join(cwd, "reply.md");
	const [command, args] = launchers[host](frame + item.request, cwd, reply);
	const env = { ...process.env };
	delete env.CLAUDECODE;
	return new Promise((done) => {
		const child = spawn(command, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
		let stdout = "";
		let stderr = "";
		child.stdout.on("data", (chunk) => { stdout += chunk; });
		child.stderr.on("data", (chunk) => { stderr += chunk; });
		const timer = setTimeout(() => child.kill(), 300_000);
		child.on("close", (code) => {
			clearTimeout(timer);
			if (host === "claude") writeFileSync(reply, stdout);
			if (code) writeFileSync(join(cwd, "stderr.txt"), stderr);
			done({ host, id: item.id, expected: item.expected, exit: code, reply });
		});
	});
}

const results = await Promise.all(hosts.flatMap((host) => suite.evals.map((item) => launch(host, item))));
writeFileSync(join(output, "results.json"), `${JSON.stringify(results, null, 2)}\n`);
for (const row of results) console.log(`${row.host}\t${row.id}\texpected=${row.expected}\texit=${row.exit}\t${row.reply}`);

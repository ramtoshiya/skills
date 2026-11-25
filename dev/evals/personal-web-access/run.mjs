import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const [outputPath, ...extra] = process.argv.slice(2);
if (!outputPath || extra.length) {
	console.error("Usage: node dev/evals/personal-web-access/run.mjs <new-output-directory>");
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

function launch(item) {
	const cwd = join(output, item.id);
	mkdirSync(cwd, { recursive: true });
	const reply = join(cwd, "reply.md");
	const args = ["-p", "--tools", "", "--no-session-persistence", frame + item.request];
	const env = { ...process.env };
	delete env.CLAUDECODE;
	return new Promise((done) => {
		const child = spawn("claude", args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
		let stdout = "";
		let stderr = "";
		child.stdout.on("data", (chunk) => { stdout += chunk; });
		child.stderr.on("data", (chunk) => { stderr += chunk; });
		const timer = setTimeout(() => child.kill(), 300_000);
		child.on("close", (code) => {
			clearTimeout(timer);
			writeFileSync(reply, stdout);
			if (code) writeFileSync(join(cwd, "stderr.txt"), stderr);
			done({ id: item.id, expected: item.expected, exit: code, reply });
		});
	});
}

const results = await Promise.all(suite.evals.map(launch));
writeFileSync(join(output, "results.json"), `${JSON.stringify(results, null, 2)}\n`);
for (const row of results) console.log(`${row.id}\texpected=${row.expected}\texit=${row.exit}\t${row.reply}`);

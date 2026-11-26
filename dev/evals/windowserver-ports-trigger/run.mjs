import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";

const usage = "Usage: node dev/evals/windowserver-ports-trigger/run.mjs <new-output-directory> [--plugin-dir <ramtoshiya plugin dir>] [--runs N]";
const { values, positionals } = parseArgs({
	allowPositionals: true,
	options: { "plugin-dir": { type: "string" }, runs: { type: "string", default: "3" } },
});
if (positionals.length !== 1) {
	console.error(usage);
	process.exit(2);
}
const output = resolve(positionals[0]);
if (existsSync(output)) {
	console.error(`${output} already exists. Pass a new directory so earlier runs are not mixed in.`);
	process.exit(2);
}
const runs = Number(values.runs);
const suite = JSON.parse(readFileSync(join(dirname(fileURLToPath(import.meta.url)), "cases.json"), "utf8"));
const pluginArgs = values["plugin-dir"]
	? ["--settings", JSON.stringify({ enabledPlugins: { "ramtoshiya@ramtoshiya": false } }), "--plugin-dir", resolve(values["plugin-dir"])]
	: [];

function calledSkill(transcript) {
	return transcript.split("\n").some((line) => {
		if (!line.startsWith("{")) return false;
		const content = JSON.parse(line).message?.content;
		return Array.isArray(content) && content.some((part) =>
			part.type === "tool_use" && part.name === "Skill" && /(^|:)windowserver-ports$/.test(part.input?.skill ?? ""));
	});
}

function launch(item, run) {
	const cwd = join(output, `${item.id}-${run}`);
	mkdirSync(cwd, { recursive: true });
	const args = ["-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
		"--tools", "Skill,Read,Grep,Glob", "--max-turns", "6", ...pluginArgs, item.request];
	const env = { ...process.env };
	delete env.CLAUDECODE;
	return new Promise((done) => {
		const child = spawn("claude", args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
		let stdout = "";
		child.stdout.on("data", (chunk) => { stdout += chunk; });
		const timer = setTimeout(() => child.kill(), 300_000);
		child.on("close", (exit) => {
			clearTimeout(timer);
			writeFileSync(join(cwd, "transcript.jsonl"), stdout);
			const called = calledSkill(stdout);
			done({ id: item.id, run, expected: item.expected, called, pass: called === item.expected, exit });
		});
	});
}

const results = await Promise.all(suite.evals.flatMap((item) =>
	Array.from({ length: runs }, (_, run) => launch(item, run + 1))));
writeFileSync(join(output, "results.json"), `${JSON.stringify(results, null, 2)}\n`);
for (const item of suite.evals) {
	const rows = results.filter((row) => row.id === item.id);
	const passed = rows.filter((row) => row.pass).length;
	console.log(`${item.id}\texpected=${item.expected}\tpassed ${passed}/${rows.length}\texits=${rows.map((row) => row.exit).join(",")}`);
}

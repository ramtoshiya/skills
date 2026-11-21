import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

const [skillPath, outputPath, configuration = "with_skill"] = process.argv.slice(2);
if (!skillPath || !outputPath || !["with_skill", "old_skill"].includes(configuration)) {
	console.error("Usage: node dev/evals/wjrj-skill/run.mjs <SKILL.md> <new-output-directory> [with_skill|old_skill]");
	process.exit(2);
}

const skillDir = dirname(resolve(skillPath));
const suite = JSON.parse(readFileSync(join(skillDir, "evals/evals.json"), "utf8"));
const references = join(skillDir, "references");
const skill = [readFileSync(resolve(skillPath), "utf8"),
	...(existsSync(references) ? readdirSync(references).filter(name => name.endsWith(".md")).sort() : [])
		.map(name => `File references/${name}:\n${readFileSync(join(references, name), "utf8")}`)].join("\n\n");
const output = resolve(outputPath);
if (existsSync(output)) {
	console.error(`${output} already exists. Pass a new directory so earlier results are not mixed in.`);
	process.exit(2);
}
const results = [];
for (const item of suite.evals) {
	const runPath = join(output, `eval-${item.id}-${item.name}`, configuration, "run-1");
	mkdirSync(join(runPath, "outputs"), { recursive: true });
	const save = (path, value) => writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, { flag: "wx" });
	save(join(runPath, "../../eval_metadata.json"), {
		eval_id: item.id, eval_name: item.name, prompt: item.prompt,
		assertions: Object.entries(item.expected).map(([key, value]) => `${key} = ${JSON.stringify(value)}`),
	});
	const prompt = `You are evaluating a skill in an offline simulation. Follow the supplied skill, then decide the next action for the user request using the simulated tool state. Do not execute commands, access boards, or create actual deliverables. Return the requested structured decision. Explain the decision in ordinary language.\n\nSkill:\n${skill}\n\nRequest and simulated state:\n${item.prompt}`;
	const env = { ...process.env };
	delete env.CLAUDECODE;
	const started = performance.now();
	const child = spawnSync("claude", [
		"-p", "--tools", "", "--disable-slash-commands", "--no-session-persistence",
		"--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
		"--output-format", "json", "--json-schema", JSON.stringify(suite.decision_schema), prompt,
	], { env, cwd: output, encoding: "utf8", timeout: 120_000, maxBuffer: 4 * 1024 * 1024 });
	const duration = performance.now() - started;
	writeFileSync(join(runPath, "response.json"), child.stdout || "", { flag: "wx" });
	if (child.error || child.status !== 0) {
		throw new Error(`Evaluation ${item.name} failed: ${child.error?.message || child.stderr || child.stdout}`);
	}
	const response = JSON.parse(child.stdout);
	if (response.is_error) throw new Error(`Model error: ${response.result}`);
	const decision = response.structured_output;
	if (!decision) throw new Error(`No structured decision for ${item.name}`);
	save(join(runPath, "outputs/decision.json"), decision);
	save(join(runPath, "timing.json"), {
		total_tokens: (response.usage?.input_tokens || 0) + (response.usage?.output_tokens || 0) + (response.usage?.cache_read_input_tokens || 0) + (response.usage?.cache_creation_input_tokens || 0),
		duration_ms: duration,
		total_duration_seconds: duration / 1000,
	});
	const expectations = Object.entries(item.expected).map(([key, value]) => ({
		text: `${key} = ${JSON.stringify(value)}`,
		passed: decision[key] === value,
		evidence: `Observed ${key} = ${JSON.stringify(decision[key])}. ${decision.explanation}`,
	}));
	const passed = expectations.filter(item => item.passed).length;
	const summary = { passed, failed: expectations.length - passed, total: expectations.length, pass_rate: passed / expectations.length };
	save(join(runPath, "grading.json"), { expectations, summary });
	results.push({ name: item.name, ...summary });
	console.log(`${configuration} ${item.name}: ${passed}/${expectations.length}`);
}
writeFileSync(join(output, `${configuration}-summary.json`), `${JSON.stringify(results, null, 2)}\n`, { flag: "wx" });
if (results.some(item => item.failed)) process.exitCode = 1;

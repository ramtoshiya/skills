import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const [skillPath, outputPath, configuration = "with_skill"] = process.argv.slice(2);
if (!skillPath || !outputPath || !["with_skill", "old_skill"].includes(configuration)) {
	console.error("Usage: node test/excalidraw-skill-eval.mjs <SKILL.md> <new-output-directory> [with_skill|old_skill]");
	process.exit(2);
}

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const suite = JSON.parse(readFileSync(join(root, "plugins/ramtoshiya/skills/excalidraw-board/evals/evals.json"), "utf8"));
const skill = readFileSync(resolve(skillPath), "utf8");
const output = resolve(outputPath);
const schema = {
	type: "object",
	properties: {
		primary_delivery: { type: "string", enum: ["shared_room", "file"], description: "The kind of artifact the user requested, even if delivery is blocked." },
		next_action: { type: "string", enum: ["report", "report_mismatch", "clarify_room", "export_file", "export_png", "report_missing_tool", "write_room"] },
		export_method: { type: "string", enum: ["none", "excalidraw-web-export", "browser_ui"] },
		install_tool: { type: "boolean" },
		create_file: { type: "boolean" },
		claim_saved_content_present: { type: "boolean" },
		claim_live_delivery: { type: "boolean" },
		publish_secret_link: { type: "boolean" },
		explanation: { type: "string" },
	},
	required: ["primary_delivery", "next_action", "export_method", "install_tool", "create_file", "claim_saved_content_present", "claim_live_delivery", "publish_secret_link", "explanation"],
	additionalProperties: false,
};
const results = [];
for (const item of suite.evals) {
	const casePath = join(output, `eval-${item.id}-${item.name}`);
	const runPath = join(casePath, configuration, "run-1");
	mkdirSync(join(runPath, "outputs"), { recursive: true });
	const save = (path, value) => writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`, { flag: "wx" });
	const metadataPath = join(casePath, "eval_metadata.json");
	const metadata = {
		eval_id: item.id, eval_name: item.name, prompt: item.prompt,
		assertions: Object.entries(item.expected).map(([key, value]) => `${key} = ${JSON.stringify(value)}`),
	};
	try {
		save(metadataPath, metadata);
	} catch (error) {
		if (error.code !== "EEXIST") throw error;
		if (readFileSync(metadataPath, "utf8") !== `${JSON.stringify(metadata, null, 2)}\n`) throw new Error("Existing evaluation metadata differs");
	}
	const prompt = `You are evaluating a skill in an offline simulation. Follow the supplied skill, then decide the next action for the user request using the simulated tool state. Do not execute commands, access rooms, or create actual deliverables. Return the requested structured decision. claim_saved_content_present means the intended drawing is confirmed present in the latest read, not just that a historical save succeeded. Explain the decision in ordinary language.\n\nSkill:\n${skill}\n\nRequest and simulated state:\n${item.prompt}`;
	const env = { ...process.env };
	delete env.CLAUDECODE;
	const started = performance.now();
	const child = spawnSync("claude", [
		"-p", "--tools", "", "--disable-slash-commands", "--no-session-persistence",
		"--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
		"--output-format", "json", "--json-schema", JSON.stringify(schema), prompt,
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

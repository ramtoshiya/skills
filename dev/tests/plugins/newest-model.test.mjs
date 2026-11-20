import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(
	new URL("../../../plugins/ramtoshiya/skills/worker-routing/scripts/newest-model", import.meta.url),
);

function run(args, slugs) {
	const home = mkdtempSync(join(tmpdir(), "newest-model-"));
	try {
		const models = slugs.map(([slug, visibility]) => ({ slug, visibility }));
		writeFileSync(join(home, "models_cache.json"), JSON.stringify({ models }));
		return spawnSync(script, args, { encoding: "utf8", env: { ...process.env, CODEX_HOME: home } });
	} finally {
		rmSync(home, { recursive: true, force: true });
	}
}

const catalog = [
	["gpt-5.6-sol", "list"],
	["gpt-6-sol", "list"],
	["gpt-6.1-sol", "list"],
	["gpt-10-sol", "list"],
	["gpt-9.9-sol", "list"],
	["gpt-11-sol", "hide"],
	["gpt-12-sol[1m]", "list"],
	["gpt-6.1-terra", "list"],
	["gpt-7-astra", "list"],
];

test("picks the highest version of the family and skips hidden and variant IDs", () => {
	const result = run(["sol"], catalog);
	assert.equal(result.status, 0, result.stderr);
	assert.equal(result.stdout, "gpt-10-sol\n");
});

test("does not substitute another family for a missing one", () => {
	const result = run(["luna"], catalog);
	assert.equal(result.status, 1);
	assert.equal(result.stdout, "");
});

test("prints the Claude family alias, which resolves to the newest model", () => {
	const result = run(["fable"], []);
	assert.equal(result.status, 0);
	assert.equal(result.stdout, "fable\n");
});

test("refuses a Claude family on claudex, where the aliases select GPT", () => {
	const result = run(["opus", "claudex"], []);
	assert.equal(result.status, 2);
	assert.equal(result.stdout, "");
});

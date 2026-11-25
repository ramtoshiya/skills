import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(
	new URL("../../../plugins/ramtoshiya/skills/worker-routing/scripts/newest-model", import.meta.url),
);

function run(args, ids) {
	const bin = mkdtempSync(join(tmpdir(), "newest-model-"));
	try {
		const listing = JSON.stringify(ids.map((id) => ({ id })));
		const bb = join(bin, "bb");
		writeFileSync(bb, `#!/bin/sh\n[ "$*" = "provider models claudex --json" ] || exit 9\nprintf '%s\\n' '${listing}'\n`);
		chmodSync(bb, 0o755);
		const PATH = `${bin}${delimiter}${process.env.PATH}`;
		return spawnSync(script, args, { encoding: "utf8", env: { ...process.env, PATH } });
	} finally {
		rmSync(bin, { recursive: true, force: true });
	}
}

const catalog = [
	"gpt-5.6-sol",
	"gpt-6-sol",
	"gpt-6.1-sol",
	"gpt-10-sol",
	"gpt-9.9-sol",
	"gpt-12-sol[1m]",
	"gpt-6.1-terra",
	"gpt-7-astra",
];

test("picks the highest version of the family and skips variant IDs", () => {
	const result = run(["sol"], catalog);
	assert.equal(result.status, 0, result.stderr);
	assert.equal(result.stdout, "gpt-10-sol\n");
});

test("does not substitute another family for a missing one", () => {
	const result = run(["luna", "claudex"], catalog);
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

test("refuses a GPT family on a provider other than claudex", () => {
	const result = run(["sol", "codex"], catalog);
	assert.equal(result.status, 2);
	assert.equal(result.stdout, "");
});

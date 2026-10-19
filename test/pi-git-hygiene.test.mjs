import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import hooks from "../plugins/ramtoshiya/hooks/pi.ts";

const handlers = {};
hooks({ on(event, callback) { handlers[event] = callback; } });

const settle = (cwd, outcome = "completed") =>
	handlers.agent_before_settle({ type: "agent_before_settle", outcome, entries: [], continue: false }, { cwd });
const settled = () => handlers.agent_settled({ type: "agent_settled", aborted: false }, {});

function repository(t) {
	const cwd = realpathSync(mkdtempSync(join(tmpdir(), "pi-git-hygiene-")));
	t.after(async () => {
		await settled();
		rmSync(cwd, { recursive: true, force: true });
	});
	execFileSync("git", ["init", "-q"], { cwd });
	return cwd;
}

test("asks for one continuation per run while the repository is dirty", async (t) => {
	const cwd = repository(t);
	assert.equal(await settle(cwd), undefined);
	writeFileSync(join(cwd, "new.txt"), "new\n");

	const result = await settle(cwd);
	assert.equal(result.continue, true);
	assert.equal(result.entries.length, 1);
	assert.equal(result.entries[0].type, "custom_message");
	assert.match(result.entries[0].content, /has uncommitted changes:\n\?\? new\.txt/);

	assert.equal(await settle(cwd), undefined);
	await settled();
	assert.equal((await settle(cwd)).continue, true);
});

test("does not check runs that were aborted or failed", async (t) => {
	const cwd = repository(t);
	writeFileSync(join(cwd, "new.txt"), "new\n");
	assert.equal(await settle(cwd, "aborted"), undefined);
	assert.equal(await settle(cwd, "error"), undefined);
});

test("allows the stop when uv is missing, fails, or returns unexpected output", async (t) => {
	const cwd = repository(t);
	writeFileSync(join(cwd, "new.txt"), "new\n");
	const originalPath = process.env.PATH;
	t.after(() => { process.env.PATH = originalPath; });
	process.env.PATH = join(cwd, "bin-missing");
	assert.equal(await settle(cwd), undefined);
	process.env.PATH = cwd;
	for (const script of [
		"#!/bin/sh\n/bin/cat >/dev/null\nexit 1\n",
		"#!/bin/sh\n/bin/cat >/dev/null\nprintf '%s' 'not JSON'\n",
		"#!/bin/sh\n/bin/cat >/dev/null\nprintf '%s' '{\"decision\":\"block\"}'\n",
	]) {
		writeFileSync(join(cwd, "uv"), script, { mode: 0o755 });
		assert.equal(await settle(cwd), undefined);
	}
});

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import packageGuard from "../plugins/ramtoshiya/hooks/pi.ts";

let handler;
packageGuard({ on(event, callback) { if (event === "tool_call") handler = callback; } });

function fixture(t) {
	const cwd = mkdtempSync(join(tmpdir(), "pi-package-guard-"));
	t.after(() => rmSync(cwd, { recursive: true, force: true }));
	return cwd;
}

function call(cwd, command, signal) {
	return handler(
		{ type: "tool_call", toolName: "bash", toolCallId: "guard-test", input: { command } },
		{ cwd, signal },
	);
}

// Runtime provisioning is a prerequisite, not a simulated policy denial.
execFileSync("uv", [
	"run", "--offline", "--no-project", "--managed-python", "--python", ">=3.11",
	"--no-config", "--exclude-newer", "3 days", "python", "-V",
]);

test("translates real guard denials and allows harmless command text without executing it", async (t) => {
	const cwd = fixture(t);
	const denial = await call(cwd, "hf download publisher/model");
	assert.equal(denial.block, true);
	assert.match(denial.reason, /40-character commit hash/);
	assert.equal(await call(cwd, `hf download publisher/model --revision ${"a".repeat(40)}`), undefined);
	assert.equal(await call(cwd, "touch should-not-exist"), undefined);
	assert.equal(existsSync(join(cwd, "should-not-exist")), false);
});

test("resolves project policy against the event working directory", async (t) => {
	const cwd = fixture(t);
	writeFileSync(join(cwd, ".npmrc"), "min-release-age=0\n");
	const denial = await call(cwd, "npm install --min-release-age=3");
	assert.equal(denial.block, true);
	assert.match(denial.reason, /Release-age overrides/);
});

test("does not apply shell policy to other tools", async () => {
	assert.equal(await handler(
		{ type: "tool_call", toolName: "read", toolCallId: "read-test", input: { path: "python3" } },
		{},
	), undefined);
});

test("blocks when uv is missing, fails, or returns unexpected output", async (t) => {
	const cwd = fixture(t);
	const originalPath = process.env.PATH;
	t.after(() => { process.env.PATH = originalPath; });
	process.env.PATH = cwd;
	for (const script of [
		null,
		"#!/bin/sh\n/bin/cat >/dev/null\nexit 1\n",
		"#!/bin/sh\n/bin/cat >/dev/null\nprintf '%s' 'not JSON'\n",
		"#!/bin/sh\n/bin/cat >/dev/null\nprintf '%s' '{}'\n",
		"#!/bin/sh\n/bin/cat >/dev/null\nprintf '%s' '{\"hookSpecificOutput\":{\"permissionDecision\":\"deny\"}}'\n",
	]) {
		if (script !== null) writeFileSync(join(cwd, "uv"), script, { mode: 0o755 });
		const denial = await call(cwd, "git status");
		assert.equal(denial.block, true);
		assert.match(denial.reason, /could not verify/);
	}
});

test("cancellation cannot become permission to execute", async (t) => {
	const cwd = fixture(t);
	const controller = new AbortController();
	controller.abort();
	const denial = await call(cwd, "git status", controller.signal);
	assert.equal(denial.block, true);
	assert.match(denial.reason, /could not verify/);
});

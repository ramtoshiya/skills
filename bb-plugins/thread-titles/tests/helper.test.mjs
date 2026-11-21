import assert from "node:assert/strict";
import { chmodSync, existsSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { buildHelper, createHelperService, runHelper } from "../helper.js";
import { SWIFT_SOURCE } from "../swift-source.js";

function scratch() {
  return mkdtempSync(join(tmpdir(), "thread-titles-"));
}

function fakeHelper(directory, body) {
  const path = join(directory, "fake-helper");
  writeFileSync(path, `#!/bin/sh\n${body}\n`);
  chmodSync(path, 0o755);
  return path;
}

test("runHelper sends the prompt on stdin and parses the last stdout line", async () => {
  const directory = scratch();
  try {
    const path = fakeHelper(directory, 'echo noise\nprintf \'{"ok":true,"text":"%s:%s"}\\n\' "$1" "$(cat)"');
    assert.deepEqual(await runHelper(path, "complete", { input: "로그인" }), { ok: true, text: "complete:로그인" });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("runHelper rejects with stderr when the helper prints no JSON", async () => {
  const directory = scratch();
  try {
    const path = fakeHelper(directory, "echo boom >&2\nexit 3");
    await assert.rejects(runHelper(path, "status"), /exited with 3: boom/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("runHelper kills the helper when the signal aborts", async () => {
  const directory = scratch();
  try {
    const path = fakeHelper(directory, "sleep 30");
    const controller = new AbortController();
    const pending = runHelper(path, "complete", { input: "p", signal: controller.signal });
    setTimeout(() => controller.abort(), 50);
    await assert.rejects(pending, { name: "AbortError" });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("buildHelper reuses a binary for the same source and replaces it when the source changes", async () => {
  const directory = scratch();
  try {
    const swiftc = ["/bin/sh", "-c", 'out=; for arg in "$@"; do [ "$prev" = -o ] && out=$arg; prev=$arg; done; echo built > "$out"'];
    const first = await buildHelper({ source: "one", directory, swiftc });
    assert.equal(await buildHelper({ source: "one", directory, swiftc }), first);
    const second = await buildHelper({ source: "two", directory, swiftc });
    assert.notEqual(second, first);
    assert.equal(existsSync(first), false);
    assert.equal(existsSync(second), true);
    assert.deepEqual(readdirSync(directory), [second.split("/").pop()]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("buildHelper reports the compiler's error and leaves no files behind", async () => {
  const directory = scratch();
  try {
    const swiftc = ["/bin/sh", "-c", "echo 'error: unterminated string literal' >&2; exit 1"];
    await assert.rejects(buildHelper({ source: "x", directory, swiftc }), /unterminated string literal/);
    assert.deepEqual(readdirSync(directory), []);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("status waits briefly for a build, then reports it as still running", async () => {
  let finish;
  const run = async (binary, mode) => ({ ready: true, binary, mode });
  const service = createHelperService({
    build: () => new Promise((resolve) => (finish = resolve)),
    run,
    statusWaitMs: 10,
  });
  assert.deepEqual(await service.status(), { ready: false, message: "Building the Swift helper" });
  finish("/bin/helper");
  assert.deepEqual(await service.status(), { ready: true, binary: "/bin/helper", mode: "status" });
});

test("status is ready on the first check when the build finishes within the wait", async () => {
  const run = async (binary, mode) => ({ ready: true, binary, mode });
  const service = createHelperService({ build: async () => "/bin/helper", run });
  assert.deepEqual(await service.status(), { ready: true, binary: "/bin/helper", mode: "status" });
});

test("status reports a failed build, and the next status starts another build", async () => {
  let builds = 0;
  const service = createHelperService({
    build: async () => {
      builds += 1;
      throw new Error("Compiling the Swift helper failed: nope");
    },
  });
  assert.deepEqual(await service.status(), { ready: false, message: "Compiling the Swift helper failed: nope" });
  await service.status();
  assert.equal(builds, 2);
});

test("concurrent completes share one build", async () => {
  let builds = 0;
  const service = createHelperService({
    build: async () => {
      builds += 1;
      return "/bin/helper";
    },
    run: async (binary, mode, { input }) => ({ ok: true, text: input }),
  });
  const answers = await Promise.all([service.complete("a"), service.complete("b")]);
  assert.deepEqual(answers, [{ ok: true, text: "a" }, { ok: true, text: "b" }]);
  assert.equal(builds, 1);
});

test("the bundled Swift source compiles and its status answers with the protocol", { skip: !existsSync("/usr/bin/xcrun") }, async () => {
  const directory = scratch();
  try {
    const binary = await buildHelper({ source: SWIFT_SOURCE, directory });
    const status = await runHelper(binary, "status");
    assert.equal(typeof status.ready, "boolean");
    if (!status.ready) assert.ok(status.message.length > 0);
    const reply = await runHelper(binary, "complete", { input: "Reply with the single word: ready" });
    if (reply.ok) assert.equal(typeof reply.text, "string");
    else assert.ok(["unavailable", "guardrail", "generation", "error"].includes(reply.code));
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

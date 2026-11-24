import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const script = fileURLToPath(new URL("../export.mjs", import.meta.url));

test("room export forwards selection and snapshot warnings and requires a revision", async t => {
  const directory = mkdtempSync(join(tmpdir(), "excalidraw-room-export-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const record = join(directory, "arguments.json");
  const command = join(directory, "excalidraw-board");
  writeFileSync(command, `#!${process.execPath}\nimport { writeFileSync } from "node:fs";\nwriteFileSync(process.env.ARGUMENTS_FILE, JSON.stringify(process.argv.slice(2)));\nconsole.error("snapshot warning");\nconsole.log(process.env.SNAPSHOT);\n`, { mode: 0o755 });
  const run = (args, snapshot) => spawnSync(process.execPath, [script, "--room-id", "room123", join(directory, "out.png"), ...args], {
    env: { ...process.env, PATH: directory, ARGUMENTS_FILE: record, SNAPSHOT: JSON.stringify(snapshot) }, encoding: "utf8",
  });
  for (const option of ["--ids", "--exclude-ids"]) {
    await t.test(option, () => {
      const result = run([option, "a,b"], { elements: [] });
      assert.equal(result.status, 1);
      assert.deepEqual(JSON.parse(readFileSync(record, "utf8")), ["snapshot", "--id", "room123", option, "a,b"]);
      assert.match(result.stderr, /snapshot warning/);
      assert.match(result.stderr, /Expected a revision from excalidraw-board snapshot/);
    });
  }
  const valid = run([], { revision: "123", elements: [] });
  assert.match(valid.stderr, /Selection contains no live elements/);
  assert.doesNotMatch(valid.stderr, /Expected a revision/);
});

test("room export names the missing board command", t => {
  const directory = mkdtempSync(join(tmpdir(), "excalidraw-room-missing-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const result = spawnSync(process.execPath, [script, "--room-id", "room123", join(directory, "out.png")], {
    env: { ...process.env, PATH: directory }, encoding: "utf8",
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /excalidraw-board is missing from PATH\. Install it separately/);
});

test("large snapshot warns and continues to validate the selection", t => {
  const directory = mkdtempSync(join(tmpdir(), "excalidraw-room-size-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  writeFileSync(join(directory, "excalidraw-board"), `#!${process.execPath}\nprocess.stdout.write(JSON.stringify({revision: "123", elements: [], padding: "x".repeat(64 * 1024 * 1024)}));\n`, { mode: 0o755 });
  const result = spawnSync(process.execPath, [script, "--room-id", "room123", join(directory, "out.png")], {
    env: { ...process.env, PATH: directory }, encoding: "utf8", timeout: 30_000,
  });
  assert.equal(result.status, 1, result.error?.message);
  assert.match(result.stderr, /warning: excalidraw-board snapshot output is \d+ bytes, over the soft limit of 67108864 bytes/);
  assert.match(result.stderr, /Selection contains no live elements/);
});

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { checkSize, hardLimit } from "../cli/excalidraw-board/size-limit.mjs";
import { checkSize as piCheckSize, hardLimit as piHardLimit, sizeWarningLog } from "../plugins/ramtoshiya/hooks/pi.ts";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

test("sizes past the soft limit pass with a warning naming the limit and sizes", () => {
  const warnings = [];
  const warn = message => warnings.push(message);
  assert.equal(hardLimit, 1024 ** 3);
  assert.equal(checkSize("example input", 5_000_000, 5_000_000, warn), 5_000_000);
  assert.deepEqual(warnings, []);
  assert.equal(checkSize("example input", 5_000_001, 5_000_000, warn), 5_000_001);
  assert.equal(checkSize("example input", hardLimit, 5_000_000, warn), hardLimit);
  assert.deepEqual(warnings, [
    "warning: example input is 5000001 bytes, over the soft limit of 5000000 bytes",
    `warning: example input is ${hardLimit} bytes, over the soft limit of 5000000 bytes`,
  ]);
});

test("sizes past the hard limit are rejected", () => {
  assert.throws(() => checkSize("example input", hardLimit + 1, 5_000_000, () => assert.fail("no warning expected")),
    { message: `example input is ${hardLimit + 1} bytes, over the hard limit of ${hardLimit} bytes` });
  assert.throws(() => checkSize("snapshot", hardLimit + 1, Infinity), /over the hard limit/);
});

test("standalone CLIs keep the same size helper", () => {
  const source = read("../cli/excalidraw-board/size-limit.mjs");
  assert.equal(read("../cli/excalidraw-web-export/size-limit.mjs"), source);
  const inline = read("../cli/worktreeinclude/worktreeinclude.mjs");
  assert.ok(inline.includes("\nconst hardLimit = 1024 ** 3;\n"));
  assert.ok(inline.includes(`\n${checkSize.toString()}\n`));
});

test("Pi guard output past the soft limit is logged instead of written to the terminal", t => {
  const state = mkdtempSync(join(tmpdir(), "size-warnings-"));
  const previous = process.env.XDG_STATE_HOME;
  t.after(() => {
    if (previous === undefined) delete process.env.XDG_STATE_HOME;
    else process.env.XDG_STATE_HOME = previous;
    rmSync(state, { recursive: true, force: true });
  });
  process.env.XDG_STATE_HOME = state;
  assert.equal(piHardLimit, hardLimit);
  assert.equal(sizeWarningLog(), join(state, "ramtoshiya", "size-warnings.log"));
  piCheckSize("Pi package guard output", 64 * 1024, 64 * 1024);
  piCheckSize("Pi package guard output", 64 * 1024 + 1, 64 * 1024);
  const lines = readFileSync(sizeWarningLog(), "utf8").trimEnd().split("\n");
  assert.equal(lines.length, 1);
  assert.match(lines[0], /^\d{4}-\d\d-\d\dT[\d:.]+Z warning: Pi package guard output is 65537 bytes, over the soft limit of 65536 bytes$/);
});

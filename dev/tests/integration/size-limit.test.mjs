import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { checkSize, hardLimit } from "../../../tools/excalidraw-board/size-limit.mjs";

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
  const source = read("../../../tools/excalidraw-board/size-limit.mjs");
  assert.equal(read("../../../tools/excalidraw-web-export/size-limit.mjs"), source);
  const inline = read("../../../tools/worktreeinclude/worktreeinclude.mjs");
  assert.ok(inline.includes("\nconst hardLimit = 1024 ** 3;\n"));
  assert.ok(inline.includes(`\n${checkSize.toString()}\n`));
});

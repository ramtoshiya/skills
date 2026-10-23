import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const root = fileURLToPath(new URL("../", import.meta.url));
test("installed board command runs without the checkout and rejects options without echoing them", t => {
  const home = mkdtempSync(join(tmpdir(), "excalidraw-install-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const env = { ...process.env, HOME: home };
  const install = () => execFileSync("sh", [join(root, "cli/excalidraw-board/install.sh")], { env, encoding: "utf8" });
  assert.match(install(), /0\.1\.0-poc/);
  assert.match(install(), /0\.1\.0-poc/);
  const command = join(home, ".local/bin/excalidraw-board");
  const run = args => spawnSync(command, args, { env, encoding: "utf8", cwd: home });
  assert.match(run(["--help"]).stdout, /room create/);
  assert.equal(run(["room", "list"]).stdout.trim(), "NAME\tID\tLAST USED");
  const unknown = run(["read", "--secret-fixture-argument"]);
  assert.equal(unknown.status, 1);
  assert.match(unknown.stderr, /Invalid command options/);
  assert.ok(!unknown.stderr.includes("secret-fixture-argument"));
  assert.equal(run(["read", "--name", "missing", "--id", "abcd"]).status, 1);
});

test("installer refuses to overwrite an unrelated command", t => {
  const home = mkdtempSync(join(tmpdir(), "excalidraw-collision-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  mkdirSync(join(home, ".local/bin"), { recursive: true });
  const command = join(home, ".local/bin/excalidraw-board");
  writeFileSync(command, "unrelated command\n");
  const result = spawnSync("sh", [join(root, "cli/excalidraw-board/install.sh")], { env: { ...process.env, HOME: home }, encoding: "utf8" });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Refusing to replace/);
  assert.equal(readFileSync(command, "utf8"), "unrelated command\n");
});

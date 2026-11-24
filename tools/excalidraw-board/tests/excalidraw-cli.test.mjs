import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { closeSync, mkdtempSync, mkdirSync, openSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { delimiter, dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const root = fileURLToPath(new URL("../../../", import.meta.url));
// A version-manager shim may lose trust when the installer changes HOME.
const testEnv = home => ({
  ...process.env,
  HOME: home,
  PATH: `${dirname(process.execPath)}${delimiter}${process.env.PATH ?? ""}`,
});

test("installed board command runs without the checkout and rejects options without echoing them", t => {
  const home = mkdtempSync(join(tmpdir(), "excalidraw-install-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const env = testEnv(home);
  const install = () => execFileSync("sh", [join(root, "tools/excalidraw-board/install.sh")], { env, encoding: "utf8" });
  assert.match(install(), /0\.1\.0-poc/);
  assert.match(install(), /0\.1\.0-poc/);
  const command = join(home, ".local/bin/excalidraw-board");
  const run = (args, input) => spawnSync(command, args, { env, input, encoding: "utf8", cwd: home });
  assert.match(run(["--help"]).stdout, /room create/);
  assert.equal(run(["room", "list"]).stdout.trim(), "NAME\tID\tLAST USED");
  const unknown = run(["read", "--secret-fixture-argument"]);
  assert.equal(unknown.status, 1);
  assert.match(unknown.stderr, /Invalid command options/);
  assert.ok(!unknown.stderr.includes("secret-fixture-argument"));
  assert.equal(run(["read", "--name", "missing", "--id", "abcd"]).status, 1);
  assert.match(run(["--help"]).stdout, /image .*--file/);
  const missingFile = run(["image", "--id", "abcd"]);
  assert.equal(missingFile.status, 1);
  assert.match(missingFile.stderr, /needs --file/);
  const badWidth = run(["image", "--id", "abcd", "--file", "private-image.png", "--width", "NaN"]);
  assert.equal(badWidth.status, 1);
  assert.match(badWidth.stderr, /finite numbers/);
  assert.equal(badWidth.stderr.includes("private-image.png"), false);
  assert.match(run(["--help"]).stdout, /images .*--concurrency/);
  const malformed = run(["images", "--id", "abcd"], "private-invalid-manifest");
  assert.equal(malformed.status, 1);
  assert.match(malformed.stderr, /Expected an images manifest/);
  assert.equal(malformed.stderr.includes("private-invalid-manifest"), false);
});

test("room create rejects a control character the registry rejects, before any request", t => {
  const home = mkdtempSync(join(tmpdir(), "excalidraw-name-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const log = join(home, "requests.log");
  const preload = join(home, "record-fetch.mjs");
  writeFileSync(preload, `import { appendFileSync } from "node:fs";\nglobalThis.fetch = async url => { appendFileSync(${JSON.stringify(log)}, "request\\n"); throw new Error("offline"); };\n`);
  const env = { ...testEnv(home), NODE_OPTIONS: `--import ${preload}` };
  const cli = join(root, "tools/excalidraw-board/excalidraw-board.mjs");
  for (const name of ["bad\u0085name", "bad\u0007name", "bad\u007fname"]) {
    const result = spawnSync(process.execPath, [cli, "room", "create", name], { env, encoding: "utf8", cwd: home });
    assert.equal(result.status, 1, JSON.stringify(name));
    assert.match(result.stderr, /Room name must be nonempty and contain no control characters/);
  }
  assert.throws(() => readFileSync(log), { code: "ENOENT" });
});

test("installer refuses to overwrite an unrelated command", t => {
  const home = mkdtempSync(join(tmpdir(), "excalidraw-collision-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  mkdirSync(join(home, ".local/bin"), { recursive: true });
  const command = join(home, ".local/bin/excalidraw-board");
  writeFileSync(command, "unrelated command\n");
  const result = spawnSync("sh", [join(root, "tools/excalidraw-board/install.sh")], { env: testEnv(home), encoding: "utf8" });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Refusing to replace/);
  assert.equal(readFileSync(command, "utf8"), "unrelated command\n");
});

test("large stdin warns and continues to validate the room link", t => {
  const home = mkdtempSync(join(tmpdir(), "excalidraw-stdin-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  // Read stdin from a file. spawnSync's input option streams it through a socket, and with 5 MB
  // that write occasionally stalled forever on macOS while the child waited for more input.
  writeFileSync(join(home, "stdin"), " ".repeat(5_000_001));
  const stdin = openSync(join(home, "stdin"), "r");
  t.after(() => closeSync(stdin));
  const result = spawnSync(process.execPath, [join(root, "tools/excalidraw-board/excalidraw-board.mjs"), "room", "import", "--name", "example", "--stdin"], {
    env: testEnv(home), stdio: [stdin, "pipe", "pipe"], encoding: "utf8",
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /warning: excalidraw-board stdin input is 5000001 bytes, over the soft limit of 5000000 bytes/);
  assert.match(result.stderr, /Invalid Excalidraw room link/);
});

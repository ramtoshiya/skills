import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const installer = fileURLToPath(new URL("install.sh", import.meta.url));

test("installed exporter runs independently of the checkout and can be updated offline", t => {
  const home = mkdtempSync(join(tmpdir(), "excalidraw-web-install-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const cache = execFileSync("npm", ["config", "get", "cache"], { encoding: "utf8" }).trim();
  const env = { ...process.env, HOME: home, npm_config_cache: cache, npm_config_offline: "true" };
  const install = () => execFileSync("sh", [installer], { env, encoding: "utf8", timeout: 60_000 });
  assert.match(install(), /Installed/);
  const command = join(home, ".local/bin/excalidraw-web-export");
  const help = spawnSync(command, ["--help"], { env, cwd: home, encoding: "utf8" });
  assert.equal(help.status, 0, help.stderr);
  assert.match(help.stdout, /excalidraw-web-export --room-id/);
  assert.equal(realpathSync(command), realpathSync(join(home, ".local/share/excalidraw-web-export/export.mjs")));
  assert.match(install(), /Installed/);
});

test("exporter installer preserves an unrelated command", t => {
  const home = mkdtempSync(join(tmpdir(), "excalidraw-web-collision-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  mkdirSync(join(home, ".local/bin"), { recursive: true });
  const command = join(home, ".local/bin/excalidraw-web-export");
  writeFileSync(command, "unrelated command\n");
  const result = spawnSync("sh", [installer], { env: { ...process.env, HOME: home }, encoding: "utf8" });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Refusing to replace/);
  assert.equal(readFileSync(command, "utf8"), "unrelated command\n");
});

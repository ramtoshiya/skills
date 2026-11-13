import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const installer = fileURLToPath(new URL('../install.sh', import.meta.url));

test('installer refuses to replace an unrelated command', t => {
  const home = mkdtempSync(join(tmpdir(), 'sidecar-install-'));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const bin = join(home, '.local/bin');
  mkdirSync(bin, { recursive: true });
  const command = join(bin, 'sidecar');
  writeFileSync(command, 'unrelated command\n');
  const compiler = join(bin, 'xcrun');
  writeFileSync(compiler, '#!/bin/sh\nfor arg do output=$arg; done\nprintf "#!/bin/sh\\nexit 0\\n" > "$output"\nchmod +x "$output"\n');
  chmodSync(compiler, 0o755);
  const result = spawnSync('sh', [installer], {
    env: { ...process.env, HOME: home, PATH: `${bin}:/usr/bin:/bin:/usr/sbin:/sbin` },
    encoding: 'utf8',
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Refusing to replace an unrelated command/);
  assert.equal(readFileSync(command, 'utf8'), 'unrelated command\n');
});

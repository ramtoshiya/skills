import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cp, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

test('host.js points bb at ~/.local/bin/claudex and forwards both bridge exports', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'claudex-native-host-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await cp(new URL('../host.js', import.meta.url), join(dir, 'host.js'));
  await writeFile(join(dir, 'package.json'), '{"type":"module"}');
  await writeFile(join(dir, 'bridge.mjs'), [
    'export default { stub: "default" };',
    'export const experimental_providerBridge = { stub: "bridge" };',
  ].join('\n'));
  await symlink(join(dir, 'bridge.mjs'), join(dir, 'claude-host.local.js'));

  const probe = `
    const host = await import(${JSON.stringify(join(dir, 'host.js'))});
    console.log(JSON.stringify({
      executable: process.env.BB_CLAUDE_CODE_EXECUTABLE,
      defaultExport: host.default,
      bridge: host.experimental_providerBridge,
    }));`;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', probe], {
    encoding: 'utf8', env: { HOME: dir },
  });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    executable: join(dir, '.local', 'bin', 'claudex'),
    defaultExport: { stub: 'default' },
    bridge: { stub: 'bridge' },
  });
});

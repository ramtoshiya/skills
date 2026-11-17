import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { PLUGIN_DIR } from '../scripts/prepare-vendor.mjs';

test('host.js points bb at ~/.local/bin/claudex and forwards both bridge exports', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'claudex-native-host-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  await cp(join(PLUGIN_DIR, 'host.js'), join(dir, 'host.js'));
  await mkdir(join(dir, 'vendor'));
  await writeFile(
    join(dir, 'vendor/claude-host.js'),
    [
      'globalThis.executableDuringBridgeLoad = process.env.BB_CLAUDE_CODE_EXECUTABLE ?? null;',
      'export default { stub: "default" };',
      'export const experimental_providerBridge = { stub: "bridge" };',
    ].join('\n'),
  );
  await writeFile(join(dir, 'package.json'), '{"type":"module"}');
  const probe = `
    const host = await import(${JSON.stringify(join(dir, 'host.js'))});
    console.log(JSON.stringify({
      executable: process.env.BB_CLAUDE_CODE_EXECUTABLE,
      duringLoad: globalThis.executableDuringBridgeLoad,
      defaultExport: host.default,
      bridge: host.experimental_providerBridge,
    }));`;
  const env = { ...process.env, HOME: dir };
  delete env.BB_CLAUDE_CODE_EXECUTABLE;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', probe], { encoding: 'utf8', env });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), {
    executable: join(dir, '.local', 'bin', 'claudex'),
    duringLoad: null,
    defaultExport: { stub: 'default' },
    bridge: { stub: 'bridge' },
  });
});

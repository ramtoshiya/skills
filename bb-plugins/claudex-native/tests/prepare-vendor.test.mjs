import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import {
  EVIDENCE_FILE,
  PIN,
  PLUGIN_DIR,
  PrepareError,
  VENDOR_FILE,
  checkVendor,
  defaultApps,
  prepareVendor,
} from '../scripts/prepare-vendor.mjs';

const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const SOURCE = 'head;return{providerId:"claude-code",status:s};tail\n//# sourceMappingURL=host.js.map\n';
const EXPECTED = 'head;return{providerId:"claudex",status:s};tail\n\n';
const FIXTURE_PIN = Object.freeze({
  ...PIN,
  bbVersion: '9.9.9',
  sourceSha256: sha256(SOURCE),
  outputSha256: sha256(EXPECTED),
});

async function scratch(t) {
  const dir = await mkdtemp(join(tmpdir(), 'claudex-native-test-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return dir;
}

async function makeApp(dir, { version = '9.9.9', source = SOURCE } = {}) {
  await mkdir(join(dir, 'Contents'), { recursive: true });
  await writeFile(
    join(dir, PIN.plist),
    `<?xml version="1.0"?>\n<plist><dict>\n\t<key>CFBundleShortVersionString</key>\n\t<string>${version}</string>\n</dict></plist>\n`,
  );
  if (source !== null) {
    await mkdir(join(dir, PIN.source, '..'), { recursive: true });
    await writeFile(join(dir, PIN.source), source);
  }
  return dir;
}

async function rejectsWith(promise, code) {
  await assert.rejects(promise, error => error instanceof PrepareError && error.code === code);
}

test('writes the edited bridge and evidence that checkVendor accepts, and a rerun converges', async t => {
  const dir = await scratch(t);
  const app = await makeApp(join(dir, 'bb.app'));
  const pluginDir = join(dir, 'plugin');

  await prepareVendor(FIXTURE_PIN, { app, pluginDir });
  const first = await readFile(join(pluginDir, EVIDENCE_FILE), 'utf8');
  assert.equal(await readFile(join(pluginDir, VENDOR_FILE), 'utf8'), EXPECTED);
  assert.doesNotMatch(first, new RegExp(dir));
  await checkVendor(FIXTURE_PIN, pluginDir);

  await prepareVendor(FIXTURE_PIN, { app, pluginDir });
  assert.equal(await readFile(join(pluginDir, VENDOR_FILE), 'utf8'), EXPECTED);
  assert.equal(await readFile(join(pluginDir, EVIDENCE_FILE), 'utf8'), first);
  assert.deepEqual((await readdir(join(pluginDir, 'vendor'))).sort(), ['claude-host.evidence.json', 'claude-host.js']);
});

test('an explicit app path is used alone and never falls back to the defaults', async t => {
  const dir = await scratch(t);
  const good = await makeApp(join(dir, 'good.app'));
  const options = { candidates: [good], pluginDir: join(dir, 'plugin') };
  await rejectsWith(prepareVendor(FIXTURE_PIN, { ...options, app: join(dir, 'missing.app') }), 'SELECTED_PATH_INVALID');
  await writeFile(join(dir, 'file.app'), '');
  await rejectsWith(prepareVendor(FIXTURE_PIN, { ...options, app: join(dir, 'file.app') }), 'SELECTED_PATH_INVALID');
  const old = await makeApp(join(dir, 'old.app'), { version: '9.8.0' });
  await rejectsWith(prepareVendor(FIXTURE_PIN, { ...options, app: old }), 'VERSION_MISMATCH');
});

test('default discovery reports no installation, or uses the first candidate that passes every pin', async t => {
  const dir = await scratch(t);
  const pluginDir = join(dir, 'plugin');
  const absent = [join(dir, 'a.app'), join(dir, 'b.app')];
  await rejectsWith(prepareVendor(FIXTURE_PIN, { candidates: absent, pluginDir }), 'NOT_INSTALLED');

  const old = await makeApp(join(dir, 'old.app'), { version: '9.8.0' });
  await rejectsWith(prepareVendor(FIXTURE_PIN, { candidates: [old], pluginDir }), 'VERSION_MISMATCH');
  const good = await makeApp(join(dir, 'good.app'));
  const result = await prepareVendor(FIXTURE_PIN, { candidates: [absent[0], old, good], pluginDir });
  assert.equal(result.app, good);
  assert.equal(await readFile(join(pluginDir, VENDOR_FILE), 'utf8'), EXPECTED);
});

test('defaultApps names the system and per-user Applications folders', () => {
  assert.deepEqual(defaultApps('/home/u'), ['/Applications/bb.app', '/home/u/Applications/bb.app']);
});

test('each source and output check fails with its own code and leaves the previous vendor file in place', async t => {
  const dir = await scratch(t);
  const pluginDir = join(dir, 'plugin');
  await prepareVendor(FIXTURE_PIN, { app: await makeApp(join(dir, 'good.app')), pluginDir });

  const cases = [
    ['VERSION_UNREADABLE', await makeApp(join(dir, 'binary.app')), FIXTURE_PIN],
    ['SOURCE_MISSING', await makeApp(join(dir, 'empty.app'), { source: null }), FIXTURE_PIN],
    ['SOURCE_HASH_MISMATCH', await makeApp(join(dir, 'changed.app'), { source: `${SOURCE} ` }), FIXTURE_PIN],
  ];
  await writeFile(join(dir, 'binary.app', PIN.plist), Buffer.from('bplist00\x00\x01', 'latin1'));
  for (const [name, source] of [
    ['zero.app', SOURCE.replace('"claude-code"', '"other"')],
    ['twice.app', SOURCE.replace('tail', 'return{providerId:"claude-code",x}')],
  ]) {
    cases.push(['EDIT_COUNT_MISMATCH', await makeApp(join(dir, name), { source }), { ...FIXTURE_PIN, sourceSha256: sha256(source) }]);
  }
  cases.push(['OUTPUT_HASH_MISMATCH', join(dir, 'good.app'), { ...FIXTURE_PIN, outputSha256: sha256('other') }]);

  for (const [code, app, pin] of cases) {
    await rejectsWith(prepareVendor(pin, { app, pluginDir }), code);
    assert.equal(await readFile(join(pluginDir, VENDOR_FILE), 'utf8'), EXPECTED, code);
  }
  assert.deepEqual((await readdir(join(pluginDir, 'vendor'))).sort(), ['claude-host.evidence.json', 'claude-host.js']);
});

test('checkVendor rejects a missing, altered, or unattested vendor file', async t => {
  const dir = await scratch(t);
  const pluginDir = join(dir, 'plugin');
  await rejectsWith(checkVendor(FIXTURE_PIN, pluginDir), 'VENDOR_MISSING');
  await prepareVendor(FIXTURE_PIN, { app: await makeApp(join(dir, 'bb.app')), pluginDir });
  await rm(join(pluginDir, EVIDENCE_FILE));
  await rejectsWith(checkVendor(FIXTURE_PIN, pluginDir), 'VENDOR_INVALID');
  await writeFile(join(pluginDir, VENDOR_FILE), `${EXPECTED}x`);
  await rejectsWith(checkVendor(FIXTURE_PIN, pluginDir), 'VENDOR_INVALID');
});

test('the CLI only accepts the production pin and rejects unknown flags', async t => {
  const dir = await scratch(t);
  const run = (...args) =>
    spawnSync(process.execPath, [join(PLUGIN_DIR, 'scripts/prepare-vendor.mjs'), ...args], { encoding: 'utf8' });
  const vendorBefore = await readFile(join(PLUGIN_DIR, VENDOR_FILE)).catch(() => null);

  const fixture = await makeApp(join(dir, 'bb.app'), { version: PIN.bbVersion });
  const mismatch = run('--app', fixture);
  assert.equal(mismatch.status, 1);
  assert.match(mismatch.stderr, /SOURCE_HASH_MISMATCH/);

  const missing = run('--app', join(dir, 'missing.app'));
  assert.equal(missing.status, 1);
  assert.match(missing.stderr, /SELECTED_PATH_INVALID/);

  for (const args of [['--source-sha256', 'x'], ['--check', '--app', fixture]]) {
    assert.equal(run(...args).status, 2, args.join(' '));
  }
  assert.deepEqual(await readFile(join(PLUGIN_DIR, VENDOR_FILE)).catch(() => null), vendorBefore);
});

test('the installed bb app reproduces the pinned vendor file', async t => {
  const dir = await scratch(t);
  try {
    await prepareVendor(PIN, { pluginDir: dir });
  } catch (error) {
    if (error instanceof PrepareError && error.code === 'NOT_INSTALLED') return t.skip('no bb.app installed');
    throw error;
  }
  assert.equal(sha256(await readFile(join(dir, VENDOR_FILE))), PIN.outputSha256);
});

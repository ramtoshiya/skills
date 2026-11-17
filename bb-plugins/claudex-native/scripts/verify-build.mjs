import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { cp, mkdtemp, readFile, rm } from 'node:fs/promises';
import { homedir, tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { PIN, PLUGIN_DIR, VENDOR_FILE, checkVendor } from './prepare-vendor.mjs';

const SOURCES = ['package.json', 'server.js', 'host.js', VENDOR_FILE];
const PORTABLE_ASSIGNMENT =
  'process.env.BB_CLAUDE_CODE_EXECUTABLE=(await import("node:path")).join((await import("node:os")).homedir(),".local","bin","claudex");';
const LITERAL_ASSIGNMENT = /process\.env\.BB_CLAUDE_CODE_EXECUTABLE=("[^"]*");/g;

const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');

function exactlyOnce(text, needle, label) {
  const count = text.split(needle).length - 1;
  if (count !== 1) throw new Error(`${label} contains the executable assignment ${count} times, expected 1`);
}

async function sameBytes(actualPath, expectedPath, label) {
  const [actual, expected] = await Promise.all([readFile(actualPath), readFile(expectedPath)]);
  if (!actual.equals(expected)) throw new Error(`${label} differs from the baseline`);
  return sha256(actual);
}

async function verifyBuild(baseline) {
  await checkVendor(PIN);
  const scratch = await mkdtemp(join(tmpdir(), 'claudex-native-build-'));
  try {
    for (const file of SOURCES) await cp(join(PLUGIN_DIR, file), join(scratch, file));
    try {
      execFileSync('bb', ['plugin', 'build', scratch], { stdio: ['ignore', 'ignore', 'inherit'] });
    } catch (error) {
      if (error.code === 'ENOENT') throw new Error('bb is not on PATH. Install the bb app and its CLI first');
      throw error;
    }

    const serverSource = await sameBytes(join(PLUGIN_DIR, 'server.js'), join(baseline, 'server.js'), 'server.js');
    const serverBuild = await sameBytes(join(scratch, 'dist/server.js'), join(baseline, 'dist/server.js'), 'dist/server.js');

    const built = (await readFile(join(scratch, 'dist/host.js'))).toString('latin1');
    exactlyOnce(built, PORTABLE_ASSIGNMENT, 'Built dist/host.js');
    const expected = await readFile(join(baseline, 'dist/host.js'));
    const literals = [...expected.toString('latin1').matchAll(LITERAL_ASSIGNMENT)];
    let comparable = built;
    if (literals.length === 1) {
      const [statement, literal] = literals[0];
      if (JSON.parse(literal) !== join(homedir(), '.local', 'bin', 'claudex')) {
        throw new Error('Baseline executable path is not ~/.local/bin/claudex for the current user');
      }
      comparable = built.replace(PORTABLE_ASSIGNMENT, () => statement);
    } else if (literals.length > 1) {
      throw new Error(`Baseline dist/host.js has ${literals.length} literal executable assignments, expected at most 1`);
    }
    if (!Buffer.from(comparable, 'latin1').equals(expected)) {
      throw new Error('Built dist/host.js differs from the baseline');
    }
    return {
      serverSource,
      serverBuild,
      hostBaseline: sha256(expected),
      hostBuilt: sha256(Buffer.from(built, 'latin1')),
      literalBaseline: literals.length === 1,
    };
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
}

let baseline;
try {
  ({ values: { baseline } } = parseArgs({ options: { baseline: { type: 'string' } } }));
  if (baseline === undefined) throw new Error('--baseline is required');
} catch (error) {
  console.error(`verify-build: ${error.message}\nUsage: verify-build --baseline <installed claudex-native plugin directory>`);
  process.exit(2);
}
try {
  const result = await verifyBuild(resolve(baseline));
  console.log(`verify-build: server.js source matches baseline (sha256 ${result.serverSource})`);
  console.log(`verify-build: dist/server.js matches baseline (sha256 ${result.serverBuild})`);
  const how = result.literalBaseline
    ? 'once the executable assignment is replaced by the baseline\'s literal ~/.local/bin/claudex path'
    : 'byte for byte';
  console.log(`verify-build: dist/host.js (sha256 ${result.hostBuilt}) equals baseline (sha256 ${result.hostBaseline}) ${how}`);
} catch (error) {
  console.error(`verify-build: ${error.code ? `${error.code}: ` : ''}${error.message}`);
  process.exitCode = 1;
}

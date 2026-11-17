import { createHash, randomBytes } from 'node:crypto';
import { realpathSync } from 'node:fs';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

export const PIN = Object.freeze({
  bbVersion: '0.49.0',
  plist: 'Contents/Info.plist',
  source:
    'Contents/Resources/app.asar.unpacked/node_modules/bb-app/server/dist/builtin-plugins/provider-claude-code/dist/host.js',
  sourceSha256: '87b8489ecd259684d16171c74c0fbebba428b0bf9f22e358215a15ad0ce5a406',
  edits: Object.freeze([
    Object.freeze({
      id: 'rate-limit-provider-id',
      find: '{providerId:"claude-code",',
      replace: '{providerId:"claudex",',
      count: 1,
    }),
    Object.freeze({
      id: 'source-map-comment',
      find: '//# sourceMappingURL=host.js.map',
      replace: '',
      count: 1,
    }),
  ]),
  outputSha256: '09194e28c09286433a3ed2b45932d932986c2076a8004ef760a1afa8ea8c2983',
});

export const PLUGIN_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const VENDOR_FILE = 'vendor/claude-host.js';
export const EVIDENCE_FILE = 'vendor/claude-host.evidence.json';

export class PrepareError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

export function defaultApps(home = homedir()) {
  return ['/Applications/bb.app', join(home, 'Applications', 'bb.app')];
}

const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');

async function readIfPresent(path) {
  try {
    return await readFile(path);
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return null;
    throw error;
  }
}

async function readPinnedSource(pin, app) {
  const plist = await readIfPresent(join(app, pin.plist));
  if (plist === null) return null;
  const version = /<key>CFBundleShortVersionString<\/key>\s*<string>([^<]*)<\/string>/.exec(plist.toString('utf8'))?.[1];
  if (version === undefined) {
    throw new PrepareError('VERSION_UNREADABLE', `${app}: ${pin.plist} has no readable CFBundleShortVersionString`);
  }
  if (version !== pin.bbVersion) {
    throw new PrepareError('VERSION_MISMATCH', `${app} is bb ${version}, this plugin is pinned to bb ${pin.bbVersion}`);
  }
  const source = await readIfPresent(join(app, pin.source));
  if (source === null) throw new PrepareError('SOURCE_MISSING', `${app} has no ${pin.source}`);
  const actual = sha256(source);
  if (actual !== pin.sourceSha256) {
    throw new PrepareError('SOURCE_HASH_MISMATCH', `${app}: bridge sha256 is ${actual}, expected ${pin.sourceSha256}`);
  }
  return source;
}

async function locateSource(pin, app, candidates) {
  if (app !== undefined) {
    const source = await readPinnedSource(pin, resolve(app));
    if (source === null) throw new PrepareError('SELECTED_PATH_INVALID', `${app} is not a bb.app bundle: no ${pin.plist}`);
    return { app: resolve(app), source };
  }
  let firstFailure;
  for (const candidate of candidates) {
    try {
      const source = await readPinnedSource(pin, candidate);
      if (source !== null) return { app: candidate, source };
    } catch (error) {
      if (!(error instanceof PrepareError)) throw error;
      firstFailure ??= error;
    }
  }
  throw firstFailure ?? new PrepareError('NOT_INSTALLED', `No bb.app found at ${candidates.join(' or ')}`);
}

function applyEdits(pin, source) {
  let text = source.toString('latin1');
  for (const edit of pin.edits) {
    const parts = text.split(edit.find);
    if (parts.length - 1 !== edit.count) {
      throw new PrepareError(
        'EDIT_COUNT_MISMATCH',
        `Edit ${edit.id} matched ${parts.length - 1} times, expected ${edit.count}`,
      );
    }
    text = parts.join(edit.replace);
  }
  const output = Buffer.from(text, 'latin1');
  const actual = sha256(output);
  if (actual !== pin.outputSha256) {
    throw new PrepareError('OUTPUT_HASH_MISMATCH', `Edited bridge sha256 is ${actual}, expected ${pin.outputSha256}`);
  }
  return output;
}

function evidenceFor(pin) {
  const evidence = {
    bbVersion: pin.bbVersion,
    source: { path: pin.source, sha256: pin.sourceSha256 },
    edits: pin.edits.map(({ id, count }) => ({ id, count })),
    output: { path: VENDOR_FILE, sha256: pin.outputSha256 },
  };
  return `${JSON.stringify(evidence, null, 2)}\n`;
}

async function publish(pluginDir, relativePath, bytes) {
  const target = join(pluginDir, relativePath);
  const staging = `${target}.${process.pid}.${randomBytes(6).toString('hex')}.tmp`;
  await mkdir(dirname(target), { recursive: true });
  try {
    await writeFile(staging, bytes, { flag: 'wx' });
    await rename(staging, target);
  } finally {
    await rm(staging, { force: true });
  }
}

export async function prepareVendor(pin, { app, candidates = defaultApps(), pluginDir = PLUGIN_DIR } = {}) {
  const located = await locateSource(pin, app, candidates);
  const output = applyEdits(pin, located.source);
  await publish(pluginDir, VENDOR_FILE, output);
  await publish(pluginDir, EVIDENCE_FILE, evidenceFor(pin));
  return { app: located.app };
}

export async function checkVendor(pin, pluginDir = PLUGIN_DIR) {
  const vendor = await readIfPresent(join(pluginDir, VENDOR_FILE));
  if (vendor === null) throw new PrepareError('VENDOR_MISSING', `${VENDOR_FILE} is missing. Run npm run prepare-vendor`);
  const actual = sha256(vendor);
  if (actual !== pin.outputSha256) {
    throw new PrepareError('VENDOR_INVALID', `${VENDOR_FILE} sha256 is ${actual}, expected ${pin.outputSha256}`);
  }
  const evidence = await readIfPresent(join(pluginDir, EVIDENCE_FILE));
  if (evidence?.toString('utf8') !== evidenceFor(pin)) {
    throw new PrepareError('VENDOR_INVALID', `${EVIDENCE_FILE} is missing or does not match the pin`);
  }
}

async function main(argv) {
  let values;
  try {
    ({ values } = parseArgs({ args: argv, options: { app: { type: 'string' }, check: { type: 'boolean' } } }));
    if (values.check && values.app !== undefined) throw new Error('--check reads no app, so it takes no --app');
  } catch (error) {
    console.error(`prepare-vendor: ${error.message}\nUsage: prepare-vendor [--app <path to bb.app>] | --check`);
    return 2;
  }
  try {
    if (values.check) {
      await checkVendor(PIN);
      console.log(`prepare-vendor: ${VENDOR_FILE} matches sha256 ${PIN.outputSha256}`);
    } else {
      const { app } = await prepareVendor(PIN, { app: values.app });
      console.log(`prepare-vendor: wrote ${VENDOR_FILE} (sha256 ${PIN.outputSha256}) from ${app}`);
    }
    return 0;
  } catch (error) {
    if (!(error instanceof PrepareError)) throw error;
    console.error(`prepare-vendor: ${error.code}: ${error.message}`);
    return 1;
  }
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main(process.argv.slice(2));
}

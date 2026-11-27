import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { register } from '../claude-plugin/hooks/register.ts';
import { askSession } from '../requests.ts';

function storage(t) {
  const dir = mkdtempSync(join(tmpdir(), 'background-tools-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
}

test('a request written before the reader starts reports its move and leaves no answer file', async (t) => {
  const dir = storage(t);
  const requests = join(dir, 'background-requests');
  const hooks = new Map();
  const aborted = [];
  const fileCreated = Promise.withResolvers();
  const engine = {
    env: { get: async () => dir },
    fs: { write: async (path, text) => {
      writeFileSync(path, text);
      if (path === requests) fileCreated.resolve();
    } },
    process: { spawn: async function* ({ argv }) {
      const signal = AbortSignal.timeout(3000);
      while (!(await readFile(requests, { encoding: 'utf8', signal }))) await delay(5, null, { signal });
      const reader = spawn(argv[0], argv.slice(1), { stdio: ['ignore', 'pipe', 'inherit'] });
      t.after(() => reader.kill());
      reader.stdout.setEncoding('utf8');
      for await (const text of reader.stdout) yield { stream: 'stdout', text };
    } },
    session: { messages: async () => [{ role: 'assistant', toolUses: [{ tool: 'Bash' }] }] },
    turn: { abort: async ({ turnId }) => { aborted.push(turnId); } },
    prompt: { submit: async () => {} },
    ui: { log: () => {} },
  };
  register((name, fn) => hooks.set(name, fn));
  await hooks.get('turn.start')(engine, {}, async () => ({ turnId: 'turn' }));
  await hooks.get('session.start')(engine, {}, async () => {});
  await fileCreated.promise;
  assert.deepEqual(await askSession(dir), { kind: 'moved', tools: ['Bash'] });
  assert.deepEqual(aborted, ['turn']);
  assert.deepEqual(readdirSync(dir), ['background-requests']);
});

test('a thread whose session never listened has no session', async (t) => {
  assert.deepEqual(await askSession(storage(t)), { kind: 'no-session' });
});

test('a session that stopped listening has no session', async (t) => {
  const dir = storage(t);
  writeFileSync(join(dir, 'background-requests'), '');
  assert.deepEqual(await askSession(dir, 300), { kind: 'no-session' });
});

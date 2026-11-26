import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { askSession } from '../requests.ts';

function storage(t) {
  const dir = mkdtempSync(join(tmpdir(), 'background-tools-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function standInSession(t, dir, answer) {
  const requests = join(dir, 'background-requests');
  writeFileSync(requests, '');
  const tail = spawn('tail', ['-n', '0', '-f', requests], { stdio: ['ignore', 'pipe', 'inherit'] });
  t.after(() => tail.kill());
  tail.stdout.setEncoding('utf8');
  tail.stdout.on('data', (text) => {
    for (const id of text.split('\n').filter(Boolean)) {
      writeFileSync(join(dir, `background-answer-${id}`), JSON.stringify(answer));
    }
  });
}

test('a session that answers reports its move and leaves no answer file', async (t) => {
  const dir = storage(t);
  standInSession(t, dir, { kind: 'moved', tools: ['Bash'] });
  assert.deepEqual(await askSession(dir), { kind: 'moved', tools: ['Bash'] });
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

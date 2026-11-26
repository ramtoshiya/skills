import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { chmodSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { delimiter, dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { moveForegroundTools } from '../sessions.ts';

const shim = fileURLToPath(new URL('../shim.cjs', import.meta.url));

const startTaskLine = 'start-foreground-task';
const splitOutputPrefix = 'write-in-two-chunks ';
const exitLeavingHelperLine = 'exit-while-a-helper-holds-stdout';

const STAND_IN = `#!${process.execPath}
const lines = require('node:readline').createInterface({ input: process.stdin });
const say = message => process.stdout.write(JSON.stringify(message) + '\\n');
if (!process.argv.includes('stream-json')) { console.log('version ' + process.argv.slice(2).join(' ')); process.exit(3); }
let foreground = [];
lines.on('line', line => {
  if (line.startsWith('${splitOutputPrefix}')) {
    const text = line.slice(${splitOutputPrefix.length});
    process.stdout.write(text.slice(0, 6));
    setTimeout(() => process.stdout.write(text.slice(6) + '\\n'), 20);
    return;
  }
  if (line === '${exitLeavingHelperLine}') {
    const helper = require('node:child_process').spawn(process.execPath, ['-e', 'setTimeout(() => {}, 60000)'],
      { detached: true, stdio: ['ignore', 'inherit', 'ignore'] });
    helper.unref();
    process.stdout.write('helper ' + helper.pid + '\\n', () => process.exit(7));
    return;
  }
  if (line === '${startTaskLine}') {
    foreground.push('t1');
    say({ type: 'system', subtype: 'task_started', task_id: 't1', description: 'Wait for the build', is_backgrounded: false });
    return;
  }
  let message;
  try { message = JSON.parse(line); } catch { process.stdout.write(line + '\\n'); return; }
  if (message.request?.subtype !== 'background_tasks') { process.stdout.write(line + '\\n'); return; }
  for (const id of foreground) say({ type: 'system', subtype: 'task_updated', task_id: id, patch: { is_backgrounded: true } });
  foreground = [];
  say({ type: 'control_response', response: { subtype: 'success', request_id: message.request_id, response: {} } });
});
`;

function start(t, args) {
  const root = mkdtempSync('/tmp/bbbg-test-');
  const claude = join(root, 'claude');
  writeFileSync(claude, STAND_IN);
  chmodSync(claude, 0o755);
  const socketDir = join(root, 's');
  const child = spawn(shim, args, {
    env: {
      PATH: [root, dirname(process.execPath), process.env.PATH].join(delimiter),
      BB_THREAD_ID: 'thr_test',
      BB_BACKGROUND_TOOLS_PROVIDER: 'claude-code',
      BB_BACKGROUND_TOOLS_SOCKET_DIR: socketDir,
    },
    stdio: ['pipe', 'pipe', 'inherit'],
  });
  const exited = new Promise(resolve => child.on('close', code => resolve(code)));
  t.after(async () => {
    child.kill();
    await exited;
    rmSync(root, { recursive: true, force: true });
  });
  let output = '';
  child.stdout.setEncoding('utf8').on('data', chunk => { output += chunk; });
  const until = async predicate => {
    while (!predicate()) await new Promise(resolve => setTimeout(resolve, 10));
  };
  const sees = text => until(() => output.includes(text));
  const listening = () => until(() => {
    try { return readdirSync(socketDir).length > 0; } catch { return false; }
  });
  return { child, exited, socketDir, sees, listening, output: () => output };
}

const SESSION = ['--output-format', 'stream-json', '--input-format', 'stream-json'];

test('a session relays bb traffic unchanged and moves the foreground task on request', { timeout: 20_000 }, async t => {
  const session = start(t, SESSION);
  const large = 'é'.repeat(300_000);
  session.child.stdin.write(`${large}\n${startTaskLine}\n`);
  await session.sees('task_started');
  await session.listening();

  assert.deepEqual(await moveForegroundTools(session.socketDir, 'thr_test'),
    { kind: 'moved', tasks: [{ taskId: 't1', description: 'Wait for the build' }] });
  assert.deepEqual(await moveForegroundTools(session.socketDir, 'thr_test'), { kind: 'nothing' });
  assert.deepEqual(await moveForegroundTools(session.socketDir, 'thr_other'), { kind: 'no-session' });

  session.child.stdin.end();
  assert.equal(await session.exited, 0);
  assert.ok(session.output().startsWith(`${large}\n`));
  assert.match(session.output(), /"subtype":"task_updated"/);
  assert.doesNotMatch(session.output(), /control_response/);
  assert.deepEqual(readdirSync(session.socketDir), []);
});

test('a request waits for the line bb is still sending', { timeout: 20_000 }, async t => {
  const session = start(t, SESSION);
  session.child.stdin.write(`${splitOutputPrefix}first-`);
  await session.listening();
  assert.deepEqual(await moveForegroundTools(session.socketDir, 'thr_test'), { kind: 'nothing' });
  session.child.stdin.end('half\n');
  assert.equal(await session.exited, 0);
  assert.equal(session.output(), 'first-half\n');
});

test('a socket left by a killed session counts as no session and is removed', { timeout: 20_000 }, async t => {
  const session = start(t, SESSION);
  await session.listening();
  session.child.kill('SIGKILL');
  await new Promise(resolve => session.child.on('exit', resolve));
  assert.deepEqual(await moveForegroundTools(session.socketDir, 'thr_test'), { kind: 'no-session' });
  assert.deepEqual(readdirSync(session.socketDir), []);
});

test('the shim exits with Claude Code while a process it left still holds stdout', { timeout: 20_000 }, async t => {
  const session = start(t, SESSION);
  t.after(() => {
    const helper = /^helper (\d+)$/m.exec(session.output());
    if (helper) process.kill(Number(helper[1]), 'SIGKILL');
  });
  session.child.stdin.write(`${exitLeavingHelperLine}\n`);
  assert.equal(await session.exited, 7);
  assert.match(session.output(), /^helper \d+$/m);
});

test('another invocation passes straight through with its exit code', { timeout: 20_000 }, async t => {
  const run = start(t, ['--version']);
  assert.equal(await run.exited, 3);
  assert.equal(run.output(), 'version --version\n');
});

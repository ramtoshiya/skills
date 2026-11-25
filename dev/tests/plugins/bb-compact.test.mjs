import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const script = resolve(dirname(fileURLToPath(import.meta.url)), '../../../plugins/ramtoshiya/skills/self-compact/scripts/bb-compact.mjs');
const thread = 'thr_self';
const scope = turnId => turnId ? { kind: 'turn', turnId } : { kind: 'thread' };
const event = (seq, type, turnId, data = {}) => ({ seq, type, threadId: thread, scope: scope(turnId), data });
const compactInput = [{ type: 'text', text: '/compact', mentions: [{ start: 0, end: 8,
  resource: { kind: 'command', trigger: '/', name: 'compact', source: 'command', origin: 'builtin' } }] }];

function recordedEvents() {
  return {
    before: [
      event(1, 'client/turn/requested', null, { requestId: 'creq_caller' }),
      event(6, 'turn/started', 'caller'),
      event(7, 'turn/input/accepted', 'caller', { clientRequestId: 'creq_caller' }),
      event(15, 'item/completed', 'caller', { item: { type: 'agentMessage' } }),
    ],
    after: [event(18, 'turn/completed', 'caller', { status: 'completed' })],
    compact: [
      event(20, 'client/turn/requested', null, { requestId: 'creq_compact', input: compactInput,
        target: { kind: 'new-turn' }, request: { method: 'turn/start' } }),
      event(21, 'turn/started', 'compact'),
      event(22, 'turn/input/accepted', 'compact', { clientRequestId: 'creq_compact' }),
      event(24, 'item/completed', 'compact', { item: { type: 'contextCompaction' } }),
      event(25, 'thread/compacted', 'compact'),
      event(32, 'turn/completed', 'compact', { status: 'completed' }),
      event(33, 'thread/contextWindowUsage/updated', 'compact'),
    ],
  };
}

// A helper that polls without end stops here after a fixed number of calls, on a fast or a loaded machine.
const callBudget = 100;

const fake = `#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const dir = process.env.BB_FAKE_DIR;
const config = JSON.parse(fs.readFileSync(path.join(dir, 'config.json')));
const statePath = path.join(dir, 'state.json');
const state = JSON.parse(fs.readFileSync(statePath));
const args = process.argv.slice(2);
const input = fs.readFileSync(0, 'utf8');
const callLog = path.join(dir, 'calls.jsonl');
if (fs.existsSync(callLog) && fs.readFileSync(callLog, 'utf8').trim().split('\\n').length >= ${callBudget}) {
  process.stderr.write('fake bb: the helper used up its budget of ${callBudget} calls without finishing.\\n');
  process.exit(1);
}
if (config.callDelayMs) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, config.callDelayMs);
fs.appendFileSync(callLog, JSON.stringify({ args, input }) + '\\n');
const save = () => fs.writeFileSync(statePath, JSON.stringify(state));
const out = value => process.stdout.write(JSON.stringify(value));
if (config.invalidJson && args[1] === config.invalidJson) {
  process.stdout.write('{');
} else if (args[1] === 'show') {
  const ready = state.phase !== 'prepare' && (!config.holdCaller || state.deliveredCaller);
  out({ thread: { id: config.wrongThread ? 'thr_other' : 'thr_self', providerId: config.provider || 'claude-code',
    status: ready && !(state.phase === 'compact' && config.activeAfterCompact) ? 'idle' : 'active', queuedMessageCount: state.phase === 'compact' ? (config.queuedAfterCompact || 0) : (config.queued || 0),
    archivedAt: config.archived ? 1 : null, deletedAt: null } });
} else if (args[1] === 'queue') {
  out(config.queueRows || []);
} else if (args[1] === 'interactions') {
  out((state.phase === 'compact' && config.interactionsAfterCompact) || config.interactions || []);
} else if (args[1] === 'log') {
  const after = Number(args[args.indexOf('--after-seq') + 1]);
  const limit = Number(args[args.indexOf('--limit') + 1]);
  let available = config.before;
  if (state.phase !== 'prepare') {
    if (config.holdCaller && !state.checkedCaller) state.checkedCaller = true;
    else available = available.concat(config.after);
  }
  if (state.phase === 'compact') available = available.concat(config.compact);
  const page = available.filter(event => event.seq > after).slice(0, limit);
  if (page.some(event => event.type === 'turn/completed' && event.scope.turnId === 'caller')) state.deliveredCaller = true;
  save();
  out(page);
} else if (args[1] === 'compact') {
  if (!state.deliveredCaller) throw new Error('compaction requested before caller completed');
  state.phase = 'compact';
  save();
  out(config.compactReceipt || { ok: true, threadId: 'thr_self' });
} else if (args[1] === 'tell') {
  if (config.tellError) {
    out({ ok: false, error: { code: 'unavailable' } });
    process.exitCode = 1;
  } else out(config.delivery || { threadId: 'thr_self', delivery: 'sent' });
} else {
  throw new Error('unexpected command');
}
`;

async function setup(t, changes = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'bb-compact-test-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const note = join(dir, 'note $(touch SENTINEL) `quoted`.md');
  await writeFile(note, 'Continue the task.');
  await writeFile(join(dir, 'bb'), fake);
  await chmod(join(dir, 'bb'), 0o755);
  await writeFile(join(dir, 'config.json'), JSON.stringify({ ...recordedEvents(), ...changes }));
  await writeFile(join(dir, 'state.json'), JSON.stringify({ phase: 'prepare' }));
  const env = { ...process.env, PATH: `${dir}:${process.env.PATH}`, BB_THREAD_ID: thread, BB_FAKE_DIR: dir };
  delete env.BB_CLI;
  const invoke = (...args) => new Promise(done => {
    const child = execFile(process.execPath, [script, ...args], { cwd: dir, env, encoding: 'utf8' },
      (error, stdout, stderr) => done({ status: child.exitCode, stdout, stderr }));
  });
  const calls = async () => {
    try { return (await readFile(join(dir, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse); }
    catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  };
  const prepare = () => invoke('prepare', note);
  async function run(options = [], captured) {
    if (!captured) {
      const result = await prepare();
      assert.equal(result.status, 0, result.stderr);
      captured = JSON.parse(result.stdout);
    }
    await writeFile(join(dir, 'state.json'), JSON.stringify({ phase: 'run' }));
    return invoke('run', note, '--launch-seq', String(captured.launchSeq), '--turn-id', captured.turnId, ...options);
  }
  return { dir, note, env, invoke, prepare, run, calls };
}

// Each case waits on the helper's poll interval, so the cases run concurrently in one suite below.
const cases = [];
const test = (name, fn) => cases.push([name, fn]);

test('captures the active caller and waits for its completion before proof and resume', async t => {
  const fixture = await setup(t, { holdCaller: true });
  const prepared = await fixture.prepare();
  assert.equal(prepared.status, 0, prepared.stderr);
  assert.deepEqual(JSON.parse(prepared.stdout), { launchSeq: 15, turnId: 'caller' });
  assert.equal((await fixture.calls()).filter(call => ['compact', 'tell'].includes(call.args[1])).length, 0);
  const result = await fixture.run([], JSON.parse(prepared.stdout));
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), { compacted: true, resumeSent: true, evidence: {
    boundarySeq: 18, requestId: 'creq_compact', requestSeq: 20, turnId: 'compact',
    acceptedSeq: 22, compactionSeq: 25, completionSeq: 32,
  } });
  const calls = await fixture.calls();
  assert.equal(calls.filter(call => call.args[1] === 'compact').length, 1);
  const sends = calls.filter(call => call.args[1] === 'tell');
  assert.equal(sends.length, 1);
  assert.deepEqual(sends[0].args, ['thread', 'tell', thread, '--mode', 'queue', '--message-file', '-', '--json']);
  assert.ok(sends[0].input.includes(JSON.stringify(fixture.note)));
  assert.equal(await readFile(fixture.note, 'utf8'), 'Continue the task.');
  await assert.rejects(readFile(join(fixture.dir, 'SENTINEL')), { code: 'ENOENT' });
});

const prepareCommand = event(16, 'item/started', 'caller', { item: {
  id: 'tool_prepare', type: 'commandExecution', command: 'node "/skills/scripts/bb-compact.mjs" prepare "/tmp/handoff.md"',
} });

test('proves and resumes when every bb call is slow, as on a loaded machine', async t => {
  const fixture = await setup(t, { holdCaller: true, callDelayMs: 700 });
  const prepared = await fixture.prepare();
  assert.equal(prepared.status, 0, prepared.stderr);
  const result = await fixture.run([], JSON.parse(prepared.stdout));
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).resumeSent, true);
});

test('compacts and resumes after steering and a child notice accepted by the current turn', async t => {
  const events = recordedEvents();
  events.before.splice(3, 0,
    event(8, 'client/turn/requested', null, { requestId: 'creq_steer', initiator: 'agent',
      source: 'tell', target: { kind: 'steer', expectedTurnId: 'caller' } }),
    event(9, 'turn/input/accepted', 'caller', { clientRequestId: 'creq_steer' }),
    event(10, 'client/turn/requested', null, { requestId: 'creq_child', initiator: 'system',
      source: 'tell', systemMessageKind: 'child-completed', target: { kind: 'auto', expectedTurnId: 'caller' } }),
    event(11, 'turn/input/accepted', 'caller', { clientRequestId: 'creq_child' }));
  events.before.push(prepareCommand);
  const fixture = await setup(t, events);
  const result = await fixture.run();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).resumeSent, true);
  const calls = await fixture.calls();
  assert.equal(calls.filter(call => call.args[1] === 'compact').length, 1);
  assert.equal(calls.filter(call => call.args[1] === 'tell').length, 1);
});

for (const [name, requestSeq, acceptance] of [
  ['was not accepted', 8, null],
  ['was accepted into another turn', 8, event(9, 'turn/input/accepted', 'other', { clientRequestId: 'creq_steer' })],
  ['was followed by acceptance of a different request', 8, event(9, 'turn/input/accepted', 'caller', { clientRequestId: 'creq_other' })],
  ['was accepted after preparation started', 8, event(17, 'turn/input/accepted', 'caller', { clientRequestId: 'creq_steer' })],
  ['arrived and was accepted during preparation', 17, event(18, 'turn/input/accepted', 'caller', { clientRequestId: 'creq_steer' })],
]) {
  test(`refuses preparation when steering ${name}`, async t => {
    const events = recordedEvents();
    events.before.push(prepareCommand, event(requestSeq, 'client/turn/requested', null, { requestId: 'creq_steer',
      target: { kind: 'steer', expectedTurnId: 'caller' } }));
    if (acceptance) events.before.push(acceptance);
    events.before.sort((left, right) => left.seq - right.seq);
    const fixture = await setup(t, events);
    const result = await fixture.prepare();
    assert.equal(result.status, 1, result.stderr);
    assert.match(result.stderr, /New work or a different turn/);
    assert.equal(await readFile(fixture.note, 'utf8'), 'Continue the task.');
  });
}

test('proves compaction without resuming when requested', async t => {
  const fixture = await setup(t);
  const result = await fixture.run(['--no-resume']);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).resumeSent, false);
  assert.equal((await fixture.calls()).filter(call => call.args[1] === 'tell').length, 0);
});

test('rejects the recorded Codex event sequence when it lacks a provider compaction boundary', async t => {
  const events = recordedEvents();
  events.before = events.before.map(item => ({ ...item, seq: ({ 6: 9, 7: 10 })[item.seq] ?? item.seq }));
  events.after = [event(20, 'turn/completed', 'caller', { status: 'completed' })];
  events.compact = events.compact.slice(0, 4).map((item, index) => ({ ...item, seq: [21, 22, 23, 28][index] }));
  events.compact.push(event(29, 'turn/completed', 'compact', { status: 'completed' }));
  const fixture = await setup(t, events);
  const result = await fixture.run();
  assert.notEqual(result.status, 0);
  assert.equal((await fixture.calls()).filter(call => call.args[1] === 'tell').length, 0);
});

test('drains event pages before deciding whether to resume', async t => {
  const events = recordedEvents();
  events.compact = [
    ...events.compact.slice(0, 3),
    ...Array.from({ length: 105 }, (_, i) => event(23 + i, 'provider/unhandled', 'compact')),
    event(128, 'thread/compacted', 'compact'),
    event(129, 'turn/completed', 'compact', { status: 'completed' }),
  ];
  const fixture = await setup(t, events);
  const result = await fixture.run();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).evidence.compactionSeq, 128);
  assert.ok((await fixture.calls()).some(call => call.args[1] === 'log' && Number(call.args[call.args.indexOf('--after-seq') + 1]) >= 100));
});

const badCompactions = {
  'only a completed compaction item': events => events.filter(item => item.type !== 'thread/compacted'),
  'a boundary for a different turn': events => events.map(item => item.type === 'thread/compacted' ? { ...item, scope: scope('other') } : item),
  'a missing input acceptance': events => events.filter(item => item.type !== 'turn/input/accepted'),
  'an acceptance for a different request': events => events.map(item => item.type === 'turn/input/accepted' ? { ...item, data: { clientRequestId: 'creq_other' } } : item),
  'an unstructured compact command': events => events.map(item => item.type === 'client/turn/requested' ? { ...item, data: { ...item.data, input: [{ type: 'text', text: '/compact', mentions: [] }] } } : item),
  'a failed compaction turn': events => events.map(item => item.type === 'turn/completed' ? { ...item, data: { status: 'failed' } } : item),
  'a duplicate compact request': events => [{ ...events[0], seq: 19 }, ...events],
  'a missing compact request': events => events.slice(1),
  'context clearing': events => [events[0], event(21, 'thread/context/cleared', 'compact'), ...events.slice(2)],
  'a foreign notification turn': events => [...events.slice(0, 5), event(26, 'turn/started', 'notification'), ...events.slice(5)],
};

for (const [name, transform] of Object.entries(badCompactions)) {
  test(`does not resume after ${name}`, async t => {
    const original = recordedEvents();
    const fixture = await setup(t, { ...original, compact: transform(original.compact) });
    const result = await fixture.run();
    assert.notEqual(result.status, 0, result.stdout);
    assert.equal((await fixture.calls()).filter(call => call.args[1] === 'tell').length, 0);
    assert.equal(await readFile(fixture.note, 'utf8'), 'Continue the task.');
  });
}

for (const [name, changes] of [
  ['unsupported provider', { provider: 'codex' }],
  ['queued work', { queued: 1 }],
  ['pending interaction', { interactions: [{ status: 'pending' }] }],
  ['resolving interaction', { interactions: [{ status: 'resolving' }] }],
  ['archived thread', { archived: true }],
  ['wrong thread ID', { wrongThread: true }],
  ['malformed BB JSON', { invalidJson: 'show' }],
]) {
  test(`refuses preparation with ${name}`, async t => {
    const fixture = await setup(t, changes);
    const result = await fixture.prepare();
    assert.notEqual(result.status, 0);
    assert.equal((await fixture.calls()).filter(call => ['compact', 'tell'].includes(call.args[1])).length, 0);
    assert.equal(await readFile(fixture.note, 'utf8'), 'Continue the task.');
  });
}

const queueRow = (waitingOn, id = 'queued_1') => ({ id, waitingOn });
const heldByMail = queueRow({ kind: 'plugin', pluginId: 'mail', reason: 'Mail inbox' });

test('compacts while mail holds an inbox message, which is not queued work', async t => {
  const fixture = await setup(t, { queued: 1, queuedAfterCompact: 1, queueRows: [heldByMail] });
  const result = await fixture.run();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).compacted, true);
  const listing = (await fixture.calls()).find(call => call.args[1] === 'queue');
  assert.deepEqual(listing.args, ['thread', 'queue', 'list', thread, '--json']);
});

for (const [name, changes] of [
  ['a real queued message beside the held one', { queued: 2, queueRows: [heldByMail, queueRow(null, 'queued_2')] }],
  ['a message held by another plugin', { queued: 1, queueRows: [queueRow({ kind: 'plugin', pluginId: 'rate-limit', reason: 'Limit' })] }],
  ['a message waiting on core', { queued: 1, queueRows: [queueRow({ kind: 'interaction' })] }],
  ['a queue listing shorter than the count', { queued: 2, queueRows: [heldByMail] }],
  ['a malformed queue listing', { queued: 1, queueRows: ['held'] }],
]) {
  test(`refuses preparation with mail holding one message and ${name}`, async t => {
    const fixture = await setup(t, changes);
    const result = await fixture.prepare();
    assert.notEqual(result.status, 0);
    assert.equal((await fixture.calls()).filter(call => ['compact', 'tell'].includes(call.args[1])).length, 0);
  });
}

for (const [name, changes] of [
  ['pending interaction', { interactionsAfterCompact: [{ status: 'pending' }] }],
  ['resolving interaction', { interactionsAfterCompact: [{ status: 'resolving' }] }],
  ['incorrect compact receipt', { compactReceipt: { ok: true, threadId: 'thr_other' } }],
  ['compact error response', { compactReceipt: { ok: false, error: { code: 'rejected' } } }],
]) {
  test(`does not resume when BB reports ${name} after compaction is requested`, async t => {
    const fixture = await setup(t, changes);
    const result = await fixture.run();
    assert.notEqual(result.status, 0);
    const calls = await fixture.calls();
    assert.equal(calls.filter(call => call.args[1] === 'compact').length, 1);
    assert.equal(calls.filter(call => call.args[1] === 'tell').length, 0);
  });
}

test('uses BB_CLI as an absolute executable and rejects an invalid selected path', async t => {
  const fixture = await setup(t);
  fixture.env.BB_CLI = join(fixture.dir, 'bb');
  const prepared = await fixture.prepare();
  assert.equal(prepared.status, 0, prepared.stderr);
  fixture.env.BB_CLI = join(fixture.dir, 'missing');
  const result = await fixture.prepare();
  assert.notEqual(result.status, 0);
});

test('rejects malformed command arguments before invoking BB', async t => {
  const fixture = await setup(t);
  const result = await fixture.invoke('prepare', 'relative.md');
  assert.notEqual(result.status, 0);
  assert.deepEqual(await fixture.calls(), []);
});

test('does not compact when the captured caller does not match the completed turn', async t => {
  const fixture = await setup(t);
  const prepared = await fixture.prepare();
  assert.equal(prepared.status, 0, prepared.stderr);
  const result = await fixture.run([], { ...JSON.parse(prepared.stdout), turnId: 'other' });
  assert.notEqual(result.status, 0);
  assert.equal((await fixture.calls()).filter(call => ['compact', 'tell'].includes(call.args[1])).length, 0);
});

for (const [name, after] of [
  ['caller failure', [event(18, 'turn/completed', 'caller', { status: 'failed' })]],
  ['incoming user work', [event(17, 'client/turn/requested', null, { requestId: 'creq_other' }), event(18, 'turn/completed', 'caller', { status: 'completed' })]],
  ['notification turn', [event(17, 'turn/started', 'notification'), event(18, 'turn/completed', 'caller', { status: 'completed' })]],
  ['automatic compaction before the manual request', [event(17, 'thread/compacted', 'caller'), event(18, 'turn/completed', 'caller', { status: 'completed' })]],
  ['context clear', [event(17, 'thread/context/cleared', 'caller'), event(18, 'turn/completed', 'caller', { status: 'completed' })]],
]) {
  test(`does not compact after ${name}`, async t => {
    const fixture = await setup(t, { after });
    const result = await fixture.run();
    assert.notEqual(result.status, 0);
    assert.equal((await fixture.calls()).filter(call => ['compact', 'tell'].includes(call.args[1])).length, 0);
  });
}

test('keeps a finished compaction when a notice is queued after the request', async t => {
  const fixture = await setup(t, { queuedAfterCompact: 1 });
  const result = await fixture.run();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).compacted, true);
  assert.equal((await fixture.calls()).filter(call => call.args[1] === 'tell').length, 1);
});

test('keeps a finished compaction when a queued notice starts its own turn right after it', async t => {
  const original = recordedEvents();
  const notice = [
    event(34, 'client/turn/requested', null, { requestId: 'creq_notice', source: 'tell' }),
    event(35, 'turn/started', 'notice'),
    event(36, 'turn/input/accepted', 'notice', { clientRequestId: 'creq_notice' }),
  ];
  const fixture = await setup(t, { compact: [...original.compact, ...notice], queuedAfterCompact: 1, activeAfterCompact: true });
  const result = await fixture.run();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).compacted, true);
  assert.equal((await fixture.calls()).filter(call => call.args[1] === 'compact').length, 1);
});

test('reports a late queued resume without retrying', async t => {
  const fixture = await setup(t, { delivery: { threadId: thread, delivery: 'queued', queuedMessage: { id: 'queue_123' } } });
  const result = await fixture.run();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /queue_123/);
  assert.match(result.stderr, /may be delivered later/);
  assert.equal((await fixture.calls()).filter(call => call.args[1] === 'tell').length, 1);
  assert.equal(await readFile(fixture.note, 'utf8'), 'Continue the task.');
});

test('reports uncertain resume delivery after a failed send without retrying', async t => {
  const fixture = await setup(t, { tellError: true });
  const result = await fixture.run();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /delivery is uncertain/i);
  assert.equal((await fixture.calls()).filter(call => call.args[1] === 'tell').length, 1);
  assert.equal(await readFile(fixture.note, 'utf8'), 'Continue the task.');
});

describe('bb-compact', { concurrency: true }, () => {
  for (const [name, fn] of cases) it(name, fn);
});

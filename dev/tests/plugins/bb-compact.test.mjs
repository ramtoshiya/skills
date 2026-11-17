import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
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

const fake = `#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const dir = process.env.BB_FAKE_DIR;
const config = JSON.parse(fs.readFileSync(path.join(dir, 'config.json')));
const statePath = path.join(dir, 'state.json');
const state = JSON.parse(fs.readFileSync(statePath));
const args = process.argv.slice(2);
const input = fs.readFileSync(0, 'utf8');
fs.appendFileSync(path.join(dir, 'calls.jsonl'), JSON.stringify({ args, input }) + '\\n');
const save = () => fs.writeFileSync(statePath, JSON.stringify(state));
const out = value => process.stdout.write(JSON.stringify(value));
if (config.invalidJson && args[1] === config.invalidJson) {
  process.stdout.write('{');
} else if (args[1] === 'show') {
  const ready = state.phase !== 'prepare' && (!config.holdCaller || state.deliveredCaller);
  out({ thread: { id: config.wrongThread ? 'thr_other' : 'thr_self', providerId: config.provider || 'claude-code',
    status: ready ? 'idle' : 'active', queuedMessageCount: state.phase === 'compact' ? (config.queuedAfterCompact || 0) : (config.queued || 0),
    archivedAt: config.archived ? 1 : null, deletedAt: null } });
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
  for (const entry of config.ledgerEntries || []) fs.appendFileSync(path.join(dir, "ledger.jsonl"), JSON.stringify(entry) + "\\n");
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
  const invoke = (...args) => spawnSync(process.execPath, [script, ...args], { cwd: dir, env, encoding: 'utf8', timeout: 12_000 });
  const calls = async () => {
    try { return (await readFile(join(dir, 'calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse); }
    catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  };
  const prepare = () => invoke('prepare', note);
  async function run(options = [], captured) {
    if (!captured) {
      const result = prepare();
      assert.equal(result.status, 0, result.stderr);
      captured = JSON.parse(result.stdout);
    }
    await writeFile(join(dir, 'state.json'), JSON.stringify({ phase: 'run' }));
    return invoke('run', note, '--launch-seq', String(captured.launchSeq), '--turn-id', captured.turnId, ...options);
  }
  return { dir, note, env, invoke, prepare, run, calls };
}

test('captures the active caller and waits for its completion before proof and resume', async t => {
  const fixture = await setup(t, { holdCaller: true });
  const prepared = fixture.prepare();
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
    const result = fixture.prepare();
    assert.notEqual(result.status, 0);
    assert.equal((await fixture.calls()).filter(call => ['compact', 'tell'].includes(call.args[1])).length, 0);
    assert.equal(await readFile(fixture.note, 'utf8'), 'Continue the task.');
  });
}

for (const [name, changes] of [
  ['queued work', { queuedAfterCompact: 1 }],
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
  const prepared = fixture.prepare();
  assert.equal(prepared.status, 0, prepared.stderr);
  fixture.env.BB_CLI = join(fixture.dir, 'missing');
  const result = fixture.prepare();
  assert.notEqual(result.status, 0);
});

test('rejects malformed command arguments before invoking BB', async t => {
  const fixture = await setup(t);
  const result = fixture.invoke('prepare', 'relative.md');
  assert.notEqual(result.status, 0);
  assert.deepEqual(await fixture.calls(), []);
});

test('does not compact when the captured caller does not match the completed turn', async t => {
  const fixture = await setup(t);
  const prepared = fixture.prepare();
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

const manual = { sessionId: 'sess_new', oldSessionId: 'sess_old', kind: 'summarize', reason: 'manual', beforeTokens: 240000, afterTokens: 30000 };

async function hermes(t, changes = {}) {
  const fixture = await setup(t, { provider: 'acp-hermes-agent', ledgerEntries: [manual], ...changes });
  const ledger = join(fixture.dir, 'ledger.jsonl');
  const tells = async () => (await fixture.calls()).filter(call => call.args[1] === 'tell');
  const compacts = async () => (await fixture.calls()).filter(call => call.args[1] === 'compact').length;
  return { ...fixture, ledger, tells, compacts, runWithLedger: (options = []) => fixture.run(['--compaction-ledger', ledger, ...options]) };
}

test('proves a Hermes compaction with BB events and one committed manual summary', async t => {
  const fixture = await hermes(t);
  const result = await fixture.runWithLedger();
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.compacted, true);
  assert.equal(output.resumeSent, true);
  assert.deepEqual(output.evidence.ledger, manual);
  assert.equal((await fixture.tells()).length, 1);
});

test('ignores ledger lines written before the compaction request', async t => {
  const fixture = await hermes(t);
  await writeFile(fixture.ledger, JSON.stringify({ ...manual, reason: 'pre_api' }) + '\n');
  const result = await fixture.runWithLedger();
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout).evidence.ledger, manual);
});

test('requires the ledger for Hermes and refuses it for Claude before compacting', async t => {
  const missing = await hermes(t);
  const withoutLedger = await missing.run();
  assert.notEqual(withoutLedger.status, 0);
  assert.match(withoutLedger.stderr, /needs --compaction-ledger/);
  assert.equal(await missing.compacts(), 0);

  const claude = await setup(t);
  const withLedger = await claude.run(['--compaction-ledger', join(claude.dir, 'ledger.jsonl')]);
  assert.notEqual(withLedger.status, 0);
  assert.match(withLedger.stderr, /takes no --compaction-ledger/);
  assert.equal((await claude.calls()).filter(call => call.args[1] === 'compact').length, 0);
});

const unprovenHermes = {
  'no committed compaction (noop or refusal)': { ledgerEntries: [] },
  'two committed compactions': { ledgerEntries: [manual, manual] },
  'an automatic compaction instead of the manual one': { ledgerEntries: [{ ...manual, reason: 'pre_api' }] },
  'a pruning pass instead of a summary': { ledgerEntries: [{ ...manual, kind: 'prune_tool_results' }] },
};

for (const [name, changes] of Object.entries(unprovenHermes)) {
  test(`does not resume a Hermes thread after ${name} and tells it once`, async t => {
    const fixture = await hermes(t, changes);
    const result = await fixture.runWithLedger();
    assert.notEqual(result.status, 0);
    const output = JSON.parse(result.stdout);
    assert.equal(output.compacted, 'unknown');
    assert.equal(output.phase, 'compact-requested');
    assert.equal(output.failureNoticeSent, true);
    assert.equal(await fixture.compacts(), 1);
    const tells = await fixture.tells();
    assert.equal(tells.length, 1);
    assert.match(tells[0].input, /^Self-compaction did not complete: .* No retry was made\./);
    assert.ok(tells[0].input.includes(JSON.stringify(fixture.note)));
  });
}

test('sends no Hermes failure notice when the user decision is pending', async t => {
  const fixture = await hermes(t, { ledgerEntries: [] });
  const result = await fixture.runWithLedger(['--no-resume']);
  assert.notEqual(result.status, 0);
  assert.equal(JSON.parse(result.stdout).failureNoticeSent, false);
  assert.equal((await fixture.tells()).length, 0);
});

test('sends no Hermes failure notice into a thread with queued work', async t => {
  const fixture = await hermes(t, { ledgerEntries: [], queuedAfterCompact: 1 });
  const result = await fixture.runWithLedger();
  assert.notEqual(result.status, 0);
  assert.equal(JSON.parse(result.stdout).failureNoticeSent, false);
  assert.equal((await fixture.tells()).length, 0);
});

test('does not follow an uncertain Hermes resume with a failure notice', async t => {
  const fixture = await hermes(t, { delivery: { threadId: thread, delivery: 'unknown' } });
  const result = await fixture.runWithLedger();
  assert.notEqual(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), { compacted: true, phase: 'proven', error: 'Resume delivery is uncertain.', failureNoticeSent: false });
  assert.equal((await fixture.tells()).length, 1);
});

test('reports a Hermes failure before compaction without claiming a compaction', async t => {
  const fixture = await hermes(t, { after: [event(18, 'turn/completed', 'caller', { status: 'failed' })] });
  const result = await fixture.runWithLedger();
  assert.notEqual(result.status, 0);
  const output = JSON.parse(result.stdout);
  assert.equal(output.compacted, false);
  assert.equal(output.phase, 'waiting-caller');
  assert.equal(await fixture.compacts(), 0);
});

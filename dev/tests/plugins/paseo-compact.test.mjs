import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { compactAndResume } from '../../../plugins/ramtoshiya-cc/skills/self-compact/scripts/paseo-compact.mjs';

const completed = {
  seqStart: 12,
  turnId: 'compact-turn',
  item: { type: 'tool_call', status: 'completed', metadata: { title: 'Compact conversation' } },
};

async function handoff(t) {
  const directory = await mkdtemp(join(tmpdir(), 'paseo-compact-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const note = join(directory, 'handoff.md');
  await writeFile(note, 'Continue the isolated test.');
  return note;
}

function client({ commands = ['compact'], finishes = [{ status: 'idle' }, { status: 'idle' }], entries = [completed] } = {}) {
  const sends = [];
  let reads = 0;
  let commandId;
  return {
    sends,
    listCommands: async () => ({ commands: commands.map(name => ({ name })) }),
    waitForFinish: async () => finishes.shift(),
    fetchAgentTimeline: async () => ++reads === 1
      ? { agent: { status: 'idle' }, epoch: 'epoch', window: { maxSeq: 10 } }
      : { agent: { status: 'idle' }, epoch: 'epoch', entries: [
          { seqStart: 11, turnId: 'compact-turn', item: { type: 'user_message', clientMessageId: commandId } },
          ...entries,
        ] },
    sendAgentMessage: async (id, text, options) => {
      commandId = options?.messageId;
      sends.push({ id, text });
    },
  };
}

test('waits for turn completion and compaction evidence before sending resume', async t => {
  const note = await handoff(t);
  const c = client();
  let release;
  let entered;
  const currentTurn = new Promise(resolve => { release = resolve; });
  const waiting = new Promise(resolve => { entered = resolve; });
  const finish = c.waitForFinish;
  let waits = 0;
  c.waitForFinish = async () => {
    if (++waits === 1) {
      entered();
      await currentTurn;
    }
    return finish();
  };
  const operation = compactAndResume(c, 'own-agent', note);
  await waiting;
  assert.equal(c.sends.length, 0);
  release();
  const result = await operation;
  assert.deepEqual(result, { compacted: true, resumeSent: true, evidence: completed.item });
  assert.equal(c.sends.length, 2);
  assert.match(c.sends[0].text, /^\/compact /);
  assert.match(c.sends[1].text, /^Resume after self-compaction:/);
  assert.ok(c.sends.every(send => send.id === 'own-agent' && send.text.includes(note)));
});

test('compacts without resuming when the next step needs the user', async t => {
  const c = client();
  const result = await compactAndResume(c, 'own-agent', await handoff(t), { resume: false });
  assert.equal(result.resumeSent, false);
  assert.equal(c.sends.length, 1);
});

for (const [name, options, sends] of [
  ['unsupported provider', { commands: ['help'] }, 0],
  ['failed current turn', { finishes: [{ status: 'error', error: 'turn failed' }] }, 0],
  ['failed compaction', { finishes: [{ status: 'idle' }, { status: 'error', error: 'compact failed' }] }, 1],
  ['ordinary assistant summary', { entries: [{ seqStart: 11, item: { type: 'assistant_message', text: 'Compacted.' } }] }, 1],
  ['stale compaction evidence', { entries: [{ ...completed, seqStart: 9 }] }, 1],
  ['unfinished compaction event', { entries: [{ ...completed, item: { ...completed.item, status: 'running' } }] }, 1],
  ['another command compacted', { entries: [{ ...completed, turnId: 'another-turn' }] }, 1],
  ['intervening user work', { entries: [completed, { seqStart: 13, turnId: 'new-work', item: { type: 'user_message', text: 'Stop' } }] }, 1],
]) {
  test(`does not resume after ${name}`, async t => {
    const c = client(options);
    await assert.rejects(compactAndResume(c, 'own-agent', await handoff(t)));
    assert.equal(c.sends.length, sends);
    assert.ok(c.sends.every(send => send.text.startsWith('/compact ')));
  });
}

import { execFile } from 'node:child_process';
import { constants } from 'node:fs';
import { access, readFile, stat } from 'node:fs/promises';
import { isAbsolute } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const PAGE_SIZE = 100;
const DEADLINE_MS = 300_000;
const CALL_TIMEOUT_MS = 15_000;
const POLL_MS = 500;
const LEDGER_GRACE_MS = 2_000;

// BB reports any ACP end_turn as a finished compaction, and Hermes ends a noop or refused /compress
// with end_turn too, so Hermes also needs the committed compaction that its self-compact plugin
// appends to the ledger.
const PROVIDERS = {
  'claude-code': { ledger: false, failureNotice: false },
  'acp-hermes-agent': { ledger: true, failureNotice: true },
};

function fail(message) {
  throw new Error(message);
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function nonempty(value) {
  return typeof value === 'string' && value.length > 0;
}

function parseRun(rest) {
  const options = { ledger: null, resume: true };
  if (rest[0] !== '--launch-seq' || !/^[1-9][0-9]*$/.test(rest[1] ?? '') ||
      !Number.isSafeInteger(Number(rest[1])) || rest[2] !== '--turn-id' || !nonempty(rest[3])) return null;
  for (let i = 4; i < rest.length; i++) {
    if (rest[i] === '--no-resume' && options.resume) options.resume = false;
    else if (rest[i] === '--compaction-ledger' && options.ledger === null && isAbsolute(rest[i + 1] ?? '')) options.ledger = rest[++i];
    else return null;
  }
  return { launchSeq: Number(rest[1]), turnId: rest[3], ...options };
}

const outcome = { compacted: false, phase: 'waiting-caller', resumeAttempted: false };
let report = null;

function prepareCommandSeq(history, turnId) {
  const active = new Map();
  for (const { seq, type, scope, data: { item } } of history) {
    if (scope.turnId !== turnId || item?.type !== 'commandExecution' || !nonempty(item.id)) continue;
    if (type === 'item/completed') active.delete(item.id);
    if (type === 'item/started' && typeof item.command === 'string' &&
        /\bbb-compact\.mjs["']?\s+prepare\s/.test(item.command)) active.set(item.id, seq);
  }
  return active.size === 1 ? active.values().next().value : 0;
}

async function main() {
  const args = process.argv.slice(2);
  const threadId = process.env.BB_THREAD_ID;
  const [action, note] = args;
  const preparing = action === 'prepare' && args.length === 2;
  const options = action === 'run' ? parseRun(args.slice(2)) : null;
  if ((!preparing && !options) || !note || !isAbsolute(note) ||
      !/^thr_[A-Za-z0-9_-]+$/.test(threadId ?? '')) {
    fail('Usage: bb-compact.mjs prepare <absolute-note> or run <absolute-note> --launch-seq <seq> --turn-id <id> [--compaction-ledger <absolute-path>] [--no-resume] inside a BB thread.');
  }
  if (!(await stat(note)).isFile()) fail('The handoff note must be a readable file.');
  await readFile(note, 'utf8');
  const cli = process.env.BB_CLI || 'bb';
  if (process.env.BB_CLI) {
    if (!isAbsolute(cli)) fail('BB_CLI must select an absolute executable path.');
    await access(cli, constants.X_OK);
    if (!(await stat(cli)).isFile()) fail('BB_CLI does not select an executable file.');
  }
  const deadline = Date.now() + DEADLINE_MS;

  async function bb(args, input, { pastDeadline = false } = {}) {
    const remaining = pastDeadline ? CALL_TIMEOUT_MS : deadline - Date.now();
    if (remaining <= 0) fail('Timed out waiting for BB compaction proof.');
    const stdout = await new Promise((resolve, reject) => {
      const child = execFile(cli, [...args, '--json'], {
        encoding: 'utf8', timeout: Math.min(remaining, CALL_TIMEOUT_MS), killSignal: 'SIGKILL',
        maxBuffer: 8 * 1024 * 1024,
      }, (error, output) => error ? reject(error) : resolve(output));
      child.stdin.on('error', () => {
        if (input !== undefined) reject(new Error('Could not write the resume message. Delivery is uncertain.'));
      });
      child.stdin.end(input);
    });
    let value;
    try { value = JSON.parse(stdout); } catch { fail('BB returned invalid JSON.'); }
    if (isObject(value) && value.ok === false) fail('BB returned an error response.');
    return value;
  }

  let provider = null;
  async function threadState({ queued = false } = {}) {
    const show = await bb(['thread', 'show', threadId]);
    const thread = show?.thread;
    if (!isObject(thread) || thread.id !== threadId || !Object.hasOwn(PROVIDERS, thread.providerId) ||
        !['active', 'starting', 'idle'].includes(thread.status) ||
        !Number.isInteger(thread.queuedMessageCount) || (!queued && thread.queuedMessageCount !== 0) ||
        thread.archivedAt !== null || thread.deletedAt !== null) {
      fail(`The thread must be an unarchived thread of a supported provider (${Object.keys(PROVIDERS).join(', ')}) with no queued work or error.`);
    }
    if (provider === null) {
      provider = PROVIDERS[thread.providerId];
      if (options && provider.ledger !== (options.ledger !== null)) {
        fail(provider.ledger ? 'This provider needs --compaction-ledger from its self-compact plugin.'
          : 'This provider takes no --compaction-ledger.');
      }
      if (options && provider.failureNotice) report = { bb, threadId, note, resume: options.resume };
    } else if (provider !== PROVIDERS[thread.providerId]) {
      fail('The thread changed provider.');
    }
    const interactions = await bb(['thread', 'interactions', 'list', threadId]);
    if (!Array.isArray(interactions) || interactions.some(item =>
      !isObject(item) || !nonempty(item.status) || ['pending', 'resolving'].includes(item.status))) {
      fail('The thread has pending, resolving, or invalid interactions.');
    }
    return thread.status;
  }

  let cursor = preparing ? 0 : options.launchSeq;
  async function events() {
    const result = [];
    let page;
    do {
      page = await bb(['thread', 'log', threadId, '--after-seq', String(cursor), '--limit', String(PAGE_SIZE)]);
      if (!Array.isArray(page) || page.length > PAGE_SIZE) fail('BB returned an invalid event page.');
      for (const event of page) {
        if (!isObject(event) || event.threadId !== threadId || !Number.isSafeInteger(event.seq) ||
            event.seq <= cursor || !nonempty(event.type) || !isObject(event.scope) ||
            !['thread', 'turn'].includes(event.scope.kind) || !isObject(event.data) ||
            (event.scope.kind === 'turn' && !nonempty(event.scope.turnId))) {
          fail('BB returned a malformed or out-of-order event.');
        }
        if (['turn/started', 'turn/input/accepted', 'turn/completed', 'thread/compacted',
          'thread/context/cleared'].includes(event.type) && event.scope.kind !== 'turn') {
          fail('BB returned an event with invalid turn scope.');
        }
        if (event.type === 'client/turn/requested' &&
            (event.scope.kind !== 'thread' || !nonempty(event.data.requestId))) {
          fail('BB returned a malformed client request.');
        }
        if (event.type === 'turn/input/accepted' && !nonempty(event.data.clientRequestId)) {
          fail('BB returned a malformed input acceptance.');
        }
        if (event.type === 'turn/completed' &&
            !['completed', 'failed', 'interrupted'].includes(event.data.status)) {
          fail('BB returned a malformed turn completion.');
        }
        cursor = event.seq;
        result.push(event);
      }
    } while (page.length === PAGE_SIZE);
    return result;
  }

  function checkFailure(event) {
    if (['client/turn/rejected', 'system/error', 'provider/error', 'system/thread/interrupted',
      'thread/context/cleared'].includes(event.type)) {
      fail(`BB recorded ${event.type} while compaction was pending.`);
    }
  }

  const initialStatus = await threadState();
  if (preparing && initialStatus !== 'active') fail('Prepare must run during the invoking turn.');
  const history = preparing ? await events() : [];
  const start = preparing ? history.findLastIndex(event => event.type === 'turn/started') : -1;
  if (preparing && start < 0) fail('Cannot identify the invoking turn.');
  const caller = { turnId: preparing ? history[start].scope.turnId : options.turnId, completed: false };

  function checkCaller(event) {
    checkFailure(event);
    if (['client/turn/requested', 'turn/started', 'thread/compacted'].includes(event.type) ||
        (event.type === 'turn/input/accepted' && event.scope.turnId !== caller.turnId)) {
      fail('New work or a different turn appeared before compaction.');
    }
    if (event.type === 'turn/completed') {
      if (event.scope.turnId !== caller.turnId || event.data.status !== 'completed' || caller.completed) {
        fail('The invoking turn did not finish successfully.');
      }
      caller.completed = true;
    }
  }

  if (preparing) {
    const callerHistory = history.slice(start + 1);
    const commandSeq = provider === PROVIDERS['claude-code'] ? prepareCommandSeq(callerHistory, caller.turnId) : 0;
    const unaccepted = new Map();
    for (const event of callerHistory) {
      if (event.seq < commandSeq) {
        if (event.type === 'client/turn/requested') {
          unaccepted.set(event.data.requestId, event);
          continue;
        }
        if (event.type === 'turn/input/accepted' && event.scope.turnId === caller.turnId) {
          unaccepted.delete(event.data.clientRequestId);
        }
      }
      checkCaller(event);
    }
    unaccepted.forEach(checkCaller);
    if (caller.completed || await threadState() !== 'active') fail('The invoking turn ended during preparation.');
    (await events()).forEach(checkCaller);
    if (caller.completed) fail('The invoking turn ended during preparation.');
    console.log(JSON.stringify({ launchSeq: cursor, turnId: caller.turnId }));
    return;
  }
  while (true) {
    (await events()).forEach(checkCaller);
    const status = await threadState();
    if (caller.completed && status === 'idle') {
      (await events()).forEach(checkCaller);
      break;
    }
    await delay(Math.min(POLL_MS, Math.max(1, deadline - Date.now())));
  }

  const boundarySeq = cursor;
  const ledgerBaseline = provider.ledger ? (await readLedger(options.ledger)).length : 0;
  outcome.phase = 'compact-requested';
  const receipt = await bb(['thread', 'compact', threadId]);
  if (!isObject(receipt) || receipt.ok !== true || receipt.threadId !== threadId) {
    fail('BB did not confirm the compaction request.');
  }
  const proof = { boundarySeq, requestId: null, requestSeq: null, turnId: null,
    acceptedSeq: null, compactionSeq: null, completionSeq: null };
  let laterWork = false;

  // Once BB records the compaction turn as completed, the proof is closed. A queued notice can then
  // start its own turn before the helper polls again, and that turn does not undo the compaction.
  function checkCompaction(event) {
    if (proof.completionSeq) {
      laterWork ||= ['client/turn/requested', 'turn/started'].includes(event.type);
      return;
    }
    checkFailure(event);
    const { type, data, scope, seq } = event;
    if (type === 'client/turn/requested') {
      const input = data.input;
      const mention = input?.[0]?.mentions?.[0];
      const resource = mention?.resource;
      if (proof.requestId || !Array.isArray(input) || input.length !== 1 || input[0].type !== 'text' ||
          input[0].text !== '/compact' || !Array.isArray(input[0].mentions) || input[0].mentions.length !== 1 ||
          mention.start !== 0 || mention.end !== 8 || resource?.kind !== 'command' ||
          resource.trigger !== '/' || resource.name !== 'compact' || resource.origin !== 'builtin' ||
          resource.source !== 'command' || data.target?.kind !== 'new-turn' ||
          data.request?.method !== 'turn/start') {
        fail('Unexpected or duplicate request appeared after the compaction boundary.');
      }
      proof.requestId = data.requestId;
      proof.requestSeq = seq;
    } else if (type === 'turn/started') {
      if (!proof.requestId || proof.turnId) fail('Unexpected turn began during compaction.');
      proof.turnId = scope.turnId;
    } else if (type === 'turn/input/accepted') {
      if (!proof.turnId || scope.turnId !== proof.turnId || data.clientRequestId !== proof.requestId || proof.acceptedSeq) {
        fail('The compaction input was not accepted by the expected turn.');
      }
      proof.acceptedSeq = seq;
    } else if (type === 'thread/compacted') {
      if (!proof.acceptedSeq || scope.turnId !== proof.turnId || proof.compactionSeq || proof.completionSeq) {
        fail('The compaction boundary did not match the accepted turn.');
      }
      proof.compactionSeq = seq;
    } else if (type === 'turn/completed') {
      if (!proof.compactionSeq || scope.turnId !== proof.turnId || data.status !== 'completed' || proof.completionSeq) {
        fail('The compaction turn finished without matching successful proof.');
      }
      proof.completionSeq = seq;
    }
  }

  while (true) {
    (await events()).forEach(checkCompaction);
    // Messages may queue while compaction runs. The refusal to start with queued work is above.
    const status = await threadState({ queued: true });
    if (proof.completionSeq && (status === 'idle' || laterWork)) {
      (await events()).forEach(checkCompaction);
      break;
    }
    await delay(Math.min(POLL_MS, Math.max(1, deadline - Date.now())));
  }

  if (provider.ledger) proof.ledger = await requireLedgerEntry(options.ledger, ledgerBaseline, deadline);
  outcome.compacted = true;
  outcome.phase = 'proven';

  let resumeSent = false;
  if (options.resume) {
    outcome.resumeAttempted = true;
    const message = `Resume after self-compaction: read ${JSON.stringify(note)} before anything else and continue from its next step. Delete the note when its task is finished.`;
    let delivery;
    try {
      delivery = await bb(['thread', 'tell', threadId, '--mode', 'queue', '--message-file', '-'], message);
    } catch (error) {
      fail(`Resume delivery is uncertain: ${error.message}`);
    }
    if (!isObject(delivery) || delivery.threadId !== threadId) fail('Resume delivery is uncertain.');
    if (delivery.delivery === 'queued') {
      const id = delivery.queuedMessage?.id;
      fail(`Resume was queued${nonempty(id) ? ` as ${id}` : ' with no valid queue ID'} and may be delivered later. Check the queue before retrying.`);
    }
    if (delivery.delivery !== 'sent') fail('Resume delivery is uncertain.');
    resumeSent = true;
  }
  console.log(JSON.stringify({ compacted: true, resumeSent, evidence: proof }));
}

// A last line without its newline is still being written.
function completeLines(text) {
  return text.split('\n').slice(0, -1);
}

async function readLedger(path) {
  let text;
  try { text = await readFile(path, 'utf8'); } catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  return completeLines(text).map(line => {
    let entry;
    try { entry = JSON.parse(line); } catch { fail('The compaction ledger has a malformed line.'); }
    if (!isObject(entry) || !nonempty(entry.kind) || !nonempty(entry.reason)) fail('The compaction ledger has a malformed entry.');
    return entry;
  });
}

// Hermes awaits the post_compaction hook before it answers /compact, so the ledger line normally
// exists before BB records the turn. The grace only covers a slow write.
async function requireLedgerEntry(path, baseline, deadline) {
  const until = Math.min(deadline, Date.now() + LEDGER_GRACE_MS);
  while (true) {
    const fresh = (await readLedger(path)).slice(baseline);
    if (fresh.length > 1) fail('Hermes committed more than one compaction after the request, so the proof is ambiguous.');
    if (fresh.length === 1) {
      const [entry] = fresh;
      if (entry.reason !== 'manual' || entry.kind !== 'summarize') {
        fail(`The only compaction after the request was ${entry.reason} ${entry.kind}, not the requested manual one.`);
      }
      return entry;
    }
    if (Date.now() >= until) fail('BB reported compaction, but Hermes committed none. The request was a noop or was refused.');
    await delay(POLL_MS);
  }
}

async function sendFailureNotice(error) {
  const { bb, threadId, note, resume } = report;
  const awaitingUser = !resume;
  if (awaitingUser || outcome.resumeAttempted) return false;
  const late = { pastDeadline: true };
  try {
    const thread = (await bb(['thread', 'show', threadId], undefined, late))?.thread;
    const interactions = await bb(['thread', 'interactions', 'list', threadId], undefined, late);
    if (thread?.status !== 'idle' || thread.queuedMessageCount !== 0 || !Array.isArray(interactions) ||
        interactions.some(item => ['pending', 'resolving'].includes(item?.status))) return false;
    const text = `Self-compaction did not complete: ${error.message} No retry was made. The handoff note is kept at ${JSON.stringify(note)}. Read it with the self_compact tool's read action, continue the task, and schedule compaction again only at a later natural boundary.`;
    const delivery = await bb(['thread', 'tell', threadId, '--mode', 'queue', '--message-file', '-'], text, late);
    return isObject(delivery) && delivery.threadId === threadId && ['sent', 'queued'].includes(delivery.delivery);
  } catch {
    return false;
  }
}

main().catch(async error => {
  const failureNoticeSent = report ? await sendFailureNotice(error) : false;
  console.log(JSON.stringify({ compacted: outcome.compacted || (outcome.phase === 'waiting-caller' ? false : 'unknown'),
    phase: outcome.phase, error: error.message, failureNoticeSent }));
  console.error(`${error.message} No automatic retry was made. Keep the handoff note.`);
  process.exitCode = 1;
});

#!/usr/bin/env node
'use strict';

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');

const REQUEST_PREFIX = 'bb-background-';
const REPLY_TIMEOUT_MS = 5000;
const OUTPUT_DRAIN_MS = 1000;
const SIGNALS = ['SIGTERM', 'SIGINT', 'SIGHUP'];

function isExecutableFile(file) {
  try {
    fs.accessSync(file, fs.constants.X_OK);
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

// The same search bb's Claude Code bridge makes when no executable is configured.
function claudeCode() {
  const home = os.homedir();
  return [
    ...(process.env.PATH || '').split(path.delimiter).filter(Boolean).map(dir => path.join(dir, 'claude')),
    path.join(home, '.local', 'bin', 'claude'),
    path.join(home, '.claude', 'local', 'claude'),
    '/opt/homebrew/bin/claude',
    '/usr/local/bin/claude',
  ].find(isExecutableFile) || 'claude';
}

const args = process.argv.slice(2);
const target = process.env.BB_BACKGROUND_TOOLS_PROVIDER === 'claudex'
  ? path.join(os.homedir(), '.local', 'bin', 'claudex')
  : claudeCode();
const socketDir = process.env.BB_BACKGROUND_TOOLS_SOCKET_DIR;
const threadId = process.env.BB_THREAD_ID;
const isSession = args.some((arg, index) =>
  arg === '--input-format=stream-json' || (arg === '--input-format' && args[index + 1] === 'stream-json'));
const relays = isSession && Boolean(socketDir) && /^[A-Za-z0-9_-]+$/.test(threadId || '');

const child = spawn(target, args, { stdio: relays ? ['pipe', 'pipe', 'inherit'] : 'inherit' });
const forwarders = SIGNALS.map(signal => [signal, () => child.kill(signal)]);
for (const [signal, forward] of forwarders) process.on(signal, forward);

let cleanUp = () => {};
let finished = false;
function finish(code, signal) {
  if (finished) return;
  finished = true;
  cleanUp();
  for (const [name, forward] of forwarders) process.off(name, forward);
  if (signal) process.kill(process.pid, signal);
  else process.exitCode = code ?? 1;
}

child.on('error', error => {
  process.stderr.write(`bb background tools: could not start ${target}: ${error.message}\n`);
  finish(127, null);
});

if (relays) relay();
else child.on('exit', finish);

function forEachLine(stream, onLine, onEnd) {
  let pending = [];
  stream.on('data', chunk => {
    let start = 0;
    for (let end = chunk.indexOf(10); end !== -1; end = chunk.indexOf(10, start)) {
      pending.push(chunk.subarray(start, end + 1));
      onLine(Buffer.concat(pending));
      pending = [];
      start = end + 1;
    }
    if (start < chunk.length) pending.push(chunk.subarray(start));
  });
  stream.on('end', () => {
    if (pending.length) onLine(Buffer.concat(pending));
    pending = [];
    onEnd();
  });
}

function writer(source, sink) {
  let waiting = false;
  return data => {
    if (sink.write(data) || waiting) return;
    waiting = true;
    source.pause();
    sink.once('drain', () => {
      waiting = false;
      source.resume();
    });
  };
}

function relay() {
  const descriptions = new Map();
  const requests = new Map();
  let requestCount = 0;

  function settle(id, reply) {
    const request = requests.get(id);
    if (!request) return;
    requests.delete(id);
    clearTimeout(request.timer);
    request.connection.end(JSON.stringify(reply) + '\n');
  }

  function parseTaskOrOwnReply(line) {
    if (!line.includes('"task_') && !line.includes(REQUEST_PREFIX)) return null;
    try {
      return JSON.parse(line.toString('utf8'));
    } catch {
      return null;
    }
  }

  function isReplyToOwnRequest(message) {
    return message?.type === 'control_response' && Boolean(message.response?.request_id?.startsWith?.(REQUEST_PREFIX));
  }

  function answerRequest({ request_id: id, subtype, error }) {
    settle(id, subtype === 'success'
      ? { ok: true, tasks: requests.get(id)?.tasks }
      : { ok: false, error: String(error) });
  }

  function recordTask(message) {
    if (message?.type !== 'system') return;
    if (message.subtype === 'task_started') descriptions.set(message.task_id, String(message.description || ''));
    else if (message.subtype === 'task_notification') descriptions.delete(message.task_id);
    else if (message.subtype === 'task_updated' && message.patch?.is_backgrounded === true) {
      const task = { taskId: message.task_id, description: descriptions.get(message.task_id) || '' };
      for (const request of requests.values()) request.tasks.push(task);
    }
  }

  const toChild = writer(process.stdin, child.stdin);
  const toParent = writer(child.stdout, process.stdout);
  child.stdin.on('error', () => {});
  process.stdout.on('error', () => child.kill());
  forEachLine(process.stdin, toChild, () => child.stdin.end());
  const outputEnded = new Promise(resolve => {
    forEachLine(child.stdout, line => {
      const message = parseTaskOrOwnReply(line);
      if (isReplyToOwnRequest(message)) return answerRequest(message.response);
      recordTask(message);
      toParent(line);
    }, resolve);
  });

  const server = net.createServer(connection => {
    connection.on('error', () => {});
    if (!child.stdin.writable) {
      connection.end(JSON.stringify({ ok: false, error: 'The Claude Code session is closing.' }) + '\n');
      return;
    }
    const id = `${REQUEST_PREFIX}${process.pid}-${++requestCount}`;
    const timer = setTimeout(() => settle(id, { ok: false, error: 'Claude Code did not answer in time.' }), REPLY_TIMEOUT_MS);
    requests.set(id, { connection, timer, tasks: [] });
    toChild(JSON.stringify({ type: 'control_request', request_id: id, request: { subtype: 'background_tasks' } }) + '\n');
  });
  const unavailable = error => process.stderr.write(`bb background tools: ${error.message}\n`);
  server.on('error', unavailable);
  const socketPath = path.join(socketDir, `${threadId}.${process.pid}.sock`);
  try {
    fs.mkdirSync(socketDir, { recursive: true, mode: 0o700 });
    fs.rmSync(socketPath, { force: true });
    server.listen(socketPath);
  } catch (error) {
    unavailable(error);
  }

  cleanUp = () => {
    for (const id of [...requests.keys()]) settle(id, { ok: false, error: 'The Claude Code session ended.' });
    if (server.listening) server.close();
    fs.rmSync(socketPath, { force: true });
    process.stdin.destroy();
  };

  child.on('exit', (code, signal) => {
    const limit = new Promise(resolve => setTimeout(resolve, OUTPUT_DRAIN_MS).unref());
    Promise.race([outputEnded, limit]).then(() => {
      child.stdout.destroy();
      finish(code, signal);
    });
  });
}

import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const source = name => fileURLToPath(new URL(`../${name}`, import.meta.url));
const HOUR = 3_600_000;
const STARTED = 'Wed Nov 25 13:28:40 2026';

function machine(t) {
  const root = mkdtempSync(join(tmpdir(), 'windowserver-ports-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const bin = join(root, 'bin');
  const state = join(root, 'state/windowserver-ports');
  const tool = join(root, 'tool');
  for (const directory of [bin, state, tool]) mkdirSync(directory, { recursive: true });
  copyFileSync(source('windowserver-ports.mjs'), join(tool, 'windowserver-ports.mjs'));
  const fake = (name, body, directory = bin) => {
    writeFileSync(join(directory, name), `#!/bin/sh\n${body}\n`);
    chmodSync(join(directory, name), 0o755);
  };
  const value = (name, content) => writeFileSync(join(root, name), `${content}\n`);
  const sent = name => existsSync(join(root, name)) ? readFileSync(join(root, name), 'utf8') : '';
  value('ports', 9000);
  value('started', STARTED);
  value('os', '27.2.1');
  fake('pgrep', 'echo 321');
  fake('ps', `cat '${root}/started'`);
  fake('top', `printf 'PID    COMMAND      #PORTS\\n321    WindowServer %s  \\n' "$(cat '${root}/ports')"`);
  fake('sw_vers', `case "$1" in -productVersion) cat '${root}/os' ;; *) echo BUILD ;; esac`);
  fake('bb', `echo "$@" >> '${root}/bb.log'`);
  fake('osascript', `echo "$@" >> '${root}/osascript.log'`);
  const client = body => fake('windowserver-ports-probe', body, tool);
  const addPorts = count => `echo $(( $(cat '${root}/ports') + ${count} )) > '${root}/ports'`;
  const cli = (...args) => spawnSync(process.execPath, [join(tool, 'windowserver-ports.mjs'), ...args], {
    env: { HOME: root, XDG_STATE_HOME: join(root, 'state'), PATH: `${bin}:/usr/bin:/bin` },
    encoding: 'utf8',
  });
  const ok = (...args) => {
    const result = cli(...args);
    assert.equal(result.status, 0, result.stderr);
    return result.stdout;
  };
  const seed = (...readings) => writeFileSync(join(state, 'history.jsonl'), readings.map(
    ({ hoursAgo, ports, started = STARTED }) => `${JSON.stringify({
      at: new Date(Date.now() - hoursAgo * HOUR).toISOString(), os: '27.2.1 (BUILD)', pid: 321,
      startedAt: new Date(started).toISOString(), ports,
    })}\n`).join(''));
  const history = () => readFileSync(join(state, 'history.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  return { root, state, bin, value, fake, client, addPorts, cli, ok, seed, sent, history };
}

const status = m => JSON.parse(m.ok('status', '--json'));

test('status projects from the recent readings of the running WindowServer only', t => {
  const m = machine(t);
  m.value('ports', 20_000);
  m.seed(
    { hoursAgo: 30, ports: 100 },
    { hoursAgo: 3, ports: 250_000, started: 'Tue Nov 24 09:00:00 2026' },
    { hoursAgo: 2, ports: 10_000 },
  );
  const report = status(m);
  assert.ok(Math.abs(report.growth.perHour - 5000) < 25, String(report.growth.perHour));
  assert.equal(Math.round(report.projection.hoursToLimit), 57);
  assert.equal(report.level, 'ok');
  assert.equal(m.history().length, 3, 'status must not write the history');
});

test('status gives no growth rate from less than an hour of readings', t => {
  const m = machine(t);
  m.value('ports', 20_000);
  m.seed({ hoursAgo: 0.5, ports: 3000 });
  const report = status(m);
  assert.equal(report.growth, null);
  assert.equal(report.projection, null);
});

test('check alerts at the threshold, suppresses the repeat, and alerts again after a new login or six hours', t => {
  const m = machine(t);
  m.ok('check', '--threshold', '8000');
  m.ok('check', '--threshold', '8000');
  const sends = () => m.sent('bb.log').trim().split('\n').filter(Boolean).length;
  assert.equal(sends(), 1);
  assert.match(m.sent('bb.log'), /push-notifications send --title .*--body 9,000 of 305,834/);
  assert.equal(m.history().length, 2);

  m.value('started', 'Thu Nov 26 08:00:00 2026');
  m.ok('check', '--threshold', '8000');
  assert.equal(sends(), 2);

  const file = join(m.state, 'check.json');
  const saved = JSON.parse(readFileSync(file, 'utf8'));
  saved.alerts.sentAt.threshold = new Date(Date.now() - 6.1 * HOUR).toISOString();
  writeFileSync(file, JSON.stringify(saved));
  m.ok('check', '--threshold', '8000');
  assert.equal(sends(), 3);
});

test('check stays quiet below both limits and alerts when the projection is within a day', t => {
  const m = machine(t);
  m.ok('check');
  assert.equal(m.sent('bb.log'), '');
  m.value('ports', 100_000);
  m.seed({ hoursAgo: 2, ports: 70_000 });
  m.ok('check');
  assert.match(m.sent('bb.log'), /About 14 h left/);
});

test('check falls back to osascript, and retries an alert that nothing delivered', t => {
  const m = machine(t);
  m.fake('bb', 'echo offline >&2; exit 1');
  m.fake('osascript', 'exit 1');
  const failed = m.cli('check', '--threshold', '8000');
  assert.equal(failed.status, 1);
  assert.match(failed.stderr, /notification failed/);
  m.fake('osascript', `echo "$@" >> '${m.root}/osascript.log'`);
  m.ok('check', '--threshold', '8000');
  assert.match(m.sent('osascript.log'), /9,000 of 305,834/);
});

test('probe reports the leak when each client leaves a port and its fix when none does', t => {
  const m = machine(t);
  m.client(m.addPorts(1));
  const leaking = JSON.parse(m.ok('probe', '--count', '12', '--settle', '0', '--json'));
  assert.equal(leaking.verdict, 'present');
  assert.equal(leaking.rounds[0].net, 12);
  m.client('exit 0');
  assert.equal(JSON.parse(m.ok('probe', '--settle', '0', '--json')).verdict, 'gone');
});

test('probe is inconclusive on an unexplained count and stops within its launch budget', t => {
  const m = machine(t);
  m.client(`echo . >> '${m.root}/launches'; ${m.addPorts(10)}`);
  const result = JSON.parse(m.ok('probe', '--settle', '0', '--json'));
  assert.equal(result.verdict, 'inconclusive');
  assert.equal(m.sent('launches').trim().split('\n').length, 60);
});

test('probe fails instead of reporting a fix when the client cannot connect', t => {
  const m = machine(t);
  m.client('echo "no screen is visible" >&2; exit 1');
  const result = m.cli('probe', '--settle', '0');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /no screen is visible/);
});

test('check probes once after a macOS update, after login has settled', t => {
  const m = machine(t);
  m.client(m.addPorts(1));
  m.ok('check', '--settle', '0');
  m.value('os', '27.3');
  m.value('started', new Date(Date.now() - 5 * 60_000).toString());
  m.ok('check', '--settle', '0');
  assert.equal(m.sent('bb.log'), '');
  m.value('started', new Date(Date.now() - HOUR).toString());
  m.ok('check', '--settle', '0');
  m.ok('check', '--settle', '0');
  assert.equal(m.sent('bb.log').match(/macOS 27\.3 \(BUILD\): present/g).length, 1);
});

test('record bounds the history', t => {
  const m = machine(t);
  m.seed(...Array.from({ length: 2200 }, (_, index) => ({ hoursAgo: 400 - index / 10, ports: index })));
  m.ok('record');
  assert.equal(m.history().length, 2016);
  assert.equal(m.history().at(-1).ports, 9000);
});

test('install loads an agent that runs check, and uninstall removes it', t => {
  const m = machine(t);
  m.client('exit 0');
  m.fake('launchctl', `echo "$@" >> '${m.root}/launchctl.log'
case "$1" in
  print) test -f '${m.root}/loaded' ;;
  bootstrap) touch '${m.root}/loaded' ;;
  bootout) rm '${m.root}/loaded' ;;
esac`);
  const plist = join(m.root, 'Library/LaunchAgents/com.ramtoshiya.windowserver-ports.plist');
  m.ok('install');
  m.ok('install');
  const text = readFileSync(plist, 'utf8');
  assert.match(text, /<string>[^<]*windowserver-ports\.mjs<\/string><string>check<\/string>/);
  assert.match(text, /<key>StartInterval<\/key><integer>600<\/integer>/);
  assert.equal(status(m).monitor.stale, true);
  m.ok('record');
  assert.equal(status(m).monitor.stale, false);
  m.ok('uninstall');
  assert.equal(existsSync(plist), false);
  assert.equal(existsSync(join(m.root, 'loaded')), false);
});

test('clients counts connections by app name from the WindowServer log', t => {
  const m = machine(t);
  const line = message => JSON.stringify({ eventMessage: message });
  m.value('log.ndjson', [
    line('[ ConnectionDebug ] New conn 0x1, PID 10 in session 257 on console'),
    line('1[CreateApplication]: Process creation: 0x0-0x1 (Some App) connectionID: 1A pid: 10 in session 0x101'),
    line('[ ConnectionDebug ] New conn 0x2, PID 11 in session 257 on console'),
    line('[ ConnectionDebug ] New conn 0x3, PID 12 in session 257 on console'),
    JSON.stringify({ count: 4, finished: 1 }),
  ].join('\n'));
  m.fake('log', `cat '${m.root}/log.ndjson'`);
  m.fake('ps', 'echo "   11 /usr/bin/helper"');
  const report = JSON.parse(m.ok('clients', '--json'));
  assert.equal(report.connections, 3);
  assert.deepEqual(report.clients.map(row => [row.name, row.connections]).sort(), [
    ['(exited, no name in the log)', 1], ['Some App', 1], ['helper', 1],
  ]);
});

test('install.sh refuses to replace an unrelated command', t => {
  const m = machine(t);
  const bin = join(m.root, '.local/bin');
  mkdirSync(bin, { recursive: true });
  const command = join(bin, 'windowserver-ports');
  writeFileSync(command, 'unrelated command\n');
  const result = spawnSync('sh', [source('install.sh')], {
    env: { HOME: m.root, PATH: `${join(process.execPath, '..')}:/usr/bin:/bin` },
    encoding: 'utf8',
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Refusing to replace an unrelated command/);
  assert.equal(readFileSync(command, 'utf8'), 'unrelated command\n');
});

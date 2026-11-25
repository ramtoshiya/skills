#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const VERSION = '0.1.0';
const PORT_LIMIT = { ports: 305_834, measuredOn: '27.2.1' };
const DEFAULT_THRESHOLD = 200_000;
const PROJECTION_ALERT_HOURS = 24;
const ALERT_REPEAT_HOURS = 6;
const RATE_WINDOW_HOURS = 6;
const LOGIN_BURST_DILUTION_HOURS = 1;
const LOGIN_SETTLE_MINUTES = 30;
const CHECK_INTERVAL_SECONDS = 600;
const STALE_MINUTES = 30;
const CHECKS_PER_DAY = 24 * 3600 / CHECK_INTERVAL_SECONDS;
const HISTORY_KEEP = 14 * CHECKS_PER_DAY;
const HISTORY_TRIM_BATCH = CHECKS_PER_DAY;
const PROBE_COUNT = { default: 20, min: 10, max: 60 };
const PROBE_MAX_ROUNDS = 3;
const PROBE_MAX_LAUNCHES = 60;
const PROBE_SETTLE_SECONDS = 10;
const LABEL = 'com.ramtoshiya.windowserver-ports';
const BB_LAUNCHER_DIR = join(homedir(), '.bb/bin');
const AGENT_PATH = [BB_LAUNCHER_DIR, '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin'];

const USAGE = `Usage: windowserver-ports <command>

  status    [--json]                    ports now, growth, and projected time to the limit
  record                                append one reading to the history
  check     [--threshold N]             record, then notify when the limit is near
  probe     [--count N] [--settle S] [--json]
                                        measure whether each exiting client still leaves a port
  clients   [--last 1h] [--json]        count new WindowServer connections per client
  install                               run check every 10 minutes with a LaunchAgent
  uninstall                             remove that LaunchAgent
  --version
`;

const scriptPath = fileURLToPath(import.meta.url);
const probeClient = join(dirname(scriptPath), 'windowserver-ports-probe');
const stateDir = join(process.env.XDG_STATE_HOME || join(homedir(), '.local/state'), 'windowserver-ports');
const historyFile = join(stateDir, 'history.jsonl');
const checkFile = join(stateDir, 'check.json');
const agentFile = join(homedir(), 'Library/LaunchAgents', `${LABEL}.plist`);

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: 'utf8', timeout: 60_000, maxBuffer: 256 * 1024 * 1024, ...options,
  });
  if (result.error) throw new Error(`${command}: ${result.error.message}`);
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || '').trim();
    throw new Error(`${command} failed with status ${result.status ?? result.signal}${detail ? `: ${detail}` : ''}`);
  }
  return result.stdout;
}

function takeReading() {
  const pid = Number(run('pgrep', ['-x', 'WindowServer']).trim().split('\n')[0]);
  const started = run('ps', ['-o', 'lstart=', '-p', String(pid)], { env: { ...process.env, LC_ALL: 'C' } }).trim();
  const top = run('top', ['-l', '1', '-pid', String(pid), '-stats', 'pid,command,ports']);
  const ports = top.match(new RegExp(`^${pid}\\s+WindowServer\\s+(\\d+)[+-]?\\s*$`, 'm'));
  if (!ports) throw new Error(`top printed no port count for WindowServer pid ${pid}`);
  const version = run('sw_vers', ['-productVersion']).trim();
  const build = run('sw_vers', ['-buildVersion']).trim();
  return {
    at: new Date().toISOString(),
    os: `${version} (${build})`,
    pid,
    startedAt: new Date(started).toISOString(),
    ports: Number(ports[1]),
  };
}

const instanceOf = reading => `${reading.pid} ${reading.startedAt}`;
const hoursBetween = (from, to) => (Date.parse(to) - Date.parse(from)) / 3_600_000;

function readHistory() {
  if (!existsSync(historyFile)) return [];
  return readFileSync(historyFile, 'utf8').split('\n').flatMap(line => {
    try { return line ? [JSON.parse(line)] : []; } catch { return []; }
  });
}

function writeAtomically(file, content) {
  const temporary = `${file}.${process.pid}.tmp`;
  writeFileSync(temporary, content);
  renameSync(temporary, file);
}

function record(reading) {
  mkdirSync(stateDir, { recursive: true });
  appendFileSync(historyFile, `${JSON.stringify(reading)}\n`);
  const history = readHistory();
  if (history.length <= HISTORY_KEEP + HISTORY_TRIM_BATCH) return history;
  const kept = history.slice(-HISTORY_KEEP);
  writeAtomically(historyFile, kept.map(item => `${JSON.stringify(item)}\n`).join(''));
  return kept;
}

function growthOf(history, now) {
  const window = history.filter(item => instanceOf(item) === instanceOf(now)
    && hoursBetween(item.at, now.at) > 0 && hoursBetween(item.at, now.at) <= RATE_WINDOW_HOURS);
  if (!window.length) return null;
  const oldest = window.reduce((a, b) => (a.at <= b.at ? a : b));
  const spanHours = hoursBetween(oldest.at, now.at);
  if (spanHours < LOGIN_BURST_DILUTION_HOURS) return null;
  return { perHour: (now.ports - oldest.ports) / spanHours, spanHours };
}

function assess(history, now, threshold) {
  const growth = growthOf(history, now);
  const hoursToLimit = growth && growth.perHour > 0 ? Math.max(0, PORT_LIMIT.ports - now.ports) / growth.perHour : null;
  const reasons = [];
  if (now.ports >= threshold) reasons.push('threshold');
  if (hoursToLimit !== null && hoursToLimit <= PROJECTION_ALERT_HOURS) reasons.push('projection');
  return {
    growth,
    projection: hoursToLimit === null ? null
      : { hoursToLimit, at: new Date(Date.parse(now.at) + hoursToLimit * 3_600_000).toISOString() },
    reasons,
  };
}

const grouped = number => Math.round(number).toLocaleString('en-US');
const percent = ports => `${(100 * ports / PORT_LIMIT.ports).toFixed(1)}%`;

function monitorState(history) {
  const installed = existsSync(agentFile);
  const lastReadingAt = history.at(-1)?.at ?? null;
  const stale = installed
    && (!lastReadingAt || hoursBetween(lastReadingAt, new Date().toISOString()) * 60 > STALE_MINUTES);
  return { installed, stale, lastReadingAt };
}

function status({ json }) {
  const now = takeReading();
  const history = readHistory();
  const { growth, projection, reasons } = assess(history, now, DEFAULT_THRESHOLD);
  const report = {
    level: reasons.length ? 'warning' : 'ok',
    reasons,
    ports: now.ports,
    limit: PORT_LIMIT.ports,
    threshold: DEFAULT_THRESHOLD,
    os: now.os,
    windowServer: { pid: now.pid, startedAt: now.startedAt },
    growth,
    projection,
    monitor: monitorState(history),
  };
  if (json) return console.log(JSON.stringify(report, null, 2));
  const lines = [
    `WindowServer pid ${now.pid}, running since ${new Date(now.startedAt).toLocaleString()}, macOS ${now.os}`,
    `Ports: ${grouped(now.ports)} of ${grouped(PORT_LIMIT.ports)} `
      + `(${percent(now.ports)}, limit measured on macOS ${PORT_LIMIT.measuredOn})`,
    growth
      ? `Growth: ${growth.perHour >= 0 ? '+' : ''}${grouped(growth.perHour)}/hour over the last ${growth.spanHours.toFixed(1)} hours`
      : `Growth: unknown, needs ${LOGIN_BURST_DILUTION_HOURS} hour of readings for this WindowServer`,
    projection
      ? `Projected limit: in ${grouped(projection.hoursToLimit)} hours, ${new Date(projection.at).toLocaleString()}`
      : `Projected limit: ${growth ? 'none, the count is not growing' : 'unknown'}`,
    `Level: ${report.level}${reasons.length ? ` (${reasons.join(', ')}). Log out or restart to clear the ports` : ''}`,
    !report.monitor.installed ? 'Monitor: not installed. Run `windowserver-ports install`'
      : report.monitor.stale
        ? `Monitor: installed but has no reading from the last ${STALE_MINUTES} minutes. Run \`windowserver-ports install\` again and see ${join(stateDir, 'check.log')}`
        : 'Monitor: installed and recording',
  ];
  console.log(lines.join('\n'));
}

function notify(title, body) {
  const failures = [];
  try {
    run('bb', ['push-notifications', 'send', '--title', title, '--body', body]);
    return 'bb';
  } catch (error) {
    failures.push(error.message);
  }
  try {
    run('osascript', ['-e', 'on run argv', '-e', 'display notification (item 1 of argv) with title (item 2 of argv)',
      '-e', 'end run', body, title]);
    return 'osascript';
  } catch (error) {
    failures.push(error.message);
  }
  throw new Error(`notification failed: ${failures.join('. ')}`);
}

function alertMessage(now, { projection }) {
  const left = projection
    ? `About ${grouped(projection.hoursToLimit)} h left at the current rate. ` : '';
  return {
    title: `WindowServer ports at ${percent(now.ports)} of the limit`,
    body: `${grouped(now.ports)} of ${grouped(PORT_LIMIT.ports)}. ${left}Log out or restart before it fills.`,
  };
}

function readCheckState() {
  return existsSync(checkFile) ? JSON.parse(readFileSync(checkFile, 'utf8')) : {};
}

function writeCheckState(state) {
  writeAtomically(checkFile, `${JSON.stringify(state, null, 2)}\n`);
}

function alertIfDue(now, history, threshold, state) {
  const assessment = assess(history, now, threshold);
  const sentAt = state.alerts?.instance === instanceOf(now) ? state.alerts.sentAt : {};
  const due = assessment.reasons.filter(reason => !sentAt[reason]
    || hoursBetween(sentAt[reason], now.at) >= ALERT_REPEAT_HOURS);
  if (!due.length) return;
  const { title, body } = alertMessage(now, assessment);
  const channel = notify(title, body);
  writeCheckState(Object.assign(state, {
    alerts: {
      instance: instanceOf(now),
      sentAt: { ...sentAt, ...Object.fromEntries(assessment.reasons.map(reason => [reason, now.at])) },
    },
  }));
  console.log(`${now.at} notified through ${channel} (${due.join(', ')}): ${title}. ${body}`);
}

const PROBE_SUMMARY = {
  present: 'Each exiting client still leaves a port.',
  gone: 'Exiting clients no longer leave ports.',
  inconclusive: 'The port count moved too much to tell. Run `windowserver-ports probe` again.',
};

async function probeAfterUpdate(now, state, settle) {
  const previous = state.os;
  if (previous === now.os) return;
  const loginSettled = hoursBetween(now.startedAt, now.at) * 60 >= LOGIN_SETTLE_MINUTES;
  if (previous !== undefined && !loginSettled) return;
  writeCheckState(Object.assign(state, { os: now.os }));
  if (previous === undefined) return;
  let title;
  let body;
  const rounds = [];
  try {
    const result = await probe(PROBE_COUNT.default, settle, round => rounds.push(round));
    title = `WindowServer leak on macOS ${now.os}: ${result.verdict}`;
    body = PROBE_SUMMARY[result.verdict];
  } catch (error) {
    title = `WindowServer leak probe failed on macOS ${now.os}`;
    body = error.message;
  }
  const channel = notify(title, body);
  console.log(`${now.at} macOS changed from ${previous}, notified through ${channel}: ${title}. ${body} `
    + `Rounds: ${JSON.stringify(rounds)}`);
}

async function check({ threshold, settle }) {
  const now = takeReading();
  const history = record(now);
  const state = readCheckState();
  alertIfDue(now, history, threshold, state);
  await probeAfterUpdate(now, state, settle);
}

function judgeRound(count, drift, net) {
  if (Math.abs(drift) > count / 4) return 'noisy';
  if (net >= 0.75 * count && net <= 1.5 * count) return 'present';
  if (Math.abs(net) <= 0.25 * count) return 'gone';
  return 'unclear';
}

async function probe(count, settle, onRound = () => {}) {
  if (!existsSync(probeClient)) {
    throw new Error(`the probe client ${probeClient} is missing. Install the tool with tools/windowserver-ports/install.sh`);
  }
  const instance = instanceOf(takeReading());
  const sample = () => {
    const reading = takeReading();
    if (instanceOf(reading) !== instance) throw new Error('WindowServer restarted during the probe');
    return reading.ports;
  };
  const rounds = [];
  const maxRounds = Math.min(PROBE_MAX_ROUNDS, Math.floor(PROBE_MAX_LAUNCHES / count));
  while (rounds.length < maxRounds) {
    const idleStart = sample();
    await sleep(settle * 1000);
    const idleEnd = sample();
    for (let launch = 0; launch < count; launch += 1) run(probeClient, []);
    await sleep(settle * 1000);
    const drift = idleEnd - idleStart;
    const growth = sample() - idleEnd;
    const round = { drift, growth, net: growth - drift, verdict: judgeRound(count, drift, growth - drift) };
    rounds.push(round);
    onRound(round, rounds.length);
    if (round.verdict === 'present' || round.verdict === 'gone') {
      return { verdict: round.verdict, count, settleSeconds: settle, rounds };
    }
  }
  return { verdict: 'inconclusive', count, settleSeconds: settle, rounds };
}

async function probeCommand({ count, settle, json }) {
  const result = await probe(count, settle, (round, number) => {
    if (!json) console.log(`Round ${number}: ${count} clients grew the count by ${round.growth}, `
      + `idle drift was ${round.drift}, net ${round.net}: ${round.verdict}`);
  });
  const os = takeReading().os;
  if (json) console.log(JSON.stringify({ os, ...result }, null, 2));
  else console.log(`macOS ${os}: ${result.verdict}. ${PROBE_SUMMARY[result.verdict]}`);
}

function clients({ last, json }) {
  const output = run('log', ['show', '--last', last, '--style', 'ndjson', '--predicate',
    'process == "WindowServer" AND (eventMessage CONTAINS "New conn 0x" OR eventMessage CONTAINS "Process creation:")'],
  { timeout: 600_000 });
  const connections = [];
  const appNames = new Map();
  for (const line of output.split('\n')) {
    if (!line.startsWith('{')) continue;
    const message = JSON.parse(line).eventMessage ?? '';
    const opened = message.match(/New conn 0x[0-9a-f]+, PID (\d+)/);
    if (opened) connections.push(opened[1]);
    const created = message.match(/Process creation: \S+ \((.*)\) connectionID: [0-9A-F]+ pid: (\d+)/);
    if (created) appNames.set(created[2], created[1]);
  }
  const running = new Map(run('ps', ['-axo', 'pid=,comm=']).split('\n').flatMap(line => {
    const match = line.trim().match(/^(\d+)\s+(.+)$/);
    return match ? [[match[1], basename(match[2])]] : [];
  }));
  const totals = new Map();
  for (const pid of connections) {
    const name = appNames.get(pid) ?? running.get(pid) ?? '(exited, no name in the log)';
    totals.set(name, (totals.get(name) ?? 0) + 1);
  }
  const rows = [...totals].map(([name, count]) => ({ name, connections: count }))
    .sort((a, b) => b.connections - a.connections);
  if (json) return console.log(JSON.stringify({ last, connections: connections.length, clients: rows }, null, 2));
  console.log(`${grouped(connections.length)} new WindowServer connections in the last ${last}`);
  for (const row of rows) console.log(`${String(row.connections).padStart(7)}  ${row.name}`);
}

const escapeXml = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const xmlString = text => `<string>${escapeXml(text)}</string>`;

function agentPlist() {
  const log = join(stateDir, 'check.log');
  const environment = { PATH: AGENT_PATH.join(':') };
  if (process.env.XDG_STATE_HOME) environment.XDG_STATE_HOME = process.env.XDG_STATE_HOME;
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>${xmlString(LABEL)}
  <key>ProgramArguments</key>
  <array>${[process.execPath, scriptPath, 'check'].map(xmlString).join('')}</array>
  <key>EnvironmentVariables</key>
  <dict>${Object.entries(environment).map(([key, value]) => `<key>${key}</key>${xmlString(value)}`).join('')}</dict>
  <key>StartInterval</key><integer>${CHECK_INTERVAL_SECONDS}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key>${xmlString(log)}
  <key>StandardErrorPath</key>${xmlString(log)}
</dict>
</plist>
`;
}

const launchDomain = () => `gui/${process.getuid()}`;
const agentLoaded = () => spawnSync('launchctl', ['print', `${launchDomain()}/${LABEL}`]).status === 0;

function unloadAgent() {
  if (agentLoaded()) run('launchctl', ['bootout', `${launchDomain()}/${LABEL}`]);
}

function installAgent() {
  if (!existsSync(probeClient)) {
    throw new Error('run tools/windowserver-ports/install.sh first, then `windowserver-ports install`');
  }
  mkdirSync(stateDir, { recursive: true });
  mkdirSync(dirname(agentFile), { recursive: true });
  unloadAgent();
  writeFileSync(agentFile, agentPlist());
  run('launchctl', ['bootstrap', launchDomain(), agentFile]);
  console.log(`Loaded ${agentFile}\nIt runs \`check\` every ${CHECK_INTERVAL_SECONDS} seconds with ${process.execPath}`);
}

function uninstallAgent() {
  unloadAgent();
  rmSync(agentFile, { force: true });
  console.log(`Removed the LaunchAgent ${LABEL}. The history stays in ${stateDir}`);
}

function integer(value, name, min, max = Number.MAX_SAFE_INTEGER) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < min || number > max) {
    throw new Error(`--${name} must be a whole number from ${min}${max < Number.MAX_SAFE_INTEGER ? ` to ${max}` : ''}`);
  }
  return number;
}

const flag = { type: 'boolean', default: false };
const text = value => ({ type: 'string', default: String(value) });

const COMMANDS = {
  status: { options: { json: flag }, run: status },
  record: {
    options: {},
    run() {
      const reading = takeReading();
      record(reading);
      console.log(`${reading.at} WindowServer pid ${reading.pid}: ${grouped(reading.ports)} ports`);
    },
  },
  check: {
    options: { threshold: text(DEFAULT_THRESHOLD), settle: text(PROBE_SETTLE_SECONDS) },
    run: values => check({
      threshold: integer(values.threshold, 'threshold', 1),
      settle: integer(values.settle, 'settle', 0, 120),
    }),
  },
  probe: {
    options: { count: text(PROBE_COUNT.default), settle: text(PROBE_SETTLE_SECONDS), json: flag },
    run: values => probeCommand({
      count: integer(values.count, 'count', PROBE_COUNT.min, PROBE_COUNT.max),
      settle: integer(values.settle, 'settle', 0, 120),
      json: values.json,
    }),
  },
  clients: {
    options: { last: text('1h'), json: flag },
    run(values) {
      if (!/^[1-9]\d*[mhd]$/.test(values.last)) throw new Error('--last takes a duration such as 30m, 2h, or 1d');
      clients(values);
    },
  },
  install: { options: {}, run: installAgent },
  uninstall: { options: {}, run: uninstallAgent },
};

async function main([name, ...args]) {
  if (name === '--version') return console.log(`windowserver-ports ${VERSION}`);
  if (name === '--help' || name === '-h') return process.stdout.write(USAGE);
  if (!Object.hasOwn(COMMANDS, name ?? '')) {
    process.stderr.write(USAGE);
    process.exitCode = 2;
    return;
  }
  const command = COMMANDS[name];
  const { values } = parseArgs({ args, options: command.options });
  await command.run(values);
}

main(process.argv.slice(2)).catch(error => {
  console.error(`windowserver-ports: ${error.message}`);
  process.exitCode = 1;
});

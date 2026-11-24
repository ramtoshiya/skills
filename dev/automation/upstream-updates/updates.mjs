#!/usr/bin/env node
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { dirname, join, posix } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '../../..');
const MARKETPLACE = '.claude-plugin/marketplace.json';
const AUTOMATION = {
  name: 'Upstream skill updates',
  cron: '0 5 * * *',
  timezone: 'Asia/Seoul',
  script: 'exec node dev/automation/upstream-updates/updates.mjs check',
  timeout: '10m',
};
const MANIFESTS = ['.claude-plugin/plugin.json', '.codex-plugin/plugin.json'];
const ROUTING = join(ROOT, 'plugins/ramtoshiya/skills/worker-routing/scripts');
const BB = process.env.BB_CLI || 'bb';

export function repoUrl(repo) {
  return /^[\w.-]+\/[\w.-]+$/.test(repo) ? `https://github.com/${repo}.git` : repo;
}

export function loadEntries(marketplace, upstreams) {
  const thirdParty = marketplace.plugins.filter(plugin => plugin.source?.source === 'git-subdir');
  const names = new Set(thirdParty.map(plugin => plugin.name));
  for (const name of Object.keys(upstreams)) {
    if (!names.has(name)) throw new Error(`upstreams.json names ${name}, which is not a git-subdir marketplace entry`);
  }
  return thirdParty.map(plugin => {
    const mapping = upstreams[plugin.name];
    if (!mapping) throw new Error(`${plugin.name} has no record in upstreams.json`);
    const { branch, upstream, upstreamBranch, watch, newSkillsIn = watch, retireWhenClosed } = mapping;
    const relativePaths = paths => Array.isArray(paths) && paths.length
      && paths.every(path => typeof path === 'string' && path && !path.startsWith('/') && !path.split('/').includes('..'));
    if (![branch, upstream, upstreamBranch].every(value => typeof value === 'string' && value)
      || !relativePaths(watch) || !relativePaths(newSkillsIn)) {
      throw new Error(`${plugin.name} needs branch, upstream, upstreamBranch, and relative watch paths in upstreams.json`);
    }
    if (retireWhenClosed !== undefined && !/^[\w.-]+\/[\w.-]+#\d+$/.test(retireWhenClosed)) {
      throw new Error(`${plugin.name}: retireWhenClosed must look like owner/repo#123`);
    }
    const { url: repo, path, sha } = plugin.source;
    if (!/^[0-9a-f]{40}$/.test(sha ?? '')) throw new Error(`${plugin.name} must pin a 40-character sha`);
    return { name: plugin.name, repo, path, sha, skills: plugin.skills, branch, upstream, upstreamBranch, watch, newSkillsIn, retireWhenClosed };
  });
}

function git(dir, ...args) {
  return execFileSync('git', ['-C', dir, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function gitSucceeds(dir, ...args) {
  return spawnSync('git', ['-C', dir, ...args], { stdio: 'ignore' }).status === 0;
}

function setRemote(dir, name, url) {
  if (!gitSucceeds(dir, 'remote', 'set-url', name, url)) git(dir, 'remote', 'add', name, url);
}

export function cacheDir() {
  return join(process.env.XDG_CACHE_HOME || join(homedir(), '.cache'), 'ramtoshiya', 'upstream-updates');
}

export function mirror(cache, entry, extraCommits = []) {
  const dir = join(cache, `${entry.name}.git`);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
    git(dir, 'init', '--quiet', '--bare');
  }
  setRemote(dir, 'source', repoUrl(entry.repo));
  setRemote(dir, 'upstream', repoUrl(entry.upstream));
  git(dir, 'fetch', '--quiet', '--prune', 'source', `+refs/heads/${entry.branch}:refs/remotes/source/${entry.branch}`);
  git(dir, 'fetch', '--quiet', '--prune', 'upstream', `+refs/heads/${entry.upstreamBranch}:refs/remotes/upstream/${entry.upstreamBranch}`);
  for (const sha of [entry.sha, ...extraCommits]) {
    if (!gitSucceeds(dir, 'cat-file', '-e', `${sha}^{commit}`)) git(dir, 'fetch', '--quiet', 'source', sha);
  }
  return dir;
}

export function inspect(dir, entry) {
  const source = `refs/remotes/source/${entry.branch}`;
  const upstreamHead = git(dir, 'rev-parse', `refs/remotes/upstream/${entry.upstreamBranch}`);
  const pinOnBranch = gitSucceeds(dir, 'merge-base', '--is-ancestor', entry.sha, source);
  const base = spawnSync('git', ['-C', dir, 'merge-base', entry.sha, upstreamHead], { encoding: 'utf8' }).stdout.trim() || null;
  const lines = (...args) => git(dir, ...args).split('\n').filter(Boolean);
  const changedFiles = base ? lines('diff', '--name-only', base, upstreamHead, '--', ...entry.watch) : [];
  const newSkills = base
    ? lines('diff', '--name-only', '--diff-filter=A', base, upstreamHead, '--', ...entry.newSkillsIn)
      .filter(file => posix.basename(file) === 'SKILL.md').map(posix.dirname)
    : [];
  return {
    entry: entry.name,
    fork: `${entry.repo}:${entry.branch}`,
    upstream: `${entry.upstream}:${entry.upstreamBranch}`,
    pin: entry.sha,
    pinOnBranch,
    handledUpstream: base,
    upstreamHead,
    changedFiles,
    newSkills,
  };
}

export function closedIssue(entry, issueState) {
  if (!entry.retireWhenClosed || entry.repo === entry.upstream) return null;
  const [repo, number] = entry.retireWhenClosed.split('#');
  return issueState(repo, number) === 'closed' ? entry.retireWhenClosed : null;
}

function githubIssueState(repo, number) {
  const result = run('gh', ['api', `repos/${repo}/issues/${number}`, '--jq', '.state']);
  if (result.status !== 0) throw new Error(`gh could not read ${repo}#${number}: ${result.stderr.trim()}`);
  return result.stdout.trim();
}

export function needsUpdate(finding) {
  return !finding.pinOnBranch || !finding.handledUpstream || finding.changedFiles.length > 0
    || finding.newSkills.length > 0 || Boolean(finding.closedIssue);
}

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function workingTreeEntries() {
  return loadEntries(readJson(join(ROOT, MARKETPLACE)), readJson(join(HERE, 'upstreams.json')));
}

function run(command, args, input = '') {
  const result = spawnSync(command, args, { encoding: 'utf8', input });
  return { status: result.status, stdout: result.stdout ?? '', stderr: result.stderr || String(result.error ?? '') };
}

function newestModel(family, provider) {
  const result = run(join(ROUTING, 'newest-model'), [family, provider]);
  return result.status === 0 ? result.stdout.trim() : null;
}

export function chooseWorker() {
  const pace = run('uv', ['run', '--no-project', '--managed-python', '--python', '>=3.11', 'python',
    join(ROUTING, 'quota-pace.py'), '--eligible', 'claude,codex']);
  let side = 'claude';
  let why = `quota lookup failed, using claude: ${pace.stderr.trim().split('\n').pop()}`;
  if (pace.status === 0) {
    const report = JSON.parse(pace.stdout).route;
    if (!report.side) throw new Error(`No provider has confirmed quota: ${report.why}`);
    ({ side, why } = report);
  }
  if (side === 'claude') return { provider: 'claude-code', model: newestModel('sonnet', 'claude-code'), reasoning: 'high', why };
  const model = newestModel('terra', 'claudex');
  if (model) return { provider: 'claudex', model, reasoning: 'high', why };
  throw new Error('newest-model found no terra model on claudex');
}

function bb(...args) {
  const result = run(BB, args);
  if (result.status !== 0) throw new Error(`bb ${args.slice(0, 2).join(' ')} failed: ${(result.stderr || result.stdout).trim()}`);
  return result.stdout;
}

function notify(title, body) {
  run(BB, ['push-notifications', 'send', '--title', title, '--body', body.slice(0, 180)]);
}

function check() {
  const cache = cacheDir();
  const findings = workingTreeEntries()
    .map(entry => ({ ...inspect(mirror(cache, entry), entry), closedIssue: closedIssue(entry, githubIssueState) }))
    .filter(needsUpdate);
  if (!findings.length) return;
  const worker = chooseWorker();
  const today = new Date().toLocaleDateString('en-CA', { timeZone: AUTOMATION.timezone });
  const prompt = `${readFileSync(join(HERE, 'agent-prompt.md'), 'utf8')}
## Findings {:#findings}

The daily check found these entries out of date. \`handledUpstream\` is the
newest upstream commit the pinned commit already contains. \`changedFiles\` and
\`newSkills\` cover the watched paths between it and \`upstreamHead\`.
\`closedIssue\` names a closed upstream issue that ends the entry's fork.

\`\`\`json
${JSON.stringify(findings, null, 2)}
\`\`\`

You run on ${worker.provider} ${worker.model} at ${worker.reasoning} effort. Routing: ${worker.why}.
`;
  const folder = mkdtempSync(join(tmpdir(), 'upstream-updates-'));
  try {
    const promptFile = join(folder, 'prompt.md');
    writeFileSync(promptFile, prompt);
    const thread = JSON.parse(bb('thread', 'spawn', '--project', process.env.BB_PROJECT_ID,
      '--new-environment', 'worktree', '--base-branch', 'main',
      '--provider', worker.provider, '--model', worker.model, '--reasoning-level', worker.reasoning,
      '--title', `Upstream skill updates ${today}`, '--prompt-file', promptFile, '--json'));
    console.log(`Started ${thread.id ?? thread.thread?.id} for ${findings.map(({ entry }) => entry).join(', ')}`);
  } finally {
    rmSync(folder, { recursive: true, force: true });
  }
}

export function verifyEntry(dir, entry, previous) {
  const errors = [];
  const at = (sha, path) => spawnSync('git', ['-C', dir, 'cat-file', '-p', `${sha}:${path}`], { encoding: 'utf8' });
  const type = (sha, path) => spawnSync('git', ['-C', dir, 'cat-file', '-t', `${sha}:${path}`], { encoding: 'utf8' }).stdout.trim();
  if (!gitSucceeds(dir, 'merge-base', '--is-ancestor', entry.sha, `refs/remotes/source/${entry.branch}`)) {
    errors.push(`${entry.name}: ${entry.sha} is not on ${entry.repo}:${entry.branch}`);
  }
  if (type(entry.sha, entry.path) !== 'tree') return [...errors, `${entry.name}: ${entry.path} is not a folder at ${entry.sha}`];
  const skills = entry.skills ?? [];
  for (const skill of skills) {
    const file = posix.join(entry.path, skill, 'SKILL.md');
    if (type(entry.sha, file) !== 'blob') errors.push(`${entry.name}: ${file} is missing at ${entry.sha}`);
  }
  if (!skills.length && !git(dir, 'ls-tree', '-r', '--name-only', entry.sha, '--', entry.path).split('\n').some(file => file.endsWith('/SKILL.md'))) {
    errors.push(`${entry.name}: no SKILL.md under ${entry.path} at ${entry.sha}`);
  }
  const versions = sha => MANIFESTS.map(manifest => {
    const result = at(sha, posix.join(entry.path, manifest));
    return result.status === 0 ? JSON.parse(result.stdout).version : undefined;
  });
  const current = versions(entry.sha);
  if (new Set(current.filter(Boolean)).size > 1) errors.push(`${entry.name}: manifest versions differ: ${current.join(', ')}`);
  if (previous && previous.repo === entry.repo && previous.sha !== entry.sha
    && git(dir, 'rev-parse', `${previous.sha}:${previous.path}`) !== git(dir, 'rev-parse', `${entry.sha}:${entry.path}`)) {
    const before = versions(previous.sha);
    MANIFESTS.forEach((manifest, index) => {
      if (current[index] !== undefined && current[index] === before[index]) {
        errors.push(`${entry.name}: ${entry.path} changed but ${manifest} keeps version ${current[index]}`);
      }
    });
  }
  return errors;
}

function verify() {
  const published = JSON.parse(git(ROOT, 'show', `origin/main:${MARKETPLACE}`)).plugins;
  const cache = cacheDir();
  const errors = workingTreeEntries().flatMap(entry => {
    const old = published.find(plugin => plugin.name === entry.name)?.source;
    const previous = old?.sha ? { repo: old.url, path: old.path, sha: old.sha } : null;
    const dir = mirror(cache, entry, previous?.repo === entry.repo ? [previous.sha] : []);
    return verifyEntry(dir, entry, previous);
  });
  for (const error of errors) console.error(error);
  if (errors.length) process.exit(1);
  console.log('Third-party pins verified');
}

function install() {
  const checkout = dirname(git(ROOT, 'rev-parse', '--path-format=absolute', '--git-common-dir'));
  const projects = JSON.parse(bb('project', 'list', '--json'));
  const project = projects.find(({ sources }) => sources?.some(source => source.path === checkout));
  if (!project) throw new Error(`No bb project has ${checkout} as a source`);
  const existing = JSON.parse(bb('automation', 'list', '--project', project.id, '--json'))
    .find(automation => automation.name === AUTOMATION.name);
  const settings = ['--name', AUTOMATION.name, '--cron', AUTOMATION.cron, '--timezone', AUTOMATION.timezone,
    '--script', AUTOMATION.script, '--interpreter', 'bash', '--working-directory', 'project', '--timeout', AUTOMATION.timeout];
  const id = existing?.id ?? JSON.parse(bb('automation', 'create', '--project', project.id, ...settings, '--json')).id;
  if (existing) bb('automation', 'update', id, '--project', project.id, ...settings);
  if (existing && existing.enabled === false) bb('automation', 'resume', id, '--project', project.id);
  console.log(`${existing ? 'Updated' : 'Created'} ${id} in ${project.id}`);
}

const commands = { check, verify, install };
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const command = commands[process.argv[2]];
  if (!command) {
    console.error('usage: updates.mjs check | verify | install');
    process.exit(2);
  }
  try {
    command();
  } catch (error) {
    if (command === check) notify('Upstream skill check failed', error.message);
    console.error(error.stack ?? error.message);
    process.exit(1);
  }
}

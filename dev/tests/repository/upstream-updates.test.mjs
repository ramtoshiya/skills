import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { inspect, loadEntries, mirror, needsUpdate, verifyEntry } from '../../automation/upstream-updates/updates.mjs';

const root = new URL('../../../', import.meta.url);
const json = path => JSON.parse(readFileSync(new URL(path, root), 'utf8'));

function git(dir, ...args) {
  return execFileSync('git', ['-C', dir, '-c', 'user.name=test', '-c', 'user.email=test@example.com', ...args],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function commit(dir, files, message) {
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(dirname(join(dir, path)), { recursive: true });
    writeFileSync(join(dir, path), content);
  }
  git(dir, 'add', '-A');
  git(dir, 'commit', '--quiet', '-m', message);
  return git(dir, 'rev-parse', 'HEAD');
}

function fixture(t) {
  const dir = mkdtempSync(join(tmpdir(), 'upstream-updates-test-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const upstream = join(dir, 'upstream');
  const fork = join(dir, 'fork');
  mkdirSync(upstream);
  git(upstream, 'init', '--quiet', '--initial-branch=main');
  commit(upstream, {
    'skills/one/SKILL.md': 'one\n',
    'skills/.claude-plugin/plugin.json': '{"version":"1.0.0"}\n',
    'docs/readme.md': 'docs\n',
  }, 'initial');
  git(dir, 'clone', '--quiet', upstream, fork);
  const pin = commit(fork, { 'skills/one/SKILL.md': 'one, customized\n' }, 'Customize one');
  const entry = {
    name: 'demo', repo: fork, path: 'skills', sha: pin, skills: ['./one'],
    branch: 'main', upstream, upstreamBranch: 'main', watch: ['skills'], newSkillsIn: ['skills'],
  };
  const check = (current = entry) => inspect(mirror(join(dir, 'cache'), current), current);
  return { upstream, fork, entry, check, cache: join(dir, 'cache') };
}

test('every git-subdir marketplace entry has exactly one upstream record', () => {
  const marketplace = json('.claude-plugin/marketplace.json');
  const upstreams = json('dev/automation/upstream-updates/upstreams.json');
  const entries = loadEntries(marketplace, upstreams);
  assert.deepEqual(entries.map(({ name }) => name).sort(), Object.keys(upstreams).sort());
  assert.throws(() => loadEntries(marketplace, { ...upstreams, retired: upstreams[entries[0].name] }), /retired/);
  const { [entries[0].name]: _, ...missing } = upstreams;
  assert.throws(() => loadEntries(marketplace, missing), /no record/);
});

test('an upstream commit outside the watched paths leaves the entry current', t => {
  const { upstream, check } = fixture(t);
  commit(upstream, { 'docs/readme.md': 'new docs\n' }, 'Docs only');
  const finding = check();
  assert.deepEqual(finding.changedFiles, []);
  assert.equal(needsUpdate(finding), false);
});

test('an upstream change to a watched path starts an update until the pin contains it', t => {
  const { upstream, fork, entry, check } = fixture(t);
  const head = commit(upstream, { 'skills/one/SKILL.md': 'one, upstream edit\n' }, 'Edit one');
  const finding = check();
  assert.deepEqual(finding.changedFiles, ['skills/one/SKILL.md']);
  assert.equal(finding.upstreamHead, head);
  assert.equal(needsUpdate(finding), true);

  git(fork, 'fetch', '--quiet', 'origin');
  git(fork, 'merge', '--quiet', '-s', 'ours', '-m', 'Keep the customization', 'origin/main');
  const merged = { ...entry, sha: git(fork, 'rev-parse', 'HEAD') };
  const after = check(merged);
  assert.equal(after.handledUpstream, head);
  assert.equal(needsUpdate(after), false);
});

test('a skill added upstream is reported once', t => {
  const { upstream, check } = fixture(t);
  commit(upstream, { 'skills/two/SKILL.md': 'two\n' }, 'Add two');
  assert.deepEqual(check().newSkills, ['skills/two']);
});

test('a pin that is not on the branch starts an update', t => {
  const { fork, entry, check } = fixture(t);
  git(fork, 'checkout', '--quiet', '-b', 'side');
  const offBranch = commit(fork, { 'skills/one/SKILL.md': 'side\n' }, 'Side work');
  git(fork, 'checkout', '--quiet', 'main');
  const finding = check({ ...entry, sha: offBranch });
  assert.equal(finding.pinOnBranch, false);
  assert.equal(needsUpdate(finding), true);
});

test('verify rejects a missing listed skill and a changed folder that keeps its version', t => {
  const { fork, entry, cache } = fixture(t);
  const previous = { repo: entry.repo, path: entry.path, sha: entry.sha };
  const changed = commit(fork, { 'skills/one/SKILL.md': 'changed\n' }, 'Change one');
  const current = { ...entry, sha: changed, skills: ['./one', './missing'] };
  const errors = verifyEntry(mirror(cache, current, [previous.sha]), current, previous);
  assert.equal(errors.length, 2);
  assert.match(errors[0], /skills\/missing\/SKILL.md is missing/);
  assert.match(errors[1], /keeps version 1.0.0/);

  const bumped = commit(fork, { 'skills/.claude-plugin/plugin.json': '{"version":"1.0.1"}\n' }, 'Release 1.0.1');
  const released = { ...entry, sha: bumped };
  assert.deepEqual(verifyEntry(mirror(cache, released, [previous.sha]), released, previous), []);
});

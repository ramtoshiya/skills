import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const cli = path.resolve('cli/worktreeinclude/worktreeinclude.mjs');
const installer = path.resolve('cli/worktreeinclude/install.sh');
const secret = 'fixture-only-secret-never-log-739';
function fixture(t, manifest = '.env\nlocal files/\n', format = 'sha1') {
  const root = fs.mkdtempSync(path.join(tmpdir(), 'worktreeinclude-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const main = path.join(root, 'main repo '), target = path.join(root, 'linked 작업 ');
  fs.mkdirSync(main);
  const env = { ...process.env, HOME: root, GIT_CONFIG_NOSYSTEM: '1', GIT_CONFIG_GLOBAL: '/dev/null', GIT_AUTHOR_NAME: 'Fixture', GIT_AUTHOR_EMAIL: 'fixture@example.test', GIT_COMMITTER_NAME: 'Fixture', GIT_COMMITTER_EMAIL: 'fixture@example.test' };
  for (const key of Object.keys(env)) if (key.startsWith('GIT_') && !['GIT_CONFIG_NOSYSTEM', 'GIT_CONFIG_GLOBAL', 'GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'].includes(key)) delete env[key];
  function run(command, args, cwd = main, extra = {}) {
    const result = spawnSync(command, args, { cwd, env: { ...env, ...extra }, encoding: 'utf8' });
    assert.ifError(result.error);
    assert.ok(!(result.stdout + result.stderr).includes(secret), 'file contents must not reach logs');
    return result;
  }
  function git(...args) {
    const result = run('git', args);
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.replace(/\n$/, '');
  }
  function write(relative, content, cwd = main) {
    const file = path.join(cwd, relative);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, content);
  }
  git('init', '--object-format=' + format, '-b', 'main');
  write('.gitignore', '.env\nlocal files/\nescape\nempty/\n*.private\n');
  write('.worktreeinclude', manifest);
  write('tracked.txt', 'tracked');
  git('add', '.');
  git('commit', '-m', 'fixture');
  write('.env', secret);
  write('local files/한 글.txt', 'local fixture');
  const invoke = (args, cwd = main) => run(process.execPath, [cli, ...args], cwd);
  const add = () => git('worktree', 'add', '-b', 'linked', target);
  const hook = action => invoke(['hook', action]);
  return { root, main, target, env, run, git, write, invoke, add, hook };
}
function ok(result) { assert.equal(result.status, 0, result.stderr + result.stdout); return result; }

test('installed hook copies ignored files into a plain worktree add, preserving spaces and Unicode', t => {
  const f = fixture(t);
  ok(f.run('sh', [installer]));
  const installed = path.join(f.root, '.local/bin/worktreeinclude');
  assert.ok(fs.lstatSync(installed).isFile());
  ok(f.run(installed, ['hook', 'install']));
  f.add();
  assert.equal(fs.readFileSync(path.join(f.target, '.env'), 'utf8'), secret);
  assert.equal(fs.readFileSync(path.join(f.target, 'local files/한 글.txt'), 'utf8'), 'local fixture');
  assert.equal(fs.readFileSync(path.join(f.target, 'tracked.txt'), 'utf8'), 'tracked');
  assert.notEqual(fs.statSync(path.join(f.main, '.env')).ino, fs.statSync(path.join(f.target, '.env')).ino);
  assert.match(ok(f.hook('status')).stdout, /installed/);
  ok(f.run('sh', [installer]));
});

test('main checkout and later ordinary branch checkouts never copy', t => {
  const f = fixture(t);
  assert.match(ok(f.invoke(['apply'])).stdout, /noop main-worktree/);
  f.add();
  ok(f.hook('install'));
  const checkout = f.run('git', ['checkout', '-b', 'later'], f.target);
  ok(checkout);
  assert.equal(fs.existsSync(path.join(f.target, '.env')), false);
  assert.match(ok(f.invoke(['apply'], f.target)).stdout, /noop not-new-worktree/);
  f.git('checkout', '-b', 'main-later');
  assert.equal(fs.readFileSync(path.join(f.main, '.env'), 'utf8'), secret);
});

test('hook install and uninstall are idempotent and preserve existing hooks, arguments, cwd, and exit status', t => {
  const f = fixture(t);
  const original = '#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" >> "$HOME/hook-events"\nexit 7\n';
  f.write('.git/hooks/post-checkout', original);
  fs.chmodSync(path.join(f.main, '.git/hooks/post-checkout'), 0o755);
  f.write('.git/hooks/pre-commit', '#!/bin/sh\nexit 9\n');
  fs.chmodSync(path.join(f.main, '.git/hooks/pre-commit'), 0o755);
  ok(f.hook('install')); ok(f.hook('install'));
  const result = f.run('git', ['worktree', 'add', '-b', 'linked', f.target]);
  assert.equal(result.status, 7);
  assert.equal(fs.readFileSync(path.join(f.target, '.env'), 'utf8'), secret);
  const events = fs.readFileSync(path.join(f.root, 'hook-events'), 'utf8').trim().split('\n');
  assert.equal(fs.realpathSync(events[0]), fs.realpathSync(f.target));
  assert.match(events[1], /^0{40,64}$/);
  assert.equal(events[3], '1');
  assert.equal(f.run('git', ['commit', '--allow-empty', '-m', 'blocked']).status, 1);
  ok(f.hook('uninstall')); ok(f.hook('uninstall'));
  assert.equal(fs.readFileSync(path.join(f.main, '.git/hooks/post-checkout'), 'utf8'), original);
  assert.equal(f.run('git', ['config', '--local', '--get', 'core.hooksPath']).status, 1);
  assert.equal(fs.existsSync(path.join(f.main, '.git/worktreeinclude')), false);
  assert.match(ok(f.hook('status')).stdout, /not-installed/);
});

test('custom relative hooksPath is restored and forwarded in the target worktree', t => {
  const f = fixture(t);
  f.write('custom hooks /post-checkout', `#!${process.execPath}
const fs = require('node:fs');
const path = require('node:path');
fs.appendFileSync(path.join(process.env.HOME, 'custom-events'), fs.readFileSync(path.join(__dirname, 'sibling')));
`);
  f.write('custom hooks /sibling', 'original');
  fs.chmodSync(path.join(f.main, 'custom hooks /post-checkout'), 0o755);
  f.git('add', 'custom hooks '); f.git('commit', '-m', 'custom hook');
  f.git('config', '--local', 'core.hooksPath', 'custom hooks ');
  ok(f.hook('install')); f.add();
  assert.equal(fs.readFileSync(path.join(f.root, 'custom-events'), 'utf8'), 'original');
  ok(f.invoke(['hook', 'uninstall'], f.target));
  assert.equal(f.git('config', '--local', '--get', 'core.hooksPath'), 'custom hooks ');
});

test('same-content skips support both Claude-before and Git-before ordering without overwrites', t => {
  const f = fixture(t);
  f.add();
  f.write('.env', secret, f.target); // Simulated Claude copier before this tool.
  assert.match(ok(f.invoke(['apply'], f.target)).stdout, /same ".env"/);
  const original = fs.statSync(path.join(f.target, '.env')).ino;
  assert.match(ok(f.invoke(['apply'], f.target)).stdout, /copied=0/);
  assert.equal(fs.statSync(path.join(f.target, '.env')).ino, original);
  fs.copyFileSync(path.join(f.main, '.env'), path.join(f.target, '.env')); // Simulated Claude copier after Git.
  assert.equal(fs.readFileSync(path.join(f.target, '.env'), 'utf8'), secret);
  assert.match(ok(f.invoke(['apply'], f.target)).stdout, /copied=0/);
  f.write('.env', 'target-owned', f.target);
  const conflict = f.invoke(['apply'], f.target);
  assert.equal(conflict.status, 1);
  assert.match(conflict.stdout, /conflict ".env"/);
  assert.equal(fs.readFileSync(path.join(f.target, '.env'), 'utf8'), 'target-owned');
  assert.equal(fs.readFileSync(path.join(f.target, 'local files/한 글.txt'), 'utf8'), 'local fixture');
});

test('unsafe manifests, tracked selections, and source symlinks fail before copying', async t => {
  for (const pattern of ['../escape', '/absolute', 'C:/outside', 'local files/../../outside', 'tracked.txt', 'escape']) {
    await t.test(pattern, t => {
      const f = fixture(t, `.env\n${pattern}\n`);
      if (pattern === 'escape') fs.symlinkSync(f.root, path.join(f.main, 'escape'));
      f.add();
      const result = f.invoke(['apply'], f.target);
      assert.equal(result.status, 1, result.stdout + result.stderr);
      assert.equal(fs.existsSync(path.join(f.target, '.env')), false);
    });
  }
});

test('target symlink parents and leaf symlinks are rejected without touching outside files', async t => {
  for (const relative of ['.env', 'local files']) {
    await t.test(relative, t => {
      const f = fixture(t);
      f.add();
      const outside = path.join(f.root, 'outside');
      fs.mkdirSync(outside);
      fs.writeFileSync(path.join(outside, 'keep'), 'outside-owned');
      fs.symlinkSync(relative === '.env' ? path.join(outside, 'keep') : outside, path.join(f.target, relative));
      assert.equal(f.invoke(['apply'], f.target).status, 1);
      assert.equal(fs.readFileSync(path.join(outside, 'keep'), 'utf8'), 'outside-owned');
      assert.deepEqual(fs.readdirSync(outside), ['keep']);
    });
  }
});

test('manifest globs and exclusions select only Git-ignored paths, including empty directories', t => {
  const f = fixture(t, '*.private\n!omit.private\nempty/\nnot-ignored\n');
  f.write('keep.private', secret); f.write('omit.private', 'excluded'); f.write('not-ignored', 'public');
  fs.mkdirSync(path.join(f.main, 'empty'));
  f.add();
  ok(f.invoke(['apply'], f.target));
  assert.equal(fs.readFileSync(path.join(f.target, 'keep.private'), 'utf8'), secret);
  assert.equal(fs.existsSync(path.join(f.target, 'omit.private')), false);
  assert.equal(fs.existsSync(path.join(f.target, 'not-ignored')), false);
  assert.ok(fs.statSync(path.join(f.target, 'empty')).isDirectory());
});

test('hook copy failures are visible after Git has created the target', t => {
  const f = fixture(t, 'tracked.txt\n');
  ok(f.hook('install'));
  const result = f.run('git', ['worktree', 'add', '-b', 'linked', f.target]);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /copy failed after checkout/);
  assert.ok(fs.existsSync(path.join(f.target, 'tracked.txt')));
});

test('changed integration, changed config, and per-worktree config fail safely', async t => {
  for (const scenario of ['files', 'permissions', 'extra-directory', 'config', 'worktree']) {
    await t.test(scenario, t => {
      const f = fixture(t);
      ok(f.hook('install'));
      if (scenario === 'files') f.write('.git/worktreeinclude/hooks/post-checkout', 'user edit');
      if (scenario === 'permissions') fs.chmodSync(path.join(f.main, '.git/worktreeinclude/hooks/pre-commit'), 0o600);
      if (scenario === 'extra-directory') fs.mkdirSync(path.join(f.main, '.git/worktreeinclude/user-directory'));
      if (scenario === 'config') f.git('config', '--local', 'core.hooksPath', 'other-hooks');
      if (scenario === 'worktree') f.git('config', 'extensions.worktreeConfig', 'true');
      assert.equal(f.hook('status').status, 1);
      assert.equal(f.hook('install').status, 1);
      assert.equal(f.hook('uninstall').status, 1);
      assert.ok(fs.existsSync(path.join(f.main, '.git/worktreeinclude')));
      if (scenario === 'files') assert.equal(fs.readFileSync(path.join(f.main, '.git/worktreeinclude/hooks/post-checkout'), 'utf8'), 'user edit');
      if (scenario === 'config') assert.equal(f.git('config', '--get', 'core.hooksPath'), 'other-hooks');
    });
  }
});

test('global hooksPath stays effective after uninstall without adding local configuration', t => {
  const f = fixture(t);
  const global = path.join(f.root, 'global.gitconfig');
  f.write('global.gitconfig', '[core]\n\thooksPath = global-hooks\n', f.root);
  const hook = action => f.run(process.execPath, [cli, 'hook', action], f.main, { GIT_CONFIG_GLOBAL: global });
  ok(hook('install')); ok(hook('status')); ok(hook('uninstall'));
  assert.equal(f.run('git', ['config', '--local', '--get', 'core.hooksPath']).status, 1);
  assert.equal(fs.readFileSync(global, 'utf8'), '[core]\n\thooksPath = global-hooks\n');
});

test('source-untracked but target-tracked deleted files cannot be restored by the copier', t => {
  const f = fixture(t);
  f.add();
  f.write('.env', 'tracked target', f.target);
  ok(f.run('git', ['add', '-f', '.env'], f.target));
  fs.unlinkSync(path.join(f.target, '.env'));
  const result = f.invoke(['apply'], f.target);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Target tracked path rejected/);
  assert.equal(fs.existsSync(path.join(f.target, '.env')), false);
});

test('SHA-256 detached worktree creation is supported', t => {
  const f = fixture(t, '.env\n', 'sha256');
  ok(f.hook('install'));
  ok(f.run('git', ['worktree', 'add', '--detach', f.target]));
  assert.equal(fs.readFileSync(path.join(f.target, '.env'), 'utf8'), secret);
});

test('no-checkout and missing creation reflogs are conservative no-ops', t => {
  const f = fixture(t);
  ok(f.hook('install'));
  f.git('worktree', 'add', '--no-checkout', '-b', 'linked', f.target);
  assert.equal(fs.existsSync(path.join(f.target, '.env')), false);
  const dir = f.run('git', ['rev-parse', '--absolute-git-dir'], f.target).stdout.trim();
  fs.rmSync(path.join(dir, 'logs/HEAD'), { force: true });
  assert.match(ok(f.invoke(['apply'], f.target)).stdout, /noop not-new-worktree/);
});

test('symlinked manifests and non-regular ignored sources are rejected', async t => {
  for (const scenario of ['manifest', 'fifo', 'ancestor']) {
    await t.test(scenario, t => {
      const f = fixture(t, scenario === 'fifo' ? 'pipe.private\n' : scenario === 'ancestor' ? 'escape/.env\n' : '.env\n');
      if (scenario === 'manifest') {
        f.write('manifest-copy', '.env\n', f.root);
        fs.unlinkSync(path.join(f.main, '.worktreeinclude'));
        fs.symlinkSync(path.join(f.root, 'manifest-copy'), path.join(f.main, '.worktreeinclude'));
      }
      if (scenario === 'fifo') ok(f.run('mkfifo', [path.join(f.main, 'pipe.private')]));
      if (scenario === 'ancestor') fs.symlinkSync(f.main, path.join(f.main, 'escape'));
      f.add();
      const result = f.invoke(['apply'], f.target);
      assert.equal(result.status, 1);
      assert.equal(fs.existsSync(path.join(f.target, '.env')), false);
      assert.equal(fs.existsSync(path.join(f.target, 'escape')), false);
    });
  }
});

test('nested worktrees under ignored source directories are never copied', t => {
  const f = fixture(t, 'local files/\n');
  const nested = path.join(f.main, 'local files/nested');
  f.git('worktree', 'add', '-b', 'nested', nested);
  f.write('nested.private', secret, nested);
  f.add();
  const result = ok(f.invoke(['apply'], f.target));
  assert.match(result.stdout, /skip nested-repository/);
  assert.equal(fs.existsSync(path.join(f.target, 'local files/nested')), false);
});

test('installer refuses unrelated files, symlinks, and non-regular commands', async t => {
  for (const type of ['file', 'symlink', 'fifo']) {
    await t.test(type, t => {
      const f = fixture(t);
      const command = path.join(f.root, '.local/bin/worktreeinclude');
      fs.mkdirSync(path.dirname(command), { recursive: true });
      f.write('unrelated-command', 'unrelated', f.root);
      if (type === 'file') fs.writeFileSync(command, 'unrelated');
      if (type === 'symlink') fs.symlinkSync(path.join(f.root, 'unrelated-command'), command);
      if (type === 'fifo') ok(f.run('mkfifo', [command]));
      const result = f.run('sh', [installer]);
      assert.equal(result.status, 1);
      assert.match(result.stderr, /Refusing to replace an unrelated command/);
      assert.equal(fs.readFileSync(path.join(f.root, 'unrelated-command'), 'utf8'), 'unrelated');
      if (type === 'file') assert.equal(fs.readFileSync(command, 'utf8'), 'unrelated');
      if (type === 'symlink') assert.ok(fs.lstatSync(command).isSymbolicLink());
      if (type === 'fifo') assert.ok(fs.lstatSync(command).isFIFO());
    });
  }
});

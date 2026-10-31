#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { tmpdir } from 'node:os';

const name = 'worktreeinclude';
const owner = 'skills-worktreeinclude-v1';
const here = fileURLToPath(import.meta.url);
const env = { ...process.env };
// A hook inherits repository-local Git variables. Each -C call must select its own index.
for (const key of Object.keys(env)) {
  if (key.startsWith('GIT_') && !['GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM', 'GIT_CONFIG_NOSYSTEM'].includes(key)) delete env[key];
}
// A copy of cli/excalidraw-board/size-limit.mjs, because this command installs as one file.
// test/size-limit.test.mjs keeps it equal.
const hardLimit = 1024 ** 3;
function checkSize(name, bytes, softLimit, warn = message => process.stderr.write(`${message}\n`)) {
  if (bytes > hardLimit) throw new Error(`${name} is ${bytes} bytes, over the hard limit of ${hardLimit} bytes`);
  if (bytes > softLimit) warn(`warning: ${name} is ${bytes} bytes, over the soft limit of ${softLimit} bytes`);
  return bytes;
}
function git(cwd, args, input, allowed = [0]) {
  const result = spawnSync('git', ['-C', cwd, ...args], { env, input, encoding: 'utf8', maxBuffer: hardLimit });
  if (result.error || !allowed.includes(result.status)) throw new Error('Git operation failed');
  checkSize(`worktreeinclude git ${args[0]} output`, Buffer.byteLength(result.stdout), 64 * 1024 * 1024);
  return result.stdout;
}
const split = value => value.split('\0').filter(Boolean);
const gitLine = value => value.replace(/\n$/, '');
const say = (status, relative) => console.log(`${name}: ${status}${relative === undefined ? '' : ' ' + JSON.stringify(relative)}`);
function stat(file) {
  try { return fs.lstatSync(file); } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
function safeRelative(relative) {
  if (!relative || path.isAbsolute(relative) || /^[a-z]:/i.test(relative) || relative.includes('\\') || relative.includes('\0') || relative.split('/').some(p => p === '..' || p.toLowerCase() === '.git')) {
    throw new Error('Unsafe manifest or file path');
  }
}
function checked(root, relative) {
  safeRelative(relative);
  let current = root;
  for (const part of relative.split('/').filter(p => p && p !== '.')) {
    current = path.join(current, part);
    const info = stat(current);
    if (info?.isSymbolicLink()) throw new Error(`Symlink rejected: ${JSON.stringify(relative)}`);
    if (info && current !== path.join(root, relative) && !info.isDirectory()) throw new Error(`Non-directory parent: ${JSON.stringify(relative)}`);
  }
  const resolved = path.resolve(root, relative);
  if (!resolved.startsWith(root + path.sep)) throw new Error('Path outside worktree');
  return resolved;
}
function context() {
  const cwd = fs.realpathSync(gitLine(git(process.cwd(), ['rev-parse', '--show-toplevel'])));
  const common = fs.realpathSync(gitLine(git(cwd, ['rev-parse', '--path-format=absolute', '--git-common-dir'])));
  const dir = fs.realpathSync(gitLine(git(cwd, ['rev-parse', '--absolute-git-dir'])));
  return { cwd, common, dir };
}
function initialCheckout(cwd) {
  // Git records creation with an empty message, sometimes followed by its initial reset.
  // Any subsequent checkout, commit, reset, or missing reflog is conservatively a no-op.
  const raw = git(cwd, ['reflog', 'show', '--format=%gs', 'HEAD']);
  if (!raw) return false;
  const log = raw.replace(/\n$/, '').split('\n');
  return log.length <= 2 && log.at(-1) === '' && log.every(message => message === '' || message === 'reset: moving to HEAD');
}
function manifest(source) {
  const file = checked(source, '.worktreeinclude');
  if (!stat(file)) return null;
  if (!stat(file).isFile() || !split(git(source, ['ls-files', '-z', '--', '.worktreeinclude'])).includes('.worktreeinclude')) throw new Error('Manifest must be a tracked regular file');
  const contents = fs.readFileSync(file, 'utf8');
  for (const line of contents.split(/\r?\n/)) {
    if (!line || line.startsWith('#')) continue;
    const pattern = line.startsWith('!') ? line.slice(1) : line;
    safeRelative(pattern);
    const prefix = [];
    for (const part of pattern.split('/')) {
      if (/[*?\[]/.test(part)) break;
      if (part) prefix.push(part);
    }
    if (prefix.length) {
      const info = stat(checked(source, prefix.join('/')));
      if (info && !info.isFile() && !info.isDirectory()) throw new Error('Non-regular manifest path rejected');
    }
  }
  return contents;
}
function select(paths, contents) {
  if (!paths.length) return new Set();
  const root = fs.mkdtempSync(path.join(tmpdir(), 'worktreeinclude-match-'));
  try {
    git(root, ['-c', 'core.hooksPath=/dev/null', 'init', '--template=', '--quiet']);
    fs.writeFileSync(path.join(root, '.gitignore'), contents, { mode: 0o600 });
    return new Set(split(git(root, ['-c', 'core.excludesFile=/dev/null', 'check-ignore', '--no-index', '-z', '--stdin'], paths.join('\0') + '\0', [0, 1])));
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
}
function apply(args) {
  const { cwd, common, dir } = context();
  if (dir === common) return say('noop main-worktree');
  if (args.length && (args.length !== 3 || !/^0{40,64}$/.test(args[0]) || !/^[a-f0-9]{40,64}$/.test(args[1]) || args[2] !== '1' || args[1] !== git(cwd, ['rev-parse', 'HEAD']).trim())) return say('noop ordinary-checkout');
  if (!initialCheckout(cwd)) return say('noop not-new-worktree');
  const records = split(git(cwd, ['worktree', 'list', '--porcelain', '-z']));
  const first = records.find(record => record.startsWith('worktree '));
  if (!first || records[1] === 'bare') throw new Error('A non-bare main worktree is required');
  const source = fs.realpathSync(first.slice(9));
  if (fs.realpathSync(gitLine(git(source, ['rev-parse', '--absolute-git-dir']))) !== common) throw new Error('Cannot resolve main worktree');
  const rules = manifest(source);
  if (!rules) return say('noop no-manifest');
  const tracked = split(git(source, ['ls-files', '-z']));
  const targetTracked = split(git(cwd, ['ls-files', '-z']));
  const selectedTracked = select(tracked, rules);
  if (selectedTracked.size) throw new Error(`Tracked path rejected: ${JSON.stringify([...selectedTracked][0])}`);
  const candidates = new Set();
  function visit(relative) {
    safeRelative(relative);
    const file = path.join(source, relative);
    const info = stat(file);
    if (!info) return;
    if (info.isDirectory() && stat(path.join(file, '.git'))) { say('skip nested-repository', relative); return; }
    candidates.add(relative + (info.isDirectory() ? '/' : ''));
    if (info.isDirectory() && !info.isSymbolicLink()) {
      for (const entry of fs.readdirSync(file)) {
        if (entry.toLowerCase() === '.git') continue;
        visit(relative + '/' + entry);
      }
    }
  }
  // Git supplies ignored roots, including empty directories. Never walk the whole checkout.
  for (const relative of split(git(source, ['ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z']))) visit(relative.replace(/\/$/, ''));
  const plan = [];
  for (const selected of [...select([...candidates], rules)].sort()) {
    const relative = selected.replace(/\/$/, '');
    const from = checked(source, relative);
    const to = checked(cwd, relative);
    const info = stat(from);
    if (!info.isDirectory() && !info.isFile()) throw new Error(`Non-regular path rejected: ${JSON.stringify(relative)}`);
    if (targetTracked.some(p => p === relative || p.startsWith(relative + '/') || relative.startsWith(p + '/'))) throw new Error(`Target tracked path rejected: ${JSON.stringify(relative)}`);
    // Check each candidate against Git's actual ignore rules, not just the manifest.
    const ignored = git(source, ['check-ignore', '--no-index', '-z', '--stdin'], relative + (info.isDirectory() ? '/' : '') + '\0', [0, 1]);
    if (ignored) plan.push({ relative, from, to, directory: info.isDirectory() });
  }
  let copied = 0, skipped = 0, conflicts = 0;
  for (const item of plan) {
    const { relative, directory } = item;
    try {
      const from = checked(source, relative), to = checked(cwd, relative);
      if (directory) {
        const existing = stat(to);
        if (existing && !existing.isDirectory()) { conflicts++; say('conflict', relative); continue; }
        fs.mkdirSync(to, { recursive: true, mode: 0o700 });
        continue;
      }
      const fd = fs.openSync(from, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
      let data, mode;
      try {
        const info = fs.fstatSync(fd);
        if (!info.isFile()) throw new Error('Source changed type');
        data = fs.readFileSync(fd);
        mode = info.mode & 0o777;
      } finally { fs.closeSync(fd); }
      fs.mkdirSync(path.dirname(to), { recursive: true, mode: 0o700 });
      checked(cwd, relative);
      const temporary = path.join(path.dirname(to), `.worktreeinclude-${randomUUID()}`);
      try {
        fs.writeFileSync(temporary, data, { flag: 'wx', mode: 0o600 });
        fs.chmodSync(temporary, mode);
        checked(cwd, relative);
        try {
          // link is an atomic no-replace publish. The temporary inode is local to the target.
          fs.linkSync(temporary, to);
          copied++; say('copied', relative);
        } catch (error) {
          if (error.code !== 'EEXIST') throw error;
          const existing = stat(to);
          let same = false;
          if (existing?.isFile()) {
            const targetFd = fs.openSync(to, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
            try { same = fs.readFileSync(targetFd).equals(data); } finally { fs.closeSync(targetFd); }
          }
          if (same) { skipped++; say('same', relative); }
          else { conflicts++; say('conflict', relative); }
        }
      } finally { fs.rmSync(temporary, { force: true }); }
    } catch {
      conflicts++; say('error', relative);
    }
  }
  say(`summary copied=${copied} same=${skipped} conflicts=${conflicts}`);
  if (conflicts) process.exitCode = 1;
}

const hooks = ['applypatch-msg', 'pre-applypatch', 'post-applypatch', 'pre-commit', 'pre-merge-commit', 'prepare-commit-msg', 'commit-msg', 'post-commit', 'pre-rebase', 'post-checkout', 'post-merge', 'pre-push', 'pre-receive', 'update', 'proc-receive', 'post-receive', 'post-update', 'reference-transaction', 'push-to-checkout', 'pre-auto-gc', 'post-rewrite', 'sendemail-validate', 'fsmonitor-watchman', 'p4-changelist', 'p4-prepare-changelist', 'p4-post-changelist', 'p4-pre-submit', 'post-index-change'];
const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
function dispatcher(hook, original, runtime) {
  const invoke = hook === 'post-checkout' ? `\n${quote(process.execPath)} ${quote(runtime)} apply "$@"\ncopy_status=$?\nif [ "$copy_status" -ne 0 ]; then\n  printf '%s\\n' 'worktreeinclude: copy failed after checkout. Checkout already completed.' >&2\n  [ "$status" -ne 0 ] || status=$copy_status\nfi` : '';
  return `#!/bin/sh\n# ${owner}\nstatus=0\nif [ -x ${quote(original + '/' + hook)} ]; then\n  ${quote(original + '/' + hook)} "$@"\n  status=$?\nfi${invoke}\nexit "$status"\n`;
}
function config(cwd, scope = []) {
  return split(git(cwd, ['config', ...scope, '--null', scope.length ? '--get-all' : '--get', 'core.hooksPath'], undefined, [0, 1]));
}
function loadState(root) {
  if (!stat(root)) return null;
  if (stat(root).isSymbolicLink() || !stat(root).isDirectory()) throw new Error('Unsafe integration directory');
  const stateFile = checked(root, 'state.json');
  if (!stat(stateFile)?.isFile()) throw new Error('Unrecognized integration directory');
  let state;
  try { state = JSON.parse(fs.readFileSync(stateFile, 'utf8')); } catch { throw new Error('Invalid integration state'); }
  if (state.owner !== owner || !Array.isArray(state.files) || !Array.isArray(state.local)) throw new Error('Unrecognized integration state');
  return state;
}
function verifyFiles(root, state) {
  const actual = [];
  function walk(dir, prefix = '') {
    for (const entry of fs.readdirSync(dir)) {
      const relative = prefix + entry;
      const file = checked(root, relative);
      if (stat(file).isDirectory()) {
        if (relative !== 'hooks') throw new Error('Integration files changed. Unknown directory');
        walk(file, relative + '/');
      } else actual.push(relative);
    }
  }
  walk(root);
  if (actual.some(file => file !== 'state.json' && !state.files.some(record => record.path === file)) || state.files.some(record => {
    const file = checked(root, record.path);
    return !stat(file)?.isFile() || (stat(file).mode & 0o777) !== 0o700 || fs.readFileSync(file, 'utf8') !== record.content;
  })) throw new Error('Integration files changed. Refusing to remove or replace them');
}
function hookCommand(action) {
  const { cwd, common } = context();
  const root = path.join(common, name);
  const managed = path.join(root, 'hooks');
  if (git(cwd, ['config', '--bool', 'extensions.worktreeConfig'], undefined, [0, 1]).trim() === 'true') throw new Error('Per-worktree configuration is unsupported. No hooks changed');
  const lock = path.join(common, name + '.lock');
  fs.mkdirSync(lock);
  try {
    const state = loadState(root);
    const current = config(cwd);
    if (action === 'status') {
      if (!state) return say('hook not-installed');
      verifyFiles(root, state);
      if (current.length !== 1 || current[0] !== managed) throw new Error('Hook configuration changed. Integration is inactive');
      return say('hook installed');
    }
    if (state) {
      verifyFiles(root, state);
      if (current.length !== 1 || current[0] !== managed) throw new Error('Hook configuration changed. No hooks changed');
      if (action === 'install') return say('hook already-installed');
      if (state.local.length) git(cwd, ['config', '--local', 'core.hooksPath', state.local[0]]);
      else git(cwd, ['config', '--local', '--unset-all', 'core.hooksPath']);
      fs.rmSync(root, { recursive: true });
      return say('hook uninstalled');
    }
    if (action === 'uninstall') return say('hook not-installed');
    const local = config(cwd, ['--local']);
    if (current.length > 1 || local.length > 1) throw new Error('Multiple hook paths are unsupported. No hooks changed');
    const original = current.length ? split(git(cwd, ['config', '--null', '--path', '--get', 'core.hooksPath']))[0] : path.join(common, 'hooks');
    if (!original || original.includes('\n')) throw new Error('Unsupported hook path');
    const names = new Set(hooks);
    const originalDir = path.resolve(cwd, original);
    if (originalDir === root || originalDir.startsWith(root + path.sep)) throw new Error('Unsupported hook path inside integration directory');
    if (stat(originalDir)?.isDirectory()) for (const entry of fs.readdirSync(originalDir)) if (/^[a-z0-9-]+$/.test(entry)) names.add(entry);
    const files = [{ path: 'runtime.mjs', content: fs.readFileSync(here, 'utf8') }];
    for (const hook of names) files.push({ path: 'hooks/' + hook, content: dispatcher(hook, original, path.join(root, 'runtime.mjs')) });
    fs.mkdirSync(root, { mode: 0o700 });
    try {
      fs.mkdirSync(managed, { mode: 0o700 });
      for (const file of files) fs.writeFileSync(path.join(root, file.path), file.content, { flag: 'wx', mode: 0o700 });
      fs.writeFileSync(path.join(root, 'state.json'), JSON.stringify({ owner, local, files }), { flag: 'wx', mode: 0o600 });
      git(cwd, ['config', '--local', 'core.hooksPath', managed]);
    } catch (error) { fs.rmSync(root, { recursive: true }); throw error; }
    say('hook installed');
  } finally { fs.rmdirSync(lock); }
}
try {
  const args = process.argv.slice(2);
  if (args[0] === 'apply') apply(args.slice(1));
  else if (args[0] === 'hook' && args.length === 2 && ['install', 'uninstall', 'status'].includes(args[1])) hookCommand(args[1]);
  else if (args.length === 1 && args[0] === '--version') console.log('worktreeinclude 1');
  else if (!args.length || args[0] === '--help') console.log('Usage: worktreeinclude apply | hook install | hook uninstall | hook status');
  else throw new Error('Unknown command. Use --help');
} catch (error) {
  // Never print subprocess output, file data, stacks, or arbitrary system error messages.
  const known = /^(Git operation failed|Unsafe |Symlink rejected:|Non-directory parent:|Path outside|Manifest must|Unsupported manifest|Tracked path rejected:|Target tracked path rejected:|A non-bare|Cannot resolve|Per-worktree|Unrecognized integration|Invalid integration|Integration files changed|Hook configuration changed|Multiple hook paths|Unsupported hook path|Unknown command|worktreeinclude git \S+ output is \d+ bytes)/;
  console.error(`${name}: ${known.test(error.message) ? error.message : 'Operation failed. Check repository permissions and integration state'}`);
  process.exitCode = 1;
}

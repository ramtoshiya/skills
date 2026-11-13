#!/usr/bin/env python3
"""Local review server for explicitly approved plugin updates."""
import argparse
import contextlib
import datetime as dt
import fcntl
import http.server
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import shlex
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid

APP = 'plugin-update-review'
ROOT = Path(__file__).resolve().parent.parent
ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')
SHA = re.compile(r'^[0-9a-f]{40,64}$')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('w', encoding='utf-8') as f:
            os.chmod(temp, 0o600)
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write('\n')
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path):
    with Path(path).open(encoding='utf-8') as f:
        return json.load(f)


def require_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value) or value in ('.', '..'):
        raise ValueError('Invalid identifier')
    return value


def check_url(url):
    if not isinstance(url, str) or not url or '\n' in url or url.startswith('-'):
        raise ValueError('Invalid repository URL')
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        raise ValueError('Repository URLs must not contain credentials')
    return url


def check_argv(record):
    argv = record.get('argv')
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or '\x00' in x for x in argv):
        raise ValueError('Each command needs a nonempty string argv')
    if Path(argv[0]).name == 'env' and any(x in ('-i', '--ignore-environment') for x in argv[1:]) and 'AGENTMEMORY_SDK_CHILD=1' not in argv[1:]:
        raise ValueError('An env command that clears its environment must set AGENTMEMORY_SDK_CHILD=1')


def validate(config):
    if config.get('version') != 1:
        raise ValueError('Unsupported config version')
    market = config['marketplace']
    if not isinstance(market.get('checkout'), str) or not Path(market['checkout']).is_absolute():
        raise ValueError('marketplace.checkout must be an absolute path')
    require_id(market['branch']) if '/' not in market['branch'] else None
    if market.get('push'):
        if not market.get('remote'):
            raise ValueError('marketplace push requires a remote')
        require_id(market['remote'])
    interval = config.get('interval_seconds', 86400)
    if not isinstance(interval, int) or interval < 1:
        raise ValueError('interval_seconds must be positive')
    ids, names = set(), set()
    if not isinstance(config['sources'], list):
        raise ValueError('sources must be a list')
    for source in config['sources']:
        sid = require_id(source['id'])
        if sid in ids:
            raise ValueError('Duplicate source id')
        ids.add(sid)
        for key in ('fork_url', 'upstream_url'):
            check_url(source[key])
        for key in ('branch', 'upstream_branch'):
            branch = source[key]
            if not isinstance(branch, str) or not branch or branch.startswith('-') or any(c in branch for c in '\n\r :~^?*[\\'):
                raise ValueError('Invalid branch')
        if not isinstance(source['label'], str) or not source['plugin_names']:
            raise ValueError('Source label and plugin_names are required')
        for name in source['plugin_names']:
            require_id(name)
            if name in names:
                raise ValueError('Plugin belongs to more than one source')
            names.add(name)
        tests = set()
        for test in source.get('tests', []):
            tid = require_id(test['id'])
            if tid in tests or test['kind'] not in ('static', 'eval') or not isinstance(test['label'], str):
                raise ValueError('Invalid or duplicate test')
            tests.add(tid)
            check_argv(test)
    target_ids = set()
    for target in config.get('install_targets', []):
        tid = require_id(target['id'])
        if tid in target_ids or not isinstance(target.get('label'), str):
            raise ValueError('Invalid or duplicate install target')
        target_ids.add(tid)
        check_argv(target)
        if not isinstance(target.get('cwd'), str) or not Path(target['cwd']).is_absolute():
            raise ValueError('Install target cwd must be absolute')
        env = target.get('env', {})
        if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str) or '=' in k or '\x00' in k + v for k, v in env.items()):
            raise ValueError('Invalid install target environment')
    return config


def git(cwd, *args, check=True):
    env = os.environ.copy()
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0', 'GIT_AUTHOR_NAME': APP,
                'GIT_AUTHOR_EMAIL': 'plugin-update-review@localhost',
                'GIT_COMMITTER_NAME': APP, 'GIT_COMMITTER_EMAIL': 'plugin-update-review@localhost'})
    # Ignore inherited Git overrides, including an inherited work tree or hooks path.
    for key in list(env):
        if key.startswith('GIT_') and key not in ('GIT_CONFIG_NOSYSTEM', 'GIT_CONFIG_GLOBAL', 'GIT_TERMINAL_PROMPT', 'GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
            del env[key]
    # Publication may use the person's configured Git credential helper.
    # Preparation stays isolated from global Git configuration.
    publish_network = args[0] in ('push', 'ls-remote')
    if publish_network:
        env.pop('GIT_CONFIG_GLOBAL', None)
    options = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=always']
    if not publish_network:
        options += ['-c', 'credential.helper=']
    result = subprocess.run([*options, '-C', str(cwd), *args],
                            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        # Report common causes without copying credential-bearing remote diagnostics.
        diagnostics = result.stderr.lower()
        reasons = [('could not resolve host', 'cannot resolve host'),
                   ('permission denied', 'permission denied'),
                   ('authentication failed', 'authentication failed'),
                   ('could not read username', 'credentials unavailable'),
                   ('repository not found', 'repository not found'),
                   ('does not appear to be a git repository', 'repository unavailable'),
                   ('connection refused', 'connection refused'),
                   ('non-fast-forward', 'non-fast-forward push refused')]
        reason = next((label for needle, label in reasons if needle in diagnostics), None)
        raise RuntimeError('git ' + args[0] + ' failed (exit ' + str(result.returncode) + ')' + (': ' + reason if reason else ''))
    return result


def head(cwd):
    return git(cwd, 'rev-parse', 'HEAD').stdout.strip()


def clean(cwd):
    return not git(cwd, 'status', '--porcelain=v1', '--untracked-files=all').stdout.strip()


def remote_head(cwd, remote, branch):
    result = git(cwd, 'ls-remote', '--heads', remote, 'refs/heads/' + branch)
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise RuntimeError('Remote branch unavailable or ambiguous')
    sha = lines[0].split()[0]
    if not SHA.fullmatch(sha):
        raise RuntimeError('Invalid remote head')
    return sha


def pins(path, names):
    doc = read_json(path)
    result = {}
    for entry in doc['plugins']:
        if entry.get('name') in names:
            name = entry['name']
            if name in result or not isinstance(entry.get('source'), dict) or not SHA.fullmatch(entry['source'].get('sha', '')):
                raise ValueError('Invalid or duplicate marketplace entry: ' + name)
            result[name] = entry['source']['sha']
    if set(result) != set(names):
        raise ValueError('Marketplace entries missing: ' + ', '.join(sorted(set(names) - set(result))))
    return result


class JSONSpans:
    """Parse JSON and retain value spans so changing pins leaves all other bytes intact."""
    def __init__(self, text):
        self.text, self.i = text, 0
        self.decoder = json.JSONDecoder()

    def space(self):
        while self.i < len(self.text) and self.text[self.i].isspace():
            self.i += 1

    def parse(self):
        self.space()
        start = self.i
        if self.text[self.i] == '{':
            self.i += 1
            children = {}
            self.space()
            while self.text[self.i] != '}':
                key, end = self.decoder.raw_decode(self.text, self.i)
                if key in children:
                    raise ValueError('Duplicate JSON key')
                self.i = end
                self.space()
                if self.text[self.i] != ':':
                    raise ValueError('Invalid JSON')
                self.i += 1
                children[key] = self.parse()
                self.space()
                if self.text[self.i] != ',':
                    break
                self.i += 1
                self.space()
            if self.text[self.i] != '}':
                raise ValueError('Invalid JSON')
            self.i += 1
        elif self.text[self.i] == '[':
            self.i += 1
            children = []
            self.space()
            while self.text[self.i] != ']':
                children.append(self.parse())
                self.space()
                if self.text[self.i] != ',':
                    break
                self.i += 1
                self.space()
            if self.text[self.i] != ']':
                raise ValueError('Invalid JSON')
            self.i += 1
        else:
            _, self.i = self.decoder.raw_decode(self.text, self.i)
            children = None
        return (start, self.i, children)


def update_pins(path, names, revision):
    text = Path(path).read_bytes().decode('utf-8')
    parser = JSONSpans(text)
    tree = parser.parse()
    parser.space()
    if parser.i != len(text):
        raise ValueError('Trailing JSON data')
    edits = []
    for entry in tree[2]['plugins'][2]:
        fields = entry[2]
        name_span = fields.get('name')
        if name_span and json.loads(text[name_span[0]:name_span[1]]) in names:
            span = fields['source'][2]['sha']
            edits.append((span[0], span[1]))
    if len(edits) != len(names):
        raise ValueError('Marketplace entries changed')
    for start, end in sorted(edits, reverse=True):
        text = text[:start] + json.dumps(revision) + text[end:]
    Path(path).write_bytes(text.encode('utf-8'))


def secret_values(env, extra=()):
    names = re.compile(r'TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH', re.I)
    values = {v.encode() for k, v in env.items() if names.search(k) and v}
    values.update(v.encode() for v in extra if v)
    return sorted(values, key=len, reverse=True)


class Redactor:
    def __init__(self, output, values):
        self.output, self.values, self.pending = output, values, b''
        self.keep = max((len(v) for v in values), default=1) - 1

    def write(self, chunk, final=False):
        self.pending += chunk
        for value in self.values:
            self.pending = self.pending.replace(value, b'[REDACTED]')
        count = len(self.pending) if final else max(0, len(self.pending) - self.keep)
        self.output.write(self.pending[:count])
        self.pending = self.pending[count:]
        self.output.flush()


class Store:
    def __init__(self, config_path, state_dir):
        self.config_path, self.dir = Path(config_path), Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path = self.dir / 'state.json'
        self.config = validate(read_json(self.config_path))
        self.market = Path(self.config['marketplace']['checkout'])
        self.market_file = self.market / '.claude-plugin/marketplace.json'

    @contextlib.contextmanager
    def lock(self, name='mutation', blocking=True):
        with (self.dir / (name + '.lock')).open('a') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                raise RuntimeError('Another operation is already running') from None
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def state(self):
        return read_json(self.state_path) if self.state_path.exists() else {'version': 1, 'candidates': {}, 'problems': {}}

    def save(self, state):
        write_json(self.state_path, state)

    def event(self, kind, source, detail):
        path = self.dir / 'events.jsonl'
        with path.open('a', encoding='utf-8') as f:
            os.chmod(path, 0o600)
            f.write(json.dumps({'time': now(), 'kind': kind, 'source': source, 'detail': detail}, ensure_ascii=False) + '\n')

    def source(self, sid):
        return next((s for s in self.config['sources'] if s['id'] == sid), None)

    def cache(self, source):
        path = self.dir / 'caches' / (source['id'] + '.git')
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            git(path.parent, 'init', '--bare', str(path))
        return path

    def fetch(self, source):
        cache = self.cache(source)
        for key, branch, ref in [('fork_url', 'branch', 'fork'), ('upstream_url', 'upstream_branch', 'upstream')]:
            git(cache, 'fetch', '--no-tags', '--no-recurse-submodules', source[key],
                '+refs/heads/' + source[branch] + ':refs/review/' + ref)
        return cache, git(cache, 'rev-parse', 'refs/review/fork').stdout.strip(), git(cache, 'rev-parse', 'refs/review/upstream').stdout.strip()

    def describe(self, candidate):
        result = dict(candidate)
        path = Path(candidate['worktree'])
        if not path.is_dir():
            result.update(status='error', error='Candidate worktree is missing')
            return result
        try:
            result['head'] = head(path)
            result['dirty'] = not clean(path)
            conflicts = git(path, 'diff', '--name-only', '--diff-filter=U').stdout.splitlines()
            result['conflicts'] = conflicts
            result['status'] = 'conflict' if conflicts else ('modified' if result['dirty'] else 'ready')
            if not candidate.get('prepared_at'):
                result['status'] = 'error'
                result['error'] = candidate.get('preparation_error', 'Preparation was interrupted')
            result['worktree_status'] = git(path, 'status', '--short', '--untracked-files=all').stdout
            if (Path(git(path, 'rev-parse', '--git-dir').stdout.strip()) / 'MERGE_HEAD').exists():
                result['status'] = 'conflict' if conflicts else 'merge in progress'
        except (OSError, RuntimeError) as exc:
            result.update(status='error', error=str(exc))
        return result

    def scan(self):
        changed = False
        with self.lock():
            state = self.state()
            for source in self.config['sources']:
                sid = source['id']
                try:
                    cache, fork, upstream = self.fetch(source)
                    current_pins = pins(self.market_file, source['plugin_names'])
                    existing = state['candidates'].get(sid)
                    if existing and not existing.get('complete'):
                        if not existing.get('prepared_at'):
                            problem = existing.get('preparation_error', 'Preparation was interrupted. Inspect the worktree.')
                            if state['problems'].get(sid) != problem:
                                state['problems'][sid] = problem
                                self.event('problem', sid, problem)
                                changed = True
                            continue
                        # Never replace a pending worktree, even if refs move.
                        if existing['fork_head'] != fork or existing['upstream_head'] != upstream or existing['prior_pins'] != current_pins:
                            problem = 'Refs or pins changed while a candidate is pending. Review the existing worktree.'
                            if state['problems'].get(sid) != problem:
                                state['problems'][sid] = problem
                                self.event('problem', sid, problem)
                                changed = True
                        else:
                            state['problems'].pop(sid, None)
                        continue
                    missing = git(cache, 'merge-base', '--is-ancestor', upstream, fork, check=False)
                    if missing.returncode not in (0, 1):
                        raise RuntimeError('Cannot compare upstream and fork')
                    if missing.returncode == 0 and all(p == fork for p in current_pins.values()):
                        state['problems'].pop(sid, None)
                        continue
                    cid = uuid.uuid4().hex
                    worktree = self.dir / 'worktrees' / (sid + '-' + cid[:12])
                    worktree.parent.mkdir(parents=True, exist_ok=True)
                    branch = 'review/' + sid + '-' + cid[:12]
                    git(cache, 'worktree', 'add', '-b', branch, str(worktree), fork)
                    candidate = {'id': cid, 'source': sid, 'fork_head': fork, 'upstream_head': upstream,
                                 'prior_pins': current_pins, 'worktree': str(worktree), 'branch': branch,
                                 'created_at': now(), 'tests': [], 'apply': {}}
                    state['candidates'][sid] = candidate
                    # Persist before merge so an interrupted or failed merge stays inspectable.
                    self.save(state)
                    if missing.returncode == 1:
                        merge = git(worktree, 'merge', '--no-edit', '--no-ff', upstream, check=False)
                        if merge.returncode:
                            conflicts = git(worktree, 'diff', '--name-only', '--diff-filter=U').stdout.splitlines()
                            if not conflicts:
                                raise RuntimeError('Merge failed without resolvable conflicts')
                    candidate['prepared_head'] = head(worktree)
                    candidate['prepared_at'] = now()
                    state['problems'].pop(sid, None)
                    self.event('prepared', sid, {'candidate': cid, 'fork': fork, 'upstream': upstream,
                                                 'head': candidate['prepared_head'], 'worktree': str(worktree)})
                    changed = True
                except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
                    problem = str(exc)
                    pending = state['candidates'].get(sid)
                    if pending and not pending.get('prepared_at'):
                        pending['preparation_error'] = problem
                    if state['problems'].get(sid) != problem:
                        state['problems'][sid] = problem
                        self.event('problem', sid, problem)
                        changed = True
                finally:
                    self.save(state)
            self.event('scan', None, {'finished': now()})
        return changed

    def diff(self, candidate, source):
        path = Path(candidate['worktree'])
        chunks = []
        entries = {p['name']: p for p in read_json(self.market_file)['plugins'] if p.get('name') in source['plugin_names']}
        for name, old in candidate['prior_pins'].items():
            plugin_path = entries[name]['source'].get('path', '.')
            result = git(path, 'diff', '--no-ext-diff', '--no-textconv', '--no-color', old, 'HEAD', '--', plugin_path, check=False)
            chunks.append('=== ' + name + ': ' + old + ' to HEAD (' + plugin_path + ') ===\n' + (result.stdout if result.returncode == 0 else '[Diff unavailable: prior pin is not in the fetched history]\n'))
        for args, label in [(('diff', '--no-ext-diff', '--no-textconv', '--no-color'), 'unstaged'), (('diff', '--cached', '--no-ext-diff', '--no-textconv', '--no-color'), 'staged')]:
            chunks.append('\n=== ' + label + ' worktree changes ===\n' + git(path, *args, check=False).stdout)
        data = ''.join(chunks)
        limit = 500000
        return {'text': data[:limit], 'truncated': len(data) > limit}

    def snapshot(self):
        with self.lock():
            state = self.state()
            sources = []
            for source in self.config['sources']:
                sid = source['id']
                item = {'id': sid, 'label': source['label'], 'tests': source.get('tests', []), 'problem': state['problems'].get(sid)}
                candidate = state['candidates'].get(sid)
                if candidate:
                    item['candidate'] = self.describe(candidate)
                    item['candidate']['tests'] = [{k: v for k, v in read_json(self.dir / 'jobs' / (j + '.json')).items() if k != 'argv'} for j in candidate.get('tests', []) if (self.dir / 'jobs' / (j + '.json')).exists()]
                    try:
                        item['diff'] = self.diff(candidate, source)
                    except (OSError, ValueError, KeyError, RuntimeError):
                        item['diff'] = {'text': 'Diff unavailable. Inspect the worktree directly.', 'truncated': False}
                sources.append(item)
            # Registered argv and installation environments need not be exposed to the page.
            for item in sources:
                item['tests'] = [{k: test[k] for k in ('id', 'label', 'kind')} for test in item['tests']]
            return {'sources': sources}

    def test(self, sid, tid, reviewed):
        with self.lock():
            state = self.state()
            source, candidate = self.source(sid), state['candidates'].get(sid)
            if not source or not candidate or candidate.get('complete'):
                raise ValueError('No pending candidate')
            test = next((t for t in source.get('tests', []) if t['id'] == tid), None)
            if not test:
                raise ValueError('Unknown test')
            view = self.describe(candidate)
            if view.get('head') != reviewed or view.get('status') != 'ready':
                raise ValueError('Candidate changed or is not clean and ready')
            job_id = uuid.uuid4().hex
            job = {'id': job_id, 'source': sid, 'test': tid, 'label': test['label'], 'kind': test['kind'],
                   'candidate': candidate['id'], 'head': reviewed, 'cwd': candidate['worktree'],
                   'argv': test['argv'], 'status': 'queued', 'created_at': now(),
                   'log': str(self.dir / 'logs' / ('test-' + job_id + '.log'))}
            job_path = self.dir / 'jobs' / (job_id + '.json')
            write_json(job_path, job)
            candidate['tests'].append(job_id)
            self.save(state)
            command = ' '.join(shlex.quote(x) for x in [sys.executable, '-I', str(Path(__file__).resolve()), 'run-job', str(job_path)])
            script = 'tell application "Terminal" to do script ' + json.dumps(command, ensure_ascii=False)
            try:
                subprocess.run(['osascript', '-e', script], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.event('test-launched', sid, {'test': tid, 'head': reviewed, 'job': job_id})
            except (OSError, subprocess.CalledProcessError):
                job['status'], job['error'], job['finished_at'] = 'launch failed', 'Could not open Terminal', now()
                write_json(job_path, job)
                self.event('test-launch-failed', sid, {'test': tid, 'job': job_id})
                raise RuntimeError('Could not open Terminal') from None
            return job_id

    def apply(self, sid, reviewed):
        with self.lock():
            state = self.state()
            source, candidate = self.source(sid), state['candidates'].get(sid)
            if not source or not candidate or candidate.get('complete'):
                raise ValueError('No pending candidate')
            view = self.describe(candidate)
            if view.get('head') != reviewed or view.get('status') != 'ready':
                raise ValueError('Candidate changed or is not clean and ready')
            apply = candidate['apply']
            if apply.get('head') and apply['head'] != reviewed:
                raise ValueError('An earlier application used a different candidate revision')
            apply['head'] = reviewed
            apply.setdefault('started_at', now())
            apply.setdefault('installs', {})
            market_config = self.config['marketplace']
            market = self.market
            phase = 'preflight'
            try:
                if git(market, 'branch', '--show-current').stdout.strip() != market_config['branch'] or not clean(market):
                    raise RuntimeError('Marketplace checkout must be clean and on its configured branch')
                actual = pins(self.market_file, source['plugin_names'])
                expected = {name: reviewed for name in source['plugin_names']}
                if apply.get('market_commit'):
                    if head(market) != apply['market_commit'] or actual != expected:
                        raise RuntimeError('Marketplace checkout changed after its pin commit')
                elif actual != candidate['prior_pins']:
                    raise RuntimeError('Marketplace pins changed since preparation')
                if not apply.get('market_base'):
                    apply['market_base'] = head(market)
                elif not apply.get('market_commit') and head(market) != apply['market_base']:
                    raise RuntimeError('Marketplace checkout changed during application')
                if market_config.get('push'):
                    mremote = remote_head(market, market_config['remote'], market_config['branch'])
                    if mremote not in {apply['market_base'], apply.get('market_commit')}:
                        raise RuntimeError('Marketplace remote changed since application started')
                fork = remote_head(candidate['worktree'], source['fork_url'], source['branch'])
                if fork not in (candidate['fork_head'], reviewed):
                    raise RuntimeError('Fork remote changed since preparation')
                if apply.get('fork_published') and fork != reviewed:
                    raise RuntimeError('Previously published fork head changed')
                self.save(state)
                phase = 'fork push'
                if fork != reviewed:
                    git(candidate['worktree'], 'push', '--no-verify', source['fork_url'], reviewed + ':refs/heads/' + source['branch'])
                apply['fork_published'] = reviewed
                self.save(state)
                phase = 'marketplace commit'
                if not apply.get('market_commit'):
                    if actual != expected:
                        update_pins(self.market_file, source['plugin_names'], reviewed)
                        git(market, 'add', '--', '.claude-plugin/marketplace.json')
                        git(market, 'commit', '--no-verify', '-m', 'Update plugin pins')
                    apply['market_commit'] = head(market)
                    self.save(state)
                phase = 'marketplace push'
                if market_config.get('push') and not apply.get('market_pushed'):
                    mremote = remote_head(market, market_config['remote'], market_config['branch'])
                    if mremote != apply['market_commit']:
                        if mremote != apply['market_base']:
                            raise RuntimeError('Marketplace remote changed before push')
                        git(market, 'push', '--no-verify', market_config['remote'], apply['market_commit'] + ':refs/heads/' + market_config['branch'])
                    apply['market_pushed'] = apply['market_commit']
                    self.save(state)
                phase = 'installation'
                for target in self.config.get('install_targets', []):
                    tid = target['id']
                    fingerprint = hashlib.sha256(json.dumps(target, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    previous = apply['installs'].get(tid, {})
                    if previous.get('status') == 'complete':
                        if previous.get('fingerprint') != fingerprint:
                            raise RuntimeError('Completed installation target ' + tid + ' changed since it ran')
                        continue
                    log = self.dir / 'logs' / ('apply-' + candidate['id'] + '-' + tid + '.log')
                    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    apply['installs'][tid] = {'status': 'running', 'started_at': now(), 'log': str(log), 'fingerprint': fingerprint}
                    self.save(state)
                    env = os.environ.copy()
                    env.update(target.get('env', {}))
                    env['AGENTMEMORY_SDK_CHILD'] = '1'
                    # Output may contain secrets, so keep it in a private local file, not events or HTTP.
                    with log.open('ab') as output:
                        os.chmod(log, 0o600)
                        redactor = Redactor(output, secret_values(env, target.get('env', {}).values()))
                        proc = subprocess.Popen(target['argv'], cwd=target['cwd'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                        for chunk in iter(lambda: os.read(proc.stdout.fileno(), 4096), b''):
                            redactor.write(chunk)
                        proc.stdout.close()
                        code = proc.wait()
                        redactor.write(b'', final=True)
                    apply['installs'][tid].update(status='complete' if code == 0 else 'failed', exit_code=code, finished_at=now())
                    self.save(state)
                    if code:
                        raise RuntimeError('Installation target ' + tid + ' failed with exit ' + str(code))
                apply.update(status='complete', finished_at=now())
                candidate['complete'] = True
                self.save(state)
                self.event('apply', sid, {'head': reviewed, 'status': 'complete', 'market_commit': apply['market_commit']})
                return 'Application complete'
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                apply.update(status='failed', phase=phase, error=str(exc), updated_at=now())
                self.save(state)
                self.event('apply', sid, {'head': reviewed, 'status': 'failed', 'phase': phase, 'error': str(exc)})
                raise


def run_job(path):
    path = Path(path)
    job = read_json(path)
    log = Path(job['log'])
    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    job.update(status='running', started_at=now())
    write_json(path, job)
    code = 1
    try:
        if head(job['cwd']) != job['head'] or not clean(job['cwd']):
            raise RuntimeError('Candidate changed after this test was requested')
        env = os.environ.copy()
        env['AGENTMEMORY_SDK_CHILD'] = '1'
        with log.open('ab') as output:
            os.chmod(log, 0o600)
            redactor = Redactor(output, secret_values(env))
            proc = subprocess.Popen(job['argv'], cwd=job['cwd'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            for chunk in iter(lambda: os.read(proc.stdout.fileno(), 4096), b''):
                redactor.write(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            proc.stdout.close()
            code = proc.wait()
            redactor.write(b'', final=True)
    except (OSError, RuntimeError) as exc:
        with log.open('ab') as output:
            os.chmod(log, 0o600)
            output.write((str(exc) + '\n').encode())
        print(str(exc), flush=True)
    job.update(status='finished', exit_code=code, finished_at=now())
    write_json(path, job)
    print('\nTest exited with status ' + str(code) + '. You may close this window.', flush=True)
    return code


def notify(message):
    script = 'display notification ' + json.dumps(message) + ' with title "Plugin update review"'
    try:
        subprocess.run(['osascript', '-e', script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass


def browser(url):
    try:
        return subprocess.run(['open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
    except OSError:
        return False


def serve(store, port):
    token = secrets.token_urlsafe(32)
    origin = 'http://127.0.0.1:' + str(port)
    url = origin + '/?token=' + token
    html = (ROOT / 'web' / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', json.dumps(token))

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def reply(self, status, body, content_type='application/json'):
            data = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def allowed_host(self):
            return self.headers.get('Host') == '127.0.0.1:' + str(port)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if not self.allowed_host():
                return self.reply(403, '{}')
            if parsed.path == '/' and secrets.compare_digest(urllib.parse.parse_qs(parsed.query).get('token', [''])[0], token):
                return self.reply(200, html, 'text/html')
            if parsed.path == '/api/state' and secrets.compare_digest(self.headers.get('X-Review-Token', ''), token):
                return self.reply(200, json.dumps(store.snapshot(), ensure_ascii=False))
            self.reply(403, '{}')

        def do_POST(self):
            if not self.allowed_host() or self.headers.get('Origin') != origin or not secrets.compare_digest(self.headers.get('X-Review-Token', ''), token):
                return self.reply(403, '{}')
            try:
                if self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Expected JSON')
                size = int(self.headers.get('Content-Length', '0'))
                if size < 1 or size > 16384:
                    raise ValueError('Invalid request size')
                request = json.loads(self.rfile.read(size))
                sid = require_id(request['source'])
                reviewed = request.get('head')
                if not isinstance(reviewed, str) or not SHA.fullmatch(reviewed):
                    raise ValueError('Invalid reviewed revision')
                if self.path == '/api/test':
                    store.test(sid, require_id(request['test']), reviewed)
                    message = 'Test opened in Terminal'
                elif self.path == '/api/apply':
                    try:
                        message = store.apply(sid, reviewed)
                        notify('Application complete for ' + sid)
                    except (ValueError, RuntimeError, OSError):
                        notify('Application failed for ' + sid + '. See the dashboard.')
                        raise
                else:
                    return self.reply(404, '{}')
                self.reply(200, json.dumps({'message': message}))
            except (KeyError, ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
                self.reply(400, json.dumps({'error': str(exc)}))

    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    stop = threading.Event()

    def timer():
        while not stop.is_set():
            try:
                if store.scan() and not stop.is_set():
                    notify('Updates or preparation problems need review.')
                    if not browser(url):
                        store.event('browser-error', None, 'Could not open the review page')
            except (OSError, RuntimeError) as exc:
                store.event('scan-error', None, str(exc))
            stop.wait(store.config.get('interval_seconds', 86400))

    session_path = store.dir / 'session.json'
    write_json(session_path, {'pid': os.getpid(), 'url': url})
    previous_signal = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    scanner = threading.Thread(target=timer, daemon=True)
    scanner.start()
    print('Review server listening on 127.0.0.1:' + str(port) + '. Use plugin-update-review open.', flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stop.set()
        server.server_close()
        signal.signal(signal.SIGTERM, previous_signal)
        session_path.unlink(missing_ok=True)
        scanner.join(timeout=15)


def github_url(value):
    if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        return 'https://github.com/' + value + '.git'
    return check_url(value)


def configure(repo, path):
    repo = Path(repo).resolve()
    manifest = read_json(repo / '.claude-plugin/marketplace.json')
    forks = read_json(repo / '.github/upstream-forks.json')
    branch = git(repo, 'branch', '--show-current').stdout.strip()
    if not branch:
        raise ValueError('Marketplace checkout must be on a branch')
    sources = []
    for fork in forks:
        matched = [entry['name'] for entry in manifest['plugins'] if isinstance(entry.get('source'), dict) and entry['source'].get('url') == fork['fork']]
        if not matched:
            continue
        sid = re.sub(r'[^a-zA-Z0-9._-]', '-', fork['fork'])
        sources.append({'id': sid, 'label': fork['fork'], 'fork_url': github_url(fork['fork']),
                        'branch': fork['branch'], 'upstream_url': github_url(fork['upstream']),
                        'upstream_branch': fork['upstreamBranch'], 'plugin_names': matched, 'tests': []})
    config = {'version': 1, 'marketplace': {'checkout': str(repo), 'branch': branch, 'remote': 'origin', 'push': False},
              'sources': sources, 'install_targets': [], 'interval_seconds': 86400}
    validate(config)
    if Path(path).exists():
        raise ValueError('Config already exists: ' + str(path))
    write_json(path, config)
    print('Wrote ' + str(path) + ' with ' + str(len(sources)) + ' sources')


def main():
    home = Path.home()
    default_config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / APP / 'config.json'
    default_state = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state')) / APP
    parser = argparse.ArgumentParser(prog=APP)
    parser.add_argument('--version', action='version', version=APP + ' 1')
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('configure', help='derive a local config from a marketplace checkout')
    init.add_argument('--repo', default='.')
    init.add_argument('--config', default=str(default_config))
    server = sub.add_parser('serve', help='scan and serve the local review page')
    server.add_argument('--config', default=str(default_config))
    server.add_argument('--state-dir', default=str(default_state))
    server.add_argument('--port', type=int, default=8765)
    opening = sub.add_parser('open', help='open the running review page')
    opening.add_argument('--state-dir', default=str(default_state))
    job = sub.add_parser('run-job', help=argparse.SUPPRESS)
    job.add_argument('path')
    args = parser.parse_args()
    try:
        if args.command == 'configure':
            configure(args.repo, args.config)
        elif args.command == 'run-job':
            return run_job(args.path)
        elif args.command == 'open':
            session = read_json(Path(args.state_dir) / 'session.json')
            os.kill(session['pid'], 0)
            if not browser(session['url']):
                raise RuntimeError('Could not open the review page')
        else:
            if not 1 <= args.port <= 65535:
                raise ValueError('Port must be between 1 and 65535')
            store = Store(args.config, args.state_dir)
            with store.lock('server', blocking=False):
                serve(store, args.port)
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())

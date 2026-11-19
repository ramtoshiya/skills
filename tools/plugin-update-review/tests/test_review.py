import contextlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

TOOL = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('review', TOOL / 'src/review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def command(*args, cwd=None, env=None):
    isolated_env = (env if env is not None else os.environ).copy()
    isolated_env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    result = subprocess.run(args, cwd=cwd, env=isolated_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise AssertionError(f'{args}: {result.stderr}')
    return result.stdout.strip()


def git(cwd, *args):
    return command('git', '-c', 'core.hooksPath=/dev/null', '-C', str(cwd), *args)


def commit(repo, message):
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', message)
    return git(repo, 'rev-parse', 'HEAD')


# A request to the review server waits while a scan holds the store lock, and the HTTP tests
# rescan every second. On a loaded machine a scan held the lock for over 4 seconds. This bound
# only stops a hung server. It is not an expected response time.
SERVER_GUARD = 60


def wait_for(fn, timeout=SERVER_GUARD):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = fn()
            if value:
                return value
        except (OSError, json.JSONDecodeError, urllib.error.URLError, KeyError):
            pass
        time.sleep(.05)
    raise AssertionError('Timed out waiting for fixture')


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.market = self.root / 'market'
        self.market.mkdir()
        git(self.market, 'init', '-b', 'main')
        self.fork, self.upstream, self.base = self.make_pair('good')
        self.fork2, self.upstream2, self.base2 = self.make_pair('conflict')
        doc = {'name': 'fixture', 'plugins': [
            {'name': 'good', 'source': {'source': 'git-subdir', 'url': 'fixture/good', 'path': 'plugin', 'sha': self.base}, 'other': 'preserved'},
            {'name': 'other-good', 'source': {'source': 'git-subdir', 'url': 'fixture/good', 'path': 'plugin', 'sha': self.base}},
            {'name': 'conflict', 'source': {'source': 'git-subdir', 'url': 'fixture/conflict', 'path': 'plugin', 'sha': self.base2}},
            {'name': 'untouched', 'source': './untouched'}]}
        path = self.market / '.claude-plugin/marketplace.json'
        path.parent.mkdir()
        path.write_text(json.dumps(doc, indent=2) + '\n')
        self.market_base = commit(self.market, 'market base')
        self.market_remote = self.root / 'market.git'
        command('git', 'clone', '--bare', str(self.market), str(self.market_remote))
        git(self.market, 'remote', 'add', 'origin', str(self.market_remote))
        self.marker = self.root / 'test-marker'
        self.install_marker = self.root / 'install-marker'
        self.config = {'version': 1, 'marketplace': {'checkout': str(self.market), 'branch': 'main', 'remote': 'origin', 'push': True},
                       'sources': [self.source('good', self.fork, self.upstream, ['good', 'other-good']),
                                   self.source('conflict', self.fork2, self.upstream2, ['conflict'])],
                       'interval_seconds': 86400,
                       'install_targets': [{'id': 'install', 'label': 'Fixture install', 'cwd': str(self.root),
                                            'env': {'FIXTURE_VALUE': 'private-value'},
                                            'argv': [sys.executable, '-c', 'import os,pathlib; pathlib.Path(' + repr(str(self.install_marker)) + ').write_text("1")']}]}
        self.config['sources'][0]['tests'] = [{'id': 'check', 'label': 'Check fixture', 'kind': 'static',
                                              'argv': [sys.executable, '-c', 'import os,pathlib; pathlib.Path(' + repr(str(self.marker)) + ').write_text("1"); print("visible output"); import sys,time; s=os.environ["FIXTURE_SECRET"]; sys.stdout.write(s[:6]); sys.stdout.flush(); time.sleep(0.2); print(s[6:])']}]
        os.environ['FIXTURE_SECRET'] = 'secret-test-value'
        self.addCleanup(os.environ.pop, 'FIXTURE_SECRET', None)
        self.config_path = self.root / 'config.json'
        self.save_config()

    def make_pair(self, name):
        work = self.root / (name + '-upstream-work')
        work.mkdir()
        git(work, 'init', '-b', 'main')
        (work / 'plugin').mkdir()
        (work / 'plugin/file.txt').write_text('base for ' + name + '\n')
        base = commit(work, 'base')
        upstream = self.root / (name + '-upstream.git')
        fork = self.root / (name + '-fork.git')
        command('git', 'clone', '--bare', str(work), str(upstream))
        command('git', 'clone', '--bare', str(work), str(fork))
        git(work, 'remote', 'add', 'origin', str(upstream))
        return fork, upstream, base

    def source(self, name, fork, upstream, names):
        return {'id': name, 'label': name, 'fork_url': str(fork), 'branch': 'main', 'upstream_url': str(upstream),
                'upstream_branch': 'main', 'plugin_names': names, 'tests': []}

    def save_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def upstream_change(self, name, text):
        work = self.root / (name + '-upstream-work')
        (work / 'plugin/file.txt').write_text(text)
        sha = commit(work, 'upstream change')
        git(work, 'push', 'origin', 'main')
        return sha

    def fork_change(self, name, text):
        work = self.root / (name + '-fork-work')
        command('git', 'clone', str(self.root / (name + '-fork.git')), str(work))
        (work / 'plugin/file.txt').write_text(text)
        sha = commit(work, 'fork change')
        git(work, 'push', 'origin', 'main')
        return sha

    def store(self):
        return review.Store(self.config_path, self.state)

    def test_scan_candidates_conflicts_and_independent_failure(self):
        store = self.store()
        hook_marker = self.root / 'hook-marker'
        hooks = self.root / 'hooks'
        hooks.mkdir()
        for name in ('post-checkout', 'post-merge', 'pre-commit', 'pre-push'):
            hook = hooks / name
            hook.write_text('#!/bin/sh\nprintf hook >> ' + str(hook_marker) + '\n')
            hook.chmod(0o755)
        git(store.cache(self.config['sources'][0]), 'config', 'core.hooksPath', str(hooks))
        self.assertFalse(store.scan())
        self.assertEqual(store.state()['candidates'], {})
        self.assertFalse(self.marker.exists())
        upstream = self.upstream_change('good', 'upstream\n')
        self.fork_change('conflict', 'fork\n')
        self.upstream_change('conflict', 'upstream\n')
        bad = self.source('bad', self.fork, self.root / 'missing.git', ['untouched'])
        # Use a real marketplace entry so the failure is the fetch, not a pin parse.
        self.config['sources'].append(bad)
        self.save_config()
        store = self.store()
        self.assertTrue(store.scan())
        state = store.state()
        good = state['candidates']['good']
        self.assertEqual(good['upstream_head'], upstream)
        self.assertEqual(store.describe(good)['status'], 'ready')
        self.assertIn('upstream', store.diff(good, self.config['sources'][0])['text'])
        conflict = state['candidates']['conflict']
        self.assertEqual(store.describe(conflict)['status'], 'conflict')
        self.assertIn('plugin/file.txt', store.describe(conflict)['conflicts'])
        self.assertIn('<<<<<<<', (Path(conflict['worktree']) / 'plugin/file.txt').read_text())
        self.assertIn('bad', state['problems'])
        self.assertFalse(store.scan())
        self.assertEqual(store.state()['candidates']['good']['id'], good['id'])
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.install_marker.exists())
        self.assertFalse(hook_marker.exists())

    def test_pin_mismatch_without_upstream_change_and_manual_work_preserved(self):
        fork_head = self.fork_change('good', 'fork only\n')
        store = self.store()
        self.assertTrue(store.scan())
        candidate = store.state()['candidates']['good']
        self.assertEqual(store.describe(candidate)['head'], fork_head)
        changed = Path(candidate['worktree']) / 'plugin/file.txt'
        changed.write_text('human work\n')
        self.upstream_change('good', 'new upstream\n')
        self.assertTrue(store.scan())
        self.assertEqual(changed.read_text(), 'human work\n')
        self.assertEqual(store.state()['candidates']['good']['id'], candidate['id'])
        self.assertEqual(store.describe(candidate)['status'], 'modified')
        self.assertIn('changed', store.state()['problems']['good'])

    def test_apply_refuses_stale_and_retries_failed_install(self):
        self.upstream_change('good', 'new\n')
        hook_marker = self.root / 'hook-marker'
        hooks = self.root / 'market-hooks'
        hooks.mkdir()
        for name in ('pre-commit', 'pre-push'):
            hook = hooks / name
            hook.write_text('#!/bin/sh\nprintf hook >> ' + str(hook_marker) + '\n')
            hook.chmod(0o755)
        git(self.market, 'config', 'core.hooksPath', str(hooks))
        self.config['install_targets'][0]['argv'] = [sys.executable, '-c', 'raise SystemExit(7)']
        self.save_config()
        store = self.store()
        market_file = self.market / '.claude-plugin/marketplace.json'
        original_market_bytes = market_file.read_bytes().replace(b'\n', b'\r\n')
        market_file.write_bytes(original_market_bytes)
        commit(self.market, 'CRLF marketplace')
        git(self.market, 'push', 'origin', 'main')
        store.scan()
        c = store.state()['candidates']['good']
        path = Path(c['worktree'])
        old = git(path, 'rev-parse', 'HEAD')
        (path / 'plugin/file.txt').write_text('reviewed manually\n')
        current = commit(path, 'manual review')
        with self.assertRaisesRegex(ValueError, 'changed'):
            store.apply('good', old)
        self.assertEqual(git(self.fork, 'rev-parse', 'refs/heads/main'), self.base)
        with self.assertRaisesRegex(RuntimeError, 'exit 7'):
            store.apply('good', current)
        state = store.state()['candidates']['good']
        self.assertEqual(state['apply']['phase'], 'installation')
        self.assertEqual(git(self.fork, 'rev-parse', 'refs/heads/main'), current)
        self.assertEqual(git(self.market_remote, 'rev-parse', 'refs/heads/main'), state['apply']['market_commit'])
        self.assertFalse(hook_marker.exists())
        doc = json.loads((self.market / '.claude-plugin/marketplace.json').read_text())
        self.assertEqual([p['source']['sha'] for p in doc['plugins'][:2]], [current, current])
        self.assertEqual(doc['plugins'][0]['other'], 'preserved')
        self.assertEqual(doc['plugins'][2]['source']['sha'], self.base2)
        self.assertEqual(market_file.read_bytes(), original_market_bytes.replace(self.base.encode(), current.encode()))
        self.assertFalse(self.marker.exists())
        self.config['install_targets'][0]['argv'] = [sys.executable, '-c', 'import os,pathlib; pathlib.Path(' + repr(str(self.install_marker)) + ').write_text("1")']
        self.save_config()
        store = self.store()
        self.assertEqual(store.apply('good', current), 'Application complete')
        self.assertEqual(self.install_marker.read_text(), '1')
        self.assertTrue(store.state()['candidates']['good']['complete'])
        self.assertFalse(self.marker.exists())

    def test_remote_and_marketplace_changes_are_refused(self):
        self.upstream_change('good', 'upstream\n')
        store = self.store()
        store.scan()
        candidate = store.state()['candidates']['good']
        self.fork_change('good', 'someone else\n')
        with self.assertRaisesRegex(RuntimeError, 'Fork remote changed'):
            store.apply('good', candidate['prepared_head'])
        self.assertEqual(git(self.market, 'rev-parse', 'HEAD'), self.market_base)

    def test_marketplace_pin_and_dirty_checkout_prevent_publication(self):
        self.upstream_change('good', 'upstream\n')
        store = self.store()
        store.scan()
        candidate = store.state()['candidates']['good']
        market_file = self.market / '.claude-plugin/marketplace.json'
        market_file.write_text(market_file.read_text().replace(self.base, self.base2, 1))
        with self.assertRaisesRegex(RuntimeError, 'clean'):
            store.apply('good', candidate['prepared_head'])
        commit(self.market, 'other pin')
        with self.assertRaisesRegex(RuntimeError, 'pins changed'):
            store.apply('good', candidate['prepared_head'])
        self.assertEqual(git(self.fork, 'rev-parse', 'refs/heads/main'), self.base)

    def start_server(self):
        fake = self.root / 'bin'
        fake.mkdir()
        fake_open = fake / 'open'
        fake_open.write_text('#!/bin/sh\nprintf "open\\n" >> "$FAKE_OPEN_LOG"\n')
        fake_open.chmod(0o755)
        fake_script = fake / 'osascript'
        fake_script.write_text('#!' + sys.executable + '\n' + '''import json, os, subprocess, sys
script = sys.argv[-1]
if 'to do script ' in script:
    command = json.loads(script.split('to do script ', 1)[1])
    with open(os.environ['FAKE_TERMINAL_LOG'], 'a') as log:
        subprocess.Popen(['/bin/sh', '-c', command], stdout=log, stderr=log, start_new_session=True)
''')
        fake_script.chmod(0o755)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.origin = 'http://127.0.0.1:' + str(port)
        env = os.environ.copy()
        env.update(PATH=str(fake) + os.pathsep + env['PATH'], FAKE_OPEN_LOG=str(self.root / 'open.log'), FAKE_TERMINAL_LOG=str(self.root / 'terminal.log'))
        proc = subprocess.Popen([sys.executable, '-I', str(TOOL / 'src/review.py'), 'serve', '--config', str(self.config_path), '--state-dir', str(self.state), '--port', str(port)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        def cleanup():
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.communicate(timeout=5)
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self.addCleanup(cleanup)
        line = proc.stdout.readline().strip()
        self.assertTrue(line.startswith('Review server listening'), line)
        session = json.loads((self.state / 'session.json').read_text())
        self.url = session['url']
        self.token = self.url.split('token=')[1]
        wait_for(lambda: (self.state / 'state.json').exists() and self.store().state()['candidates'].get('good'))

    def request(self, path, data=None, origin=True, token=True, host=None):
        headers = {'Host': host} if host else {}
        if token:
            headers['X-Review-Token'] = self.token
        if data is not None:
            headers['Content-Type'] = 'application/json'
            if origin:
                headers['Origin'] = self.origin
            data = json.dumps(data).encode()
        request = urllib.request.Request(self.origin + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=SERVER_GUARD) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read().decode()

    def test_http_clicks_open_terminal_and_apply_without_duplicates(self):
        self.upstream_change('good', 'from upstream\n')
        self.fork_change('conflict', 'fork\n')
        self.upstream_change('conflict', 'upstream\n')
        self.config['sources'].append(self.source('bad', self.fork, self.root / 'missing.git', ['untouched']))
        eval_marker = self.root / 'eval-marker'
        self.config['sources'][0]['tests'].append({'id': 'manual-eval', 'label': 'Manual eval fixture', 'kind': 'eval',
            'argv': [sys.executable, '-c',
                     'import os,pathlib; pathlib.Path(' + repr(str(eval_marker)) + ').write_text("1")']})
        self.config['interval_seconds'] = 1
        self.save_config()
        self.start_server()
        status, page = self.request('/?token=' + self.token)
        self.assertEqual(status, 200)
        self.assertIn('Plugin update review', page)
        self.assertEqual(self.request('/api/state', token=False)[0], 403)
        self.assertEqual(self.request('/api/state', host='localhost:' + self.origin.rsplit(':', 1)[1])[0], 403)
        status, data = self.request('/api/state')
        self.assertEqual(status, 200)
        self.assertNotIn('private-value', data)
        self.assertNotIn(str(self.marker), data)
        items = json.loads(data)['sources']
        item = items[0]
        self.assertEqual(items[1]['candidate']['status'], 'conflict')
        self.assertTrue(items[2]['problem'])
        self.assertIn('from upstream', item['diff']['text'])
        head = item['candidate']['head']
        wait_for(lambda: (self.state / 'events.jsonl').read_text().count('\"kind\": \"scan\"') >= 2)
        self.assertEqual((self.root / 'open.log').read_text().splitlines(), ['open'])
        self.assertEqual(self.request('/api/apply', {'source': 'good', 'head': self.base})[0], 400)
        payload = {'source': 'good', 'test': 'check', 'head': head}
        self.assertEqual(self.request('/api/test', payload, origin=False)[0], 403)
        self.assertFalse(self.marker.exists())
        self.assertFalse(eval_marker.exists())
        self.assertEqual(self.request('/api/test', dict(payload, test='unknown'))[0], 400)
        self.assertEqual(self.request('/api/test', payload)[0], 200)
        wait_for(lambda: self.marker.exists())
        def finished():
            jobs = json.loads(self.request('/api/state')[1])['sources'][0]['candidate']['tests']
            return jobs and jobs[0] if jobs and jobs[0]['status'] == 'finished' else None
        job = wait_for(finished)
        self.assertEqual(job['exit_code'], 0)
        self.assertEqual(job['head'], head)
        self.assertEqual(self.marker.read_text(), '1')
        self.assertIn('visible output', Path(job['log']).read_text())
        self.assertNotIn('secret-test-value', Path(job['log']).read_text())
        self.assertIn('[REDACTED]', Path(job['log']).read_text())
        self.assertFalse(eval_marker.exists())
        self.assertEqual(self.request('/api/test', dict(payload, test='manual-eval'))[0], 200)
        wait_for(lambda: eval_marker.exists())
        self.assertEqual(eval_marker.read_text(), '1')
        wait_for(lambda: any(j['test'] == 'manual-eval' and j['status'] == 'finished' for j in json.loads(self.request('/api/state')[1])['sources'][0]['candidate']['tests']))
        self.assertEqual(self.request('/api/apply', {'source': 'good', 'head': head})[0], 200)
        self.assertEqual(git(self.fork, 'rev-parse', 'refs/heads/main'), head)
        self.assertEqual(self.install_marker.read_text(), '1')
        self.assertEqual(self.request('/api/apply', {'source': 'good', 'head': head})[0], 400)
        wait_for(lambda: (self.root / 'open.log').exists())
        self.assertEqual((self.root / 'open.log').read_text().splitlines(), ['open'])

    def test_configure_derives_sources_from_marketplace_and_forks(self):
        forks_path = self.market / '.github/upstream-forks.json'
        forks_path.parent.mkdir()
        forks_path.write_text(json.dumps([
            {'fork': 'fixture/good', 'branch': 'feature/review',
             'upstream': 'publisher/good', 'upstreamBranch': 'release/v2'},
            {'fork': 'fixture/conflict', 'branch': 'candidate',
             'upstream': 'publisher/conflict', 'upstreamBranch': 'integration'},
            {'fork': 'fixture/unmatched', 'branch': 'main',
             'upstream': 'publisher/unmatched', 'upstreamBranch': 'main'},
        ]))
        git(self.market, 'branch', '-m', 'review-config')
        inputs = [forks_path, self.market / '.claude-plugin/marketplace.json']
        before = [path.read_bytes() for path in inputs]
        status = git(self.market, 'status', '--porcelain')
        config_path = self.root / 'derived.json'
        result = subprocess.run([sys.executable, '-I', str(TOOL / 'src/review.py'), 'configure', '--repo', str(self.market), '--config', str(config_path)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(config_path.read_text()), {
            'version': 1,
            'marketplace': {'checkout': str(self.market.resolve()), 'branch': 'review-config',
                            'remote': 'origin', 'push': False},
            'sources': [
                {'id': 'fixture-good', 'label': 'fixture/good',
                 'fork_url': 'https://github.com/fixture/good.git', 'branch': 'feature/review',
                 'upstream_url': 'https://github.com/publisher/good.git', 'upstream_branch': 'release/v2',
                 'plugin_names': ['good', 'other-good'], 'tests': []},
                {'id': 'fixture-conflict', 'label': 'fixture/conflict',
                 'fork_url': 'https://github.com/fixture/conflict.git', 'branch': 'candidate',
                 'upstream_url': 'https://github.com/publisher/conflict.git', 'upstream_branch': 'integration',
                 'plugin_names': ['conflict'], 'tests': []},
            ],
            'install_targets': [],
            'interval_seconds': 86400,
        })
        self.assertEqual([path.read_bytes() for path in inputs], before)
        self.assertEqual(git(self.market, 'status', '--porcelain'), status)
        self.assertEqual(git(self.market, 'rev-parse', 'HEAD'), self.market_base)
        self.assertFalse(self.state.exists())

    def test_installer_copy_is_independent_and_refuses_unrelated_command(self):
        home = self.root / 'home'
        home.mkdir()
        copied = self.root / 'tool-copy'
        shutil.copytree(TOOL, copied)
        env = os.environ.copy()
        env['HOME'] = str(home)
        # Bypass version-manager shims that select config from the temporary HOME.
        real_uv = next((Path(part) / 'uv' for part in env['PATH'].split(os.pathsep) if (Path(part) / 'uv').is_file() and Path(os.path.realpath(Path(part) / 'uv')).name != 'mise'), None)
        self.assertIsNotNone(real_uv, 'A direct uv executable is required')
        env['PATH'] = str(real_uv.parent) + os.pathsep + env['PATH']
        env['UV_PYTHON_INSTALL_DIR'] = command('uv', 'python', 'dir')
        command('sh', str(copied / 'install.sh'), env=env)
        shutil.rmtree(copied)
        cmd = home / '.local/bin/plugin-update-review'
        self.assertIn('plugin-update-review 1', command(str(cmd), '--version', cwd=self.root, env=env))
        cmd.unlink()
        cmd.write_text('unrelated')
        result = subprocess.run(['sh', str(TOOL / 'install.sh')], env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cmd.read_text(), 'unrelated')


if __name__ == '__main__':
    unittest.main()

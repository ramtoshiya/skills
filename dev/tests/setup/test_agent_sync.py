import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[3] / "setup/agents/sync.py"
SPEC = importlib.util.spec_from_file_location("agent_sync", SOURCE)
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def commit(path, message):
    git(path, "add", ".")
    git(path, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", message)
    return git(path, "rev-parse", "HEAD")


class AgentSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.root = self.home / "repository"
        (self.root / ".claude-plugin").mkdir(parents=True)
        (self.root / "setup/agents").mkdir(parents=True)
        self.policy = self.root / "setup/agents/hosts.json"
        sync.write_json(self.policy, {"hosts": ["claude", "codex"], "plugins": {}})
        self.marketplace = self.root / ".claude-plugin/marketplace.json"
        commands = self.home / "bin"
        commands.mkdir()
        for host in ("claude", "codex"):
            (commands / host).write_text("#!/bin/sh\nexit 99\n")
            (commands / host).chmod(0o755)
        self.environment = patch.dict(os.environ, {
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "HOME": str(self.home), "XDG_STATE_HOME": str(self.home / "state"),
            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
            "CODEX_HOME": str(self.home / ".codex"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.upstream = self.home / "upstream"
        (self.upstream / "plugins/example/skills/writing").mkdir(parents=True)
        (self.upstream / "plugins/example/skills/writing/SKILL.md").write_text("original skill\n")
        git(self.upstream, "init", "-q")
        self.first = commit(self.upstream, "Initial")
        self.source = self.install_source(self.first)
        self.entry = {"name": "example", "source": {
            "source": "git-subdir", "url": "example/skills", "path": "plugins/example", "sha": self.first,
        }}
        self.set_entries([self.entry])
        git(self.root, "init", "-q")
        commit(self.root, "Approve source")

    def set_entries(self, entries):
        sync.write_json(self.marketplace, {"name": "example", "plugins": entries})

    def install_source(self, revision):
        target = self.home / "state/ramtoshiya-agents/sources/example/skills" / revision
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", str(self.upstream), str(target)], check=True)
        git(target, "checkout", "--detach", "-q", revision)
        return target / "plugins/example"

    def cache(self, host):
        return self.home / f".{host}/plugins/cache/example/example/local"

    def deploy(self, host, source):
        cache = shlex.quote(str(self.cache(host)))
        return f"rm -rf {cache} && mkdir -p {shlex.quote(str(self.cache(host).parent))} && cp -R {shlex.quote(str(source))} {cache}"

    def fake_cli(self, host, commands=None):
        if host == "claude":
            marketplaces = [{"name": "example", "path": str(self.root)}]
            listing = "plugin list --json"
            present = [{"id": "example@example", "scope": "user", "installPath": str(self.cache(host)), "enabled": True}]
            absent = []
        else:
            marketplaces = {"marketplaces": [{"name": "example", "root": str(self.root)}]}
            listing = "plugin list --json --marketplace example"
            present = {"installed": [{"pluginId": "example@example", "installed": True, "enabled": True, "version": "local"}]}
            absent = {"installed": []}
        cases = "".join(f"  {shlex.quote(call)}) {snippet} ;;\n" for call, snippet in (commands or {}).items())
        script = (
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> {shlex.quote(str(self.home / (host + '.log')))}\n"
            'case "$*" in\n'
            f"  'plugin marketplace list --json') printf '%s\\n' {shlex.quote(json.dumps(marketplaces))} ;;\n"
            f"  '{listing}') if [ -d {shlex.quote(str(self.cache(host)))} ]; then printf '%s\\n' {shlex.quote(json.dumps(present))}; "
            f"else printf '%s\\n' {shlex.quote(json.dumps(absent))}; fi ;;\n"
            f"{cases}"
            "  *) exit 98 ;;\n"
            "esac\n"
        )
        (self.home / "bin" / host).write_text(script)

    def changes(self, host):
        log = self.home / f"{host}.log"
        calls = log.read_text().splitlines() if log.exists() else []
        return [call for call in calls if not call.startswith(("plugin marketplace list", "plugin list", "plugins list"))]

    def execute(self, apply, host="claude"):
        operation = sync.Sync(self.root)
        return operation, operation.process([host], apply=apply)

    def use_hook_plugin(self, source):
        hooks = self.root / "plugins/ramtoshiya/hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "main.go").write_text(source)
        (self.root / ".gitignore").write_text("/plugins/*/hooks/ramtoshiya-hooks\n/plugins/*/hooks/.ramtoshiya-hooks.*\n")
        self.set_entries([{"name": "example", "source": "./plugins/ramtoshiya"}])
        commit(self.root, "Change the hook source")
        for name, script in (
            ("mise", "exit 1\n"),
            ("go", 'while [ $# -gt 1 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
                   'if grep -q broken main.go; then echo "main.go: syntax error" >&2; exit 1; fi\n'
                   'cp main.go "$out"\n'),
        ):
            (self.home / "bin" / name).write_text("#!/bin/sh\n" + script)
            (self.home / "bin" / name).chmod(0o755)
        return hooks

    def test_sync_installs_repeats_without_writes_and_updates_after_a_pin_change(self):
        self.fake_cli("claude", {"plugin install example@example --scope user": self.deploy("claude", self.source)})
        operation, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "updated")
        state_before = operation.state_path.read_bytes(), operation.state_path.stat().st_mtime_ns
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual((operation.state_path.read_bytes(), operation.state_path.stat().st_mtime_ns), state_before)
        (self.upstream / "plugins/example/skills/writing/SKILL.md").write_text("updated skill\n")
        revision = commit(self.upstream, "Update")
        new = self.install_source(revision)
        self.entry["source"]["sha"] = revision
        self.set_entries([self.entry])
        self.fake_cli("claude", {"plugin update example@example --scope user": self.deploy("claude", new)})
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "updated")
        self.assertEqual((self.cache("claude") / "skills/writing/SKILL.md").read_text(), "updated skill\n")
        self.assertEqual(sync.read_json(operation.state_path)["packages"]["claude:example"]["pin"], revision)
        self.assertEqual(self.changes("claude"), [
            "plugin install example@example --scope user", "plugin update example@example --scope user",
        ])

    def test_plugin_selection_limits_installation_and_retirement(self):
        other = self.upstream / "plugins/other/skills/research/SKILL.md"
        other.parent.mkdir(parents=True)
        other.write_text("other package\n")
        revision = commit(self.upstream, "Add other package")
        self.install_source(revision)
        self.entry["source"]["sha"] = revision
        second = {"name": "other", "source": {**self.entry["source"], "path": "plugins/other"}}
        self.set_entries([self.entry, second])
        example = sync.Sync(self.root).sources.package(self.entry)
        self.fake_cli("claude", {
            "plugin install example@example --scope user": self.deploy("claude", example.root),
            "plugin uninstall example@example --scope user --keep-data": "",
        })
        rows = sync.Sync(self.root).process(["claude"])
        self.assertEqual([row["component"] for row in rows], ["example", "other"])
        rows = sync.Sync(self.root).process(["claude"], apply=True, selected=["example"])
        self.assertEqual([(row["component"], row["status"]) for row in rows], [("example", "updated")])
        self.assertEqual(self.changes("claude"), ["plugin install example@example --scope user"])
        operation = sync.Sync(self.root)
        package = operation.sources.package(second)
        installed = self.home / "installed-other"
        shutil.copytree(package.root, installed)
        operation.remember("claude", "other", installed, package)
        self.set_entries([])
        rows = sync.Sync(self.root).process(["claude"], selected=["example"])
        self.assertEqual([(row["component"], row["status"]) for row in rows], [("example", "drift")])
        operation = sync.Sync(self.root)
        rows = operation.process(["claude"], apply=True, selected=["example"])
        self.assertEqual([(row["component"], row["status"]) for row in rows], [("example", "updated")])
        self.assertEqual(self.changes("claude")[1:], ["plugin uninstall example@example --scope user --keep-data"])
        self.assertEqual(set(sync.read_json(operation.state_path)["packages"]), {"claude:other"})
        with self.assertRaisesRegex(sync.Conflict, "Unknown plugins"):
            sync.Sync(self.root).process(["claude"], apply=True, selected=["typo"])

    def test_status_is_offline_and_does_not_create_state(self):
        self.fake_cli("claude")
        self.fake_cli("codex")
        operation = sync.Sync(self.root)
        rows = operation.process(["claude", "codex"])
        self.assertEqual([(row["host"], row["status"]) for row in rows], [("claude", "drift"), ("codex", "drift")])
        shutil.rmtree(self.home / "state/ramtoshiya-agents/sources")
        rows = sync.Sync(self.root).process(["claude"])
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("not cached", rows[0]["detail"])
        self.assertEqual(self.changes("claude") + self.changes("codex"), [])
        self.assertFalse(operation.state_path.exists())

    def test_modified_pinned_source_is_not_installed_or_overwritten(self):
        (self.source / "skills/writing/SKILL.md").write_text("local customization\n")
        self.fake_cli("claude")
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("Modified source", rows[0]["detail"])
        self.assertEqual(self.changes("claude"), [])
        self.assertEqual((self.source / "skills/writing/SKILL.md").read_text(), "local customization\n")

    def test_installation_from_an_earlier_approved_pin_is_updated(self):
        shutil.copytree(self.source, self.cache("claude"))
        (self.upstream / "plugins/example/skills/writing/SKILL.md").write_text("updated skill\n")
        revision = commit(self.upstream, "Update")
        new = self.install_source(revision)
        self.entry["source"]["sha"] = revision
        self.set_entries([self.entry])
        commit(self.root, "Update pin")
        self.fake_cli("claude", {"plugin update example@example --scope user": self.deploy("claude", new)})
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "updated")
        self.assertEqual(self.changes("claude"), ["plugin update example@example --scope user"])
        self.assertEqual((self.cache("claude") / "skills/writing/SKILL.md").read_text(), "updated skill\n")

    def test_committed_but_unapproved_customization_is_not_adopted(self):
        (self.upstream / "plugins/example/skills/writing/SKILL.md").write_text("committed local customization\n")
        custom = self.install_source(commit(self.upstream, "Customize"))
        shutil.copytree(custom, self.cache("claude"))
        self.fake_cli("claude")
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("Unrecognized or modified installation", rows[0]["detail"])
        self.assertEqual(self.changes("claude"), [])
        self.assertEqual((self.cache("claude") / "skills/writing/SKILL.md").read_text(), "committed local customization\n")

    def test_locally_changed_installation_is_neither_updated_nor_retired(self):
        self.fake_cli("claude", {"plugin install example@example --scope user": self.deploy("claude", self.source)})
        self.execute(True)
        edited = self.cache("claude") / "skills/writing/SKILL.md"
        edited.write_text("local edit\n")
        for declared in (True, False):
            with self.subTest(declared=declared):
                self.set_entries([self.entry] if declared else [])
                operation, rows = self.execute(True)
                self.assertEqual(rows[0]["status"], "conflict")
                self.assertIn("Locally changed", rows[0]["detail"])
                self.assertEqual(self.changes("claude"), ["plugin install example@example --scope user"])
                self.assertEqual(edited.read_text(), "local edit\n")
                self.assertIn("claude:example", sync.read_json(operation.state_path)["packages"])

    def test_retiring_a_package_unregisters_it_and_forgets_its_record(self):
        for host, install, retire in (
            ("claude", "plugin install example@example --scope user", "plugin uninstall example@example --scope user --keep-data"),
            ("codex", "plugin add example@example", "plugin remove example@example"),
        ):
            with self.subTest(host=host):
                self.set_entries([self.entry])
                self.fake_cli(host, {install: self.deploy(host, self.source), retire: ""})
                self.execute(True, host)
                self.set_entries([])
                operation, rows = self.execute(True, host)
                self.assertEqual([row["status"] for row in rows], ["updated"])
                self.assertEqual(self.changes(host), [install, retire])
                self.assertNotIn(f"{host}:example", sync.read_json(operation.state_path)["packages"])
                self.assertTrue((self.source / "skills/writing/SKILL.md").is_file())

    def test_native_install_does_not_enable_an_already_enabled_plugin(self):
        self.fake_cli("claude", {
            "plugin install example@example --scope user": self.deploy("claude", self.source),
            "plugin enable example@example --scope user": ":",
        })
        operation, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "updated")
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(self.changes("claude"), ["plugin install example@example --scope user"])
        self.assertEqual((self.cache("claude") / "skills/writing/SKILL.md").read_text(), "original skill\n")
        self.assertEqual(sync.read_json(operation.state_path)["packages"]["claude:example"]["pin"], self.first)

    def test_installer_success_is_not_accepted_when_cached_contents_remain_stale(self):
        self.fake_cli("codex", {"plugin add example@example": self.deploy("codex", self.source)})
        operation, rows = self.execute(True, "codex")
        self.assertEqual(rows[0]["status"], "updated")
        state_before = operation.state_path.read_bytes()
        (self.upstream / "plugins/example/skills/writing/SKILL.md").write_text("updated skill\n")
        revision = commit(self.upstream, "Update")
        self.install_source(revision)
        self.entry["source"]["sha"] = revision
        self.set_entries([self.entry])
        self.fake_cli("codex", {"plugin add example@example": ":"})
        operation, rows = self.execute(True, "codex")
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("Native installer did not reconcile", rows[0]["detail"])
        self.assertEqual(self.changes("codex"), ["plugin add example@example", "plugin add example@example"])
        self.assertEqual((self.cache("codex") / "skills/writing/SKILL.md").read_text(), "original skill\n")
        self.assertEqual(operation.state_path.read_bytes(), state_before)

    def fake_app_server(self, current_hash):
        script = self.home / "app-server.py"
        script.write_text(
            "import json, sys\n"
            "from pathlib import Path\n"
            "state, current = Path(sys.argv[1]), sys.argv[2]\n"
            "key = 'example@example:hooks/hooks.json:pre_tool_use:0:0'\n"
            "for line in sys.stdin:\n"
            "    message = json.loads(line)\n"
            "    if 'id' not in message:\n"
            "        continue\n"
            "    trusted = json.loads(state.read_text()) if state.exists() else {}\n"
            "    result = {}\n"
            "    if message['method'] == 'hooks/list':\n"
            "        status = 'trusted' if trusted.get(key) == current else ('modified' if key in trusted else 'untrusted')\n"
            "        hooks = [{'key': key, 'pluginId': 'example@example', 'currentHash': current, 'trustStatus': status}]\n"
            "        result = {'data': [{'cwd': '/', 'errors': [], 'warnings': [], 'hooks': hooks if current else []}]}\n"
            "    elif message['method'] == 'config/batchWrite':\n"
            "        for edit in message['params']['edits']:\n"
            "            trusted.update({k: v['trusted_hash'] for k, v in edit['value'].items()})\n"
            "        state.write_text(json.dumps(trusted))\n"
            "    print(json.dumps({'id': message['id'], 'result': result}), flush=True)\n"
        )
        return " ".join(shlex.quote(part) for part in [sys.executable, str(script), str(self.home / "trust.json"), current_hash])

    def test_codex_sync_trusts_the_hooks_it_installs_and_status_reports_untrusted_hooks(self):
        (self.upstream / "plugins/example/hooks").mkdir()
        (self.upstream / "plugins/example/hooks/hooks.json").write_text(
            '{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "true"}]}]}}\n')
        revision = commit(self.upstream, "Add hooks")
        source = self.install_source(revision)
        self.entry["source"]["sha"] = revision
        self.set_entries([self.entry])
        key = "example@example:hooks/hooks.json:pre_tool_use:0:0"
        self.fake_cli("codex", {"plugin add example@example": self.deploy("codex", source),
                                "app-server": self.fake_app_server("sha256:a/sha256:b")})
        _, rows = self.execute(True, "codex")
        self.assertEqual(rows[0]["status"], "updated")
        self.assertEqual(sync.read_json(self.home / "trust.json"), {key: "sha256:a/sha256:b"})
        _, rows = self.execute(False, "codex")
        self.assertEqual(rows[0]["status"], "ok")

        self.fake_cli("codex", {"app-server": self.fake_app_server("sha256:a/sha256:c")})
        _, rows = self.execute(False, "codex")
        self.assertEqual((rows[0]["status"], rows[0]["detail"]), ("drift", f"Codex has not trusted hooks ['{key}'], run agents:sync"))
        _, rows = self.execute(True, "codex")
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(sync.read_json(self.home / "trust.json"), {key: "sha256:a/sha256:c"})

        self.fake_cli("codex", {"app-server": self.fake_app_server("")})
        _, rows = self.execute(False, "codex")
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("Codex lists none of the hooks in", rows[0]["detail"])

    def test_generated_codex_manifest_cannot_add_unapproved_capabilities(self):
        manifest = self.cache("codex") / ".codex-plugin/plugin.json"
        injected = json.dumps({"name": "example", "skills": None, "hooks": "./injected.json"})
        install = (f"{self.deploy('codex', self.source)} && mkdir -p {shlex.quote(str(manifest.parent))} "
                   f"&& printf '%s\\n' {shlex.quote(injected)} > {shlex.quote(str(manifest))}")
        self.fake_cli("codex", {"plugin add example@example": install})
        operation, rows = self.execute(True, "codex")
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("Unexpected capabilities", rows[0]["detail"])
        self.assertEqual(self.changes("codex"), ["plugin add example@example"])
        self.assertNotIn("codex:example", sync.read_json(operation.state_path, {"packages": {}})["packages"])

    def test_symlinked_state_file_is_not_replaced_or_written_through(self):
        shutil.copytree(self.source, self.cache("claude"))
        self.fake_cli("claude")
        target = self.home / "dotfiles/state.json"
        sync.write_json(target, {"version": 1, "packages": {}})
        state = sync.Sync(self.root).state_path
        state.parent.mkdir(parents=True, exist_ok=True)
        state.symlink_to(target)
        before = target.read_bytes()
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("symlinked", rows[0]["detail"])
        self.assertTrue(state.is_symlink())
        self.assertEqual(target.read_bytes(), before)

    def test_lock_rejects_concurrent_sync(self):
        first = sync.Sync(self.root)
        second = sync.Sync(self.root)
        with first.lock():
            with self.assertRaisesRegex(sync.Conflict, "Another agent sync"):
                with second.lock():
                    self.fail("concurrent sync acquired the lock")

    def test_sync_builds_the_hook_binary_before_installing_and_status_compares_it_with_its_source(self):
        hooks = self.use_hook_plugin("package main // v1\n")
        installed = self.cache("codex")
        shutil.copytree(self.root / "plugins/ramtoshiya", installed)
        self.fake_cli("codex", {"plugin add example@example": self.deploy("codex", self.root / "plugins/ramtoshiya")})
        steps = [
            (False, [("build", "drift"), ("codex", "ok")]),
            (True, [("build", "updated"), ("codex", "updated")]),
            (True, [("build", "ok"), ("codex", "ok")]),
        ]
        for apply, expected in steps:
            _, rows = self.execute(apply, "codex")
            self.assertEqual([(row["host"], row["status"]) for row in rows], expected)
        self.assertEqual((installed / "hooks/ramtoshiya-hooks").read_text(), "package main // v1\n")

        (hooks / "main.go").write_text("package main // v2\n")
        commit(self.root, "Change the hook")
        _, rows = self.execute(False, "codex")
        self.assertEqual([(row["host"], row["status"]) for row in rows], [("build", "drift"), ("codex", "drift")])
        self.assertEqual(sorted(path.name for path in hooks.iterdir()), ["main.go", "ramtoshiya-hooks"])
        _, rows = self.execute(True, "codex")
        self.assertEqual([(row["host"], row["status"]) for row in rows], [("build", "updated"), ("codex", "updated")])
        self.assertEqual((installed / "hooks/ramtoshiya-hooks").read_text(), "package main // v2\n")
        self.assertEqual(self.changes("codex"), ["plugin add example@example", "plugin add example@example"])

    def test_failed_hook_build_stops_sync_before_any_install(self):
        self.use_hook_plugin("package main // broken\n")
        self.fake_cli("codex", {"plugin add example@example": self.deploy("codex", self.root / "plugins/ramtoshiya")})
        operation, rows = self.execute(True, "codex")
        self.assertEqual([(row["host"], row["status"]) for row in rows], [("build", "conflict")])
        self.assertIn("main.go: syntax error", rows[0]["detail"])
        self.assertEqual(self.changes("codex"), [])
        self.assertFalse(operation.state_path.exists())

    def test_git_source_checks_include_untracked_files_and_symlinks(self):
        (self.source / "unexpected").symlink_to(self.home / "private")
        self.fake_cli("claude")
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("unexpected", rows[0]["detail"])


if __name__ == "__main__":
    unittest.main()

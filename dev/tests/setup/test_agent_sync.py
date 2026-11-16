"""Ownership and source-integrity contracts for the agent setup reconciler."""

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
        shutil.copyfile(SOURCE.with_name("hermes-skills.py"), self.root / "setup/agents/hermes-skills.py")
        self.policy = self.root / "setup/agents/hosts.json"
        sync.write_json(self.policy, {"hosts": ["claude", "codex"], "plugins": {}})
        self.marketplace = self.root / ".claude-plugin/marketplace.json"
        commands = self.home / "bin"
        commands.mkdir()
        # These stubs keep a test that forgets fake_cli from reaching a real host command.
        for host in ("claude", "codex", "hermes"):
            (commands / host).write_text("#!/bin/sh\nexit 99\n")
            (commands / host).chmod(0o755)
        self.environment = patch.dict(os.environ, {
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "HOME": str(self.home), "XDG_STATE_HOME": str(self.home / "state"),
            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
            "CODEX_HOME": str(self.home / ".codex"),
            "HERMES_HOME": str(self.home / ".hermes"),
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
        """Check out a revision where sync looks for pinned sources and return the plugin directory."""
        target = self.home / "state/ramtoshiya-agents/sources/example/skills" / revision
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", str(self.upstream), str(target)], check=True)
        git(target, "checkout", "--detach", "-q", revision)
        return target / "plugins/example"

    def cache(self, host):
        return self.home / f".{host}/plugins/cache/example/example/local"

    def deploy(self, host, source):
        """Return a shell snippet that leaves a copy of source in the host's plugin cache."""
        cache = shlex.quote(str(self.cache(host)))
        return f"rm -rf {cache} && mkdir -p {shlex.quote(str(self.cache(host).parent))} && cp -R {shlex.quote(str(source))} {cache}"

    def fake_cli(self, host, commands=None):
        """Replace the host command with a script that logs every call.

        The script reports this checkout as the marketplace and lists the example
        plugin once its cache directory exists. It runs the shell snippet that
        commands maps to an exact call and exits with an error for any other call."""
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
        """Return the calls sync made to the host command, without its read-only queries."""
        log = self.home / f"{host}.log"
        calls = log.read_text().splitlines() if log.exists() else []
        return [call for call in calls if not call.startswith(("plugin marketplace list", "plugin list", "plugins list"))]

    def execute(self, apply, host="claude"):
        operation = sync.Sync(self.root)
        return operation, operation.process([host], apply=apply)

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

    def fake_hermes(self):
        """Replace hermes with a script that logs calls and keeps enabled plugins as flag files."""
        flags = shlex.quote(str(self.home / "hermes-enabled"))
        script = (
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> {shlex.quote(str(self.home / 'hermes.log'))}\n"
            f"mkdir -p {flags}\n"
            'case "$1 $2" in\n'
            f"  'plugins list') printf '['; sep=''; for f in {flags}/*; do [ -e \"$f\" ] || continue; "
            "printf '%s{\"name\":\"%s\",\"status\":\"enabled\"}' \"$sep\" \"$(basename \"$f\")\"; sep=','; done; printf ']\\n' ;;\n"
            f"  'plugins enable') touch {flags}/\"$3\" ;;\n"
            f"  'plugins disable') rm -f {flags}/\"$3\" ;;\n"
            "  'plugins doctor') exit 0 ;;\n"
            "  *) exit 98 ;;\n"
            "esac\n"
        )
        (self.home / "bin/hermes").write_text(script)

    def test_native_hermes_plugin_is_linked_enabled_and_disabled_on_retirement(self):
        native = self.root / "plugins/native"
        (native / "skills/writing").mkdir(parents=True)
        (native / "skills/writing/SKILL.md").write_text("native skill\n")
        (native / "plugin.yaml").write_text("name: native\n")
        sync.write_json(self.policy, {"hosts": ["hermes"], "plugins": {}})
        self.set_entries([{"name": "native", "source": "./plugins/native"}])
        commit(self.root, "Add native plugin")
        self.fake_hermes()
        _, rows = self.execute(True, "hermes")
        self.assertEqual([row["status"] for row in rows], ["updated"], rows)
        link = self.home / ".hermes/plugins/native"
        self.assertEqual(link.resolve(), native.resolve())
        self.assertEqual(self.changes("hermes"), [f"plugins doctor {link} --ci", "plugins enable native --no-allow-tool-override"])
        _, rows = self.execute(True, "hermes")
        self.assertEqual([row["status"] for row in rows], ["ok"], rows)
        self.assertEqual(len(self.changes("hermes")), 2)
        self.set_entries([])
        commit(self.root, "Retire native plugin")
        _, rows = self.execute(True, "hermes")
        self.assertEqual([row["status"] for row in rows], ["updated"], rows)
        self.assertEqual(self.changes("hermes")[-1], "plugins disable native")
        self.assertTrue(link.is_symlink())

    def test_humanize_without_its_advisory_flag_is_not_reported_as_current(self):
        operation = sync.Sync(self.root)
        entry = {**self.entry, "name": "humanize"}
        package = operation.sources.package(entry)
        sync.write_json(self.home / ".hermes/plugins/humanize/source.json", {
            **entry["source"], "root": str(package.root), "skills": ["skills/writing"], "managed_adapter": False,
        })
        self.fake_hermes()
        (self.home / "hermes-enabled").mkdir()
        (self.home / "hermes-enabled/humanize").touch()
        status, _ = operation.hermes(entry, package, False)
        self.assertEqual(status, "drift")

    def test_generated_hermes_adapters_follow_template_changes_but_preserve_local_edits(self):
        self.fake_hermes()
        operation = sync.Sync(self.root)
        package = operation.sources.package(self.entry)
        self.assertEqual(operation.hermes(self.entry, package, True)[0], "updated")
        template = self.root / "setup/agents/hermes-skills.py"
        template.write_text(template.read_text() + "\n# Updated registration adapter.\n")
        operation = sync.Sync(self.root)
        self.assertEqual(operation.hermes(self.entry, package, True)[0], "updated")
        installed = self.home / ".hermes/plugins/example/__init__.py"
        self.assertEqual(installed.read_bytes(), template.read_bytes())
        before = installed.stat().st_mtime_ns
        operation = sync.Sync(self.root)
        self.assertEqual(operation.hermes(self.entry, package, True)[0], "ok")
        self.assertEqual(installed.stat().st_mtime_ns, before)
        installed.write_text("local adapter customization\n")
        operation = sync.Sync(self.root)
        with self.assertRaisesRegex(sync.Conflict, "Locally changed"):
            operation.hermes(self.entry, package, True)
        self.assertEqual(installed.read_text(), "local adapter customization\n")

    def test_failed_link_replacement_restores_the_original_directory(self):
        operation = sync.Sync(self.root)
        plugin = self.home / ".hermes/plugins/example"
        plugin.mkdir(parents=True)
        (plugin / "original.txt").write_text("original plugin\n")
        with patch.object(sync.os, "replace", side_effect=OSError("replacement failed")):
            with self.assertRaisesRegex(OSError, "replacement failed"):
                operation.install_link(plugin, self.upstream / "plugins/example")
        self.assertEqual((plugin / "original.txt").read_text(), "original plugin\n")
        self.assertFalse(plugin.is_symlink())
        self.assertFalse(plugin.with_name("example.sync-link").is_symlink())

    def test_lock_rejects_concurrent_sync(self):
        first = sync.Sync(self.root)
        second = sync.Sync(self.root)
        with first.lock():
            with self.assertRaisesRegex(sync.Conflict, "Another agent sync"):
                with second.lock():
                    self.fail("concurrent sync acquired the lock")

    def test_git_source_checks_include_untracked_files_and_symlinks(self):
        (self.source / "unexpected").symlink_to(self.home / "private")
        self.fake_cli("claude")
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("unexpected", rows[0]["detail"])


if __name__ == "__main__":
    unittest.main()

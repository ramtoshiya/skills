"""Ownership and source-integrity contracts for the agent setup reconciler."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "setup/agents/sync.py"
SPEC = importlib.util.spec_from_file_location("agent_sync", SOURCE)
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


class AgentSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.root = self.home / "repository"
        (self.root / ".claude-plugin").mkdir(parents=True)
        (self.root / "setup/agents").mkdir(parents=True)
        shutil.copyfile(SOURCE.with_name("hermes-skills.py"), self.root / "setup/agents/hermes-skills.py")
        self.policy = self.root / "setup/agents/hosts.json"
        sync.write_json(self.policy, {"hosts": ["pi"], "plugins": {}})
        self.marketplace = self.root / ".claude-plugin/marketplace.json"
        commands = self.home / "bin"
        commands.mkdir()
        (commands / "pi").write_text("#!/bin/sh\nexit 99\n")
        (commands / "pi").chmod(0o755)
        self.environment = patch.dict(os.environ, {
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "HOME": str(self.home), "XDG_STATE_HOME": str(self.home / "state"),
            "PI_CODING_AGENT_DIR": str(self.home / ".pi/agent"),
            "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
            "CODEX_HOME": str(self.home / ".codex"),
            "HERMES_HOME": str(self.home / ".hermes"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.settings = self.home / ".pi/agent/settings.json"
        self.upstream = self.home / "upstream"
        (self.upstream / "plugins/example/skills/writing").mkdir(parents=True)
        (self.upstream / "plugins/example/hooks").mkdir()
        (self.upstream / "plugins/example/skills/writing/SKILL.md").write_text("original skill\n")
        (self.upstream / "plugins/example/hooks/pi.ts").write_text("original extension\n")
        git(self.upstream, "init", "-q")
        git(self.upstream, "add", ".")
        git(self.upstream, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "Initial")
        self.first = git(self.upstream, "rev-parse", "HEAD")
        self.install_source(self.first)
        self.entry = {"name": "example", "source": {
            "source": "git-subdir", "url": "example/skills", "path": "plugins/example", "sha": self.first,
        }}
        self.set_entries([self.entry])
        git(self.root, "init", "-q")
        git(self.root, "add", ".")
        git(self.root, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "Approve source")

    def set_entries(self, entries):
        sync.write_json(self.marketplace, {"name": "example", "plugins": entries})

    def install_source(self, revision):
        target = self.home / ".pi/agent/skill-sources/example/skills" / revision
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", str(self.upstream), str(target)], check=True)
        git(target, "checkout", "--detach", "-q", revision)
        return target / "plugins/example"

    def execute(self, apply):
        operation = sync.Sync(self.root)
        return operation, operation.process(["pi"], apply=apply)

    def test_sync_preserves_unrelated_settings_replaces_owned_paths_and_is_idempotent(self):
        old = self.home / f".pi/agent/skill-sources/example/skills/{self.first}/plugins/example"
        original = {
            "defaultModel": "personal-model",
            "skills": ["personal/skill", str(old / "skills/writing")],
            "extensions": ["orca.ts", str(old / "hooks/pi.ts")],
            "packages": ["unrelated-package"],
        }
        sync.write_json(self.settings, original)
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "ok")
        (self.upstream / "plugins/example/skills/writing/SKILL.md").write_text("updated skill\n")
        git(self.upstream, "add", ".")
        git(self.upstream, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "Update")
        revision = git(self.upstream, "rev-parse", "HEAD")
        new = self.install_source(revision)
        self.entry["source"]["sha"] = revision
        self.set_entries([self.entry])
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "updated")
        expected = {
            **original, "skills": ["personal/skill", str(new / "skills/writing")],
            "extensions": ["orca.ts", str(new / "hooks/pi.ts")],
        }
        self.assertEqual(json.loads(self.settings.read_text()), expected)
        operation = sync.Sync(self.root)
        before = self.settings.read_bytes(), self.settings.stat().st_mtime_ns
        state_before = operation.state_path.read_bytes(), operation.state_path.stat().st_mtime_ns
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual((self.settings.read_bytes(), self.settings.stat().st_mtime_ns), before)
        self.assertEqual((operation.state_path.read_bytes(), operation.state_path.stat().st_mtime_ns), state_before)

    def test_repeated_sync_does_not_reorder_or_rewrite_a_shared_multi_package_settings_file(self):
        other = self.upstream / "plugins/other/skills/research/SKILL.md"
        other.parent.mkdir(parents=True)
        other.write_text("other package\n")
        git(self.upstream, "add", ".")
        git(self.upstream, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "Add other package")
        revision = git(self.upstream, "rev-parse", "HEAD")
        self.install_source(revision)
        self.entry["source"]["sha"] = revision
        second = {"name": "other", "source": {**self.entry["source"], "path": "plugins/other"}}
        self.set_entries([self.entry, second])
        sync.write_json(self.settings, {"skills": ["personal"], "extensions": ["orca.ts"]})
        self.execute(True)
        before = self.settings.read_bytes(), self.settings.stat().st_mtime_ns
        _, rows = self.execute(True)
        self.assertEqual([row["status"] for row in rows], ["ok", "ok"])
        self.assertEqual((self.settings.read_bytes(), self.settings.stat().st_mtime_ns), before)

    def test_plugin_selection_limits_installation_and_retirement(self):
        other = self.upstream / "plugins/other/skills/research/SKILL.md"
        other.parent.mkdir(parents=True)
        other.write_text("other package\n")
        git(self.upstream, "add", ".")
        git(self.upstream, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "Add other package")
        revision = git(self.upstream, "rev-parse", "HEAD")
        source = self.install_source(revision)
        self.entry["source"]["sha"] = revision
        second = {"name": "other", "source": {**self.entry["source"], "path": "plugins/other"}}
        self.set_entries([self.entry, second])
        operation = sync.Sync(self.root)
        rows = operation.process(["pi"], apply=True, selected=["example"])
        self.assertEqual([row["component"] for row in rows], ["example"])
        self.assertEqual(set(operation.state["packages"]), {"pi:example"})
        operation = sync.Sync(self.root)
        operation.process(["pi"], apply=True)
        self.set_entries([])
        operation = sync.Sync(self.root)
        rows = operation.process(["pi"], selected=["example"])
        self.assertEqual([(row["component"], row["status"]) for row in rows], [("example", "drift")])
        operation = sync.Sync(self.root)
        rows = operation.process(["pi"], apply=True, selected=["example"])
        self.assertEqual([row["component"] for row in rows], ["example"])
        self.assertEqual(set(sync.read_json(operation.state_path)["packages"]), {"pi:other"})
        self.assertEqual(sync.read_json(self.settings)["skills"], [str(source.parent / "other/skills/research")])
        with self.assertRaisesRegex(sync.Conflict, "Unknown plugins"):
            sync.Sync(self.root).process(["pi"], apply=True, selected=["typo"])

    def test_status_is_offline_and_does_not_create_state_or_settings(self):
        operation, rows = self.execute(False)
        self.assertEqual(rows[0]["status"], "drift")
        self.assertFalse(self.settings.exists())
        self.assertFalse(operation.state_dir.exists())

    def test_modified_pinned_source_is_not_adopted_or_overwritten(self):
        source = self.home / f".pi/agent/skill-sources/example/skills/{self.first}/plugins/example"
        (source / "skills/writing/SKILL.md").write_text("local customization\n")
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("Modified source", rows[0]["detail"])
        self.assertFalse(self.settings.exists())
        self.assertEqual((source / "skills/writing/SKILL.md").read_text(), "local customization\n")

    def test_adoption_uses_the_referenced_checkout_when_another_cache_has_the_same_pin(self):
        source = self.home / f".pi/agent/skill-sources/example/skills/{self.first}/plugins/example"
        operation = sync.Sync(self.root)
        cached = operation.sources.directory / "example/skills" / self.first
        cached.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", str(self.upstream), str(cached)], check=True)
        sync.write_json(self.settings, {"skills": [str(source / "skills/writing")], "extensions": [str(source / "hooks/pi.ts")]})
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "updated")
        settings = json.loads(self.settings.read_text())
        self.assertEqual(settings["skills"], [str(cached / "plugins/example/skills/writing")])
        self.assertEqual(settings["extensions"], [str(cached / "plugins/example/hooks/pi.ts")])

    def test_committed_but_unapproved_customization_is_not_adopted(self):
        (self.upstream / "plugins/example/skills/writing/SKILL.md").write_text("committed local customization\n")
        git(self.upstream, "add", ".")
        git(self.upstream, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "Customize")
        revision = git(self.upstream, "rev-parse", "HEAD")
        custom = self.install_source(revision)
        sync.write_json(self.settings, {"skills": [str(custom / "skills/writing")]})
        before = self.settings.read_bytes()
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("not approved", rows[0]["detail"])
        self.assertEqual(self.settings.read_bytes(), before)

    def test_adoption_leaves_other_packages_from_the_same_repository_alone(self):
        other = self.upstream / "plugins/other/skills/research/SKILL.md"
        other.parent.mkdir(parents=True)
        other.write_text("other package\n")
        git(self.upstream, "add", ".")
        git(self.upstream, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "Add other package")
        revision = git(self.upstream, "rev-parse", "HEAD")
        checkout = self.install_source(revision).parents[1]
        other_skill = str(checkout / "plugins/other/skills/research")
        sync.write_json(self.settings, {"skills": [other_skill]})
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "updated")
        settings = json.loads(self.settings.read_text())
        self.assertEqual(settings["skills"][0], other_skill)
        self.assertEqual(len(settings["skills"]), 2)

    def test_humanize_without_its_advisory_flag_is_not_reported_as_current(self):
        operation = sync.Sync(self.root)
        entry = {**self.entry, "name": "humanize"}
        package = operation.sources.package(entry)
        wrapper = self.home / ".hermes/plugins/humanize"
        sync.write_json(wrapper / "source.json", {
            **entry["source"], "root": str(package.root), "skills": ["skills/writing"], "managed_adapter": False,
        })
        command = self.home / "bin/hermes"
        command.write_text('#!/bin/sh\nprintf \'%s\\n\' \'[{"name":"humanize","status":"enabled"}]\'\n')
        command.chmod(0o755)
        status, _ = operation.hermes(entry, package, False)
        self.assertEqual(status, "drift")

    def test_generated_hermes_adapters_follow_template_changes_but_preserve_local_edits(self):
        command = self.home / "bin/hermes"
        flag = self.home / "hermes-enabled"
        command.write_text('#!/bin/sh\ncase "$2" in\n list) if test -f "' + str(flag) + '"; then printf \'%s\\n\' \'[{"name":"example","status":"enabled"}]\'; else printf \'[]\\n\'; fi ;;\n enable) printf enabled > "' + str(flag) + '" ;;\n doctor) exit 0 ;;\n *) exit 98 ;;\nesac\n')
        command.chmod(0o755)
        operation = sync.Sync(self.root)
        package = operation.sources.package(self.entry)
        status, _ = operation.hermes(self.entry, package, True)
        self.assertEqual(status, "updated")
        template = self.root / "setup/agents/hermes-skills.py"
        template.write_text(template.read_text() + "\n# Updated registration adapter.\n")
        operation = sync.Sync(self.root)
        status, _ = operation.hermes(self.entry, package, True)
        self.assertEqual(status, "updated")
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

    def test_user_changes_to_managed_array_entries_are_conflicts(self):
        self.execute(True)
        settings = json.loads(self.settings.read_text())
        settings["skills"] = ["replacement/custom-skill"]
        sync.write_json(self.settings, settings)
        before = self.settings.read_bytes()
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertEqual(self.settings.read_bytes(), before)

    def test_retiring_a_package_removes_only_recorded_settings_and_keeps_sources(self):
        sync.write_json(self.settings, {"skills": ["personal"], "extensions": ["orca.ts"]})
        operation, _ = self.execute(True)
        self.set_entries([])
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "updated")
        self.assertEqual(json.loads(self.settings.read_text()), {"skills": ["personal"], "extensions": ["orca.ts"]})
        self.assertEqual(json.loads(operation.state_path.read_text())["packages"], {})
        self.assertTrue((self.home / f".pi/agent/skill-sources/example/skills/{self.first}/plugins/example/skills/writing/SKILL.md").exists())

    def test_installer_success_is_not_accepted_when_cached_contents_remain_stale(self):
        operation = sync.Sync(self.root)
        package = operation.sources.package(self.entry)
        installed = self.home / ".codex/plugins/cache/example/example/local"
        shutil.copytree(package.root, installed)
        (installed / "skills/writing/SKILL.md").write_text("old managed contents\n")
        operation.remember("codex", "example", installed, package)
        operation.inventory = [{"pluginId": "example@example", "installed": True, "enabled": True, "version": "local"}]
        command = self.home / "bin/codex"
        command.write_text('#!/bin/sh\ncase "$*" in\n  "plugin add example@example") exit 0 ;;\n  "plugin marketplace list --json") printf \'%s\\n\' \'{"marketplaces":[{"name":"example","root":"' + str(self.root) + '"}]}\' ;;\n  "plugin list --json --marketplace example") printf \'%s\\n\' \'{"installed":[{"pluginId":"example@example","installed":true,"enabled":true,"version":"local"}]}\' ;;\n  *) exit 98 ;;\nesac\n')
        command.chmod(0o755)
        with self.assertRaisesRegex(sync.Conflict, "Native installer did not reconcile"):
            operation.native("codex", self.entry, package, True)
        self.assertEqual((installed / "skills/writing/SKILL.md").read_text(), "old managed contents\n")

    def test_generated_codex_manifest_cannot_add_unapproved_capabilities(self):
        operation = sync.Sync(self.root)
        package = operation.sources.package(self.entry)
        installed = self.home / "installed"
        shutil.copytree(package.root, installed)
        sync.write_json(installed / ".codex-plugin/plugin.json", {
            "name": "example", "skills": None, "hooks": "./injected.json",
        })
        with self.assertRaisesRegex(sync.Conflict, "Unexpected capabilities"):
            operation.native_files(self.entry, installed, package.expected)

    def test_symlinked_settings_are_not_replaced_or_written_through(self):
        target = self.home / "dotfiles/pi.json"
        sync.write_json(target, {"skills": ["personal"]})
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.symlink_to(target)
        before = target.read_bytes()
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertTrue(self.settings.is_symlink())
        self.assertEqual(target.read_bytes(), before)

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
        source = self.home / f".pi/agent/skill-sources/example/skills/{self.first}/plugins/example"
        (source / "unexpected").symlink_to(self.home / "private")
        _, rows = self.execute(True)
        self.assertEqual(rows[0]["status"], "conflict")
        self.assertIn("unexpected", rows[0]["detail"])


if __name__ == "__main__":
    unittest.main()

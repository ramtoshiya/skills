"""Command-level contracts for Claude settings reconciliation."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[3]
SECRET = "secret-sentinel-do-not-print"
BEGIN = b"<!-- BEGIN ramtoshiya:preferences -->"
END = b"<!-- END ramtoshiya:preferences -->"


class ClaudeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.root = self.base / "repo"
        (self.root / "setup/agents").mkdir(parents=True)
        (self.root / ".claude-plugin").mkdir()
        for name in ("sync.py", "claude-settings.json"):
            shutil.copyfile(ROOT / "setup/agents" / name, self.root / "setup/agents" / name)
        terminal = ROOT / "setup/agents/claude-terminal-settings.json"
        if terminal.exists():
            shutil.copyfile(terminal, self.root / "setup/agents" / terminal.name)
        self.source = self.root / "setup/agents/preferences.md"
        self.source.write_text(f"Private instruction {SECRET}\n")
        self.write(self.root / "setup/agents/hosts.json", {
            "hosts": ["claude", "codex"], "plugins": {"example": []},
        })
        self.write(self.root / ".claude-plugin/marketplace.json", {
            "name": "test-market", "plugins": [{"name": "example", "source": "plugins/example"}],
        })
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for host in ("claude", "codex"):
            command = self.bin / host
            command.write_text("#!/bin/sh\nexit 99\n")
            command.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.base / "config"),
            "XDG_STATE_HOME": str(self.base / "state"), "PATH": str(self.bin),
        })
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        self.env.pop("CODEX_HOME", None)
        self.registry = self.base / "config/ramtoshiya/claude-profiles.json"
        self.default = self.home / ".claude/settings.json"
        self.alternate = self.home / ".claude_worker/settings.json"

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")

    def register(self, profiles):
        self.write(self.registry, {"version": 1, "profiles": profiles})

    def run_cli(self, command, *args):
        result = subprocess.run(
            [sys.executable, "-I", str(self.root / "setup/agents/sync.py"), command, *args],
            env=self.env, cwd=self.root, capture_output=True, text=True, check=False,
        )
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        return result

    def settings(self, command, *args):
        return self.run_cli(command, "--host", "claude", "--settings-only", *args)

    def test_required_interaction_rules_reach_every_profile_and_repair_drift(self):
        self.register({"worker": {"configDir": "~/.claude_worker", "overrides": {
            "permissions": {"deny": ["WorkerRule"]},
        }}})
        self.write(self.alternate, {"permissions": {"deny": ["CustomRule"]}})
        result = self.settings("sync", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in (self.default, self.alternate):
            data = json.loads(path.read_text())
            self.assertTrue({"AskUserQuestion", "EnterPlanMode", "EnterWorktree", "SendFeedback"} <= set(data["permissions"]["deny"]))
        worker = json.loads(self.alternate.read_text())
        self.assertTrue({"CustomRule", "WorkerRule"} <= set(worker["permissions"]["deny"]))
        self.assertNotIn("defaultMode", worker["permissions"])
        self.assertNotIn("statusLine", worker)
        worker["permissions"]["deny"].remove("EnterWorktree")
        self.write(self.alternate, worker)
        status = self.settings("status", "--json")
        self.assertEqual(status.returncode, 1, status.stdout + status.stderr)
        row = next(row for row in json.loads(status.stdout) if row["component"] == "settings:worker")
        self.assertEqual(row["status"], "drift")
        self.assertIn("permissions.deny", row["detail"])
        self.assertEqual(self.settings("sync").returncode, 0)
        self.assertIn("EnterWorktree", json.loads(self.alternate.read_text())["permissions"]["deny"])
        self.assertEqual(self.settings("status").returncode, 0)

    def test_registered_profiles_repair_drift_without_copying_private_settings(self):
        self.register({"worker": {"configDir": "~/.claude_worker", "overrides": {"env": {"WORKER_MODE": "1"}}}})
        self.write(self.default, {"env": {"PRIVATE_TOKEN": SECRET}, "permissions": {"deny": ["CustomRule"]}})
        self.write(self.alternate, {
            "env": {"PRIVATE_TOKEN": SECRET}, "permissions": {"allow": ["PersonalRule"]},
            "hooks": {"Stop": [{"command": SECRET}]}, "enabledPlugins": {"private": True},
            "apiKeyHelper": SECRET,
        })
        before = self.alternate.read_bytes()
        status = self.settings("status", "--json")
        self.assertEqual(status.returncode, 1, status.stderr)
        rows = json.loads(status.stdout)
        worker = next(row for row in rows if row["component"] == "settings:worker")
        self.assertEqual(worker["status"], "drift")
        self.assertIn("disableBundledSkills", worker["detail"])
        self.assertIn("enableArtifact", worker["detail"])
        self.assertEqual(self.alternate.read_bytes(), before)
        applied = self.settings("sync", "--json")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        default = json.loads(self.default.read_text())
        alternate = json.loads(self.alternate.read_text())
        self.assertTrue(alternate["disableBundledSkills"])
        self.assertFalse(alternate["enableArtifact"])
        self.assertEqual(alternate["env"]["PRIVATE_TOKEN"], SECRET)
        self.assertEqual(alternate["env"]["WORKER_MODE"], "1")
        self.assertEqual(alternate["permissions"]["allow"], ["PersonalRule"])
        self.assertEqual(set(alternate["permissions"]["deny"]), {"AskUserQuestion", "EnterPlanMode", "EnterWorktree", "SendFeedback"})
        self.assertNotIn("defaultMode", alternate["permissions"])
        self.assertEqual(alternate["hooks"]["Stop"][0]["command"], SECRET)
        self.assertEqual(alternate["enabledPlugins"], {"private": True})
        self.assertEqual(alternate["apiKeyHelper"], SECRET)
        self.assertNotIn("statusLine", alternate)
        self.assertEqual(default["env"]["PRIVATE_TOKEN"], SECRET)
        self.assertEqual(default["statusLine"]["type"], "command")
        self.assertEqual(set(default["permissions"]["deny"]), {"CustomRule", "AskUserQuestion", "EnterPlanMode", "EnterWorktree", "SendFeedback"})
        self.assertEqual(self.settings("status").returncode, 0)

    def test_overrides_baseline_updates_and_repeated_sync(self):
        self.register({
            "terminal": {"configDir": "~/.claude", "overrides": {
                "autoMemoryEnabled": True, "permissions": {"deny": ["ExtraRule"]},
            }},
            "worker": {"configDir": str(self.alternate.parent), "overrides": {
                "disableBundledSkills": False, "env": {"WORKER_TOKEN": SECRET},
            }},
        })
        self.write(self.alternate, {"custom": SECRET})
        self.alternate.chmod(0o640)
        applied = self.settings("sync", "--json")
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        rows = json.loads(applied.stdout)
        self.assertEqual({row["component"] for row in rows}, {
            "settings:terminal", "settings:worker", "instructions:terminal", "instructions:worker",
        })
        self.assertTrue(all("local overrides" in row["detail"] for row in rows if row["component"].startswith("settings:")))
        terminal = json.loads(self.default.read_text())
        worker = json.loads(self.alternate.read_text())
        self.assertTrue(terminal["autoMemoryEnabled"])
        self.assertIn("statusLine", terminal)
        self.assertEqual(set(terminal["permissions"]["deny"]), {
            "ExtraRule", "AskUserQuestion", "EnterPlanMode", "EnterWorktree", "SendFeedback",
        })
        self.assertFalse(worker["disableBundledSkills"])
        self.assertEqual(worker["env"]["WORKER_TOKEN"], SECRET)
        self.assertNotIn("defaultMode", worker["permissions"])
        self.assertNotIn("statusLine", worker)
        self.assertEqual(self.alternate.stat().st_mode & 0o777, 0o640)

        source = self.root / "setup/agents/claude-settings.json"
        common = json.loads(source.read_text())
        common["promptSuggestionEnabled"] = True
        self.write(source, common)
        status = self.settings("status", "--json")
        self.assertEqual(status.returncode, 1)
        rows = json.loads(status.stdout)
        self.assertTrue(all(row["status"] == "drift" for row in rows if row["component"].startswith("settings:")))
        self.assertTrue(all(row["status"] == "ok" for row in rows if row["component"].startswith("instructions:")))
        self.assertEqual(self.settings("sync").returncode, 0)
        self.assertTrue(json.loads(self.default.read_text())["promptSuggestionEnabled"])
        self.assertTrue(json.loads(self.alternate.read_text())["promptSuggestionEnabled"])
        paths = (self.default, self.alternate, self.default.parent / "CLAUDE.md", self.alternate.parent / "CLAUDE.md")
        before = [(path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) for path in paths]
        self.assertEqual(self.settings("sync").returncode, 0)
        after = [(path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) for path in paths]
        self.assertEqual(after, before)
        self.assertEqual(self.alternate.stat().st_mode & 0o777, 0o640)
        clean = self.settings("status", "--json")
        self.assertEqual(clean.returncode, 0)
        worker_row = next(row for row in json.loads(clean.stdout) if row["component"] == "settings:worker")
        self.assertIn("disableBundledSkills", worker_row["detail"])
        self.assertIn("env.WORKER_TOKEN", worker_row["detail"])

    def test_existing_alternate_terminal_choices_are_preserved(self):
        self.register({"worker": {"configDir": "~/.claude_worker"}})
        self.write(self.alternate, {
            "permissions": {"defaultMode": "acceptEdits", "allow": ["PersonalRule"]},
            "statusLine": {"type": "command", "command": "custom-status"},
        })
        self.assertEqual(self.settings("sync").returncode, 0)
        worker = json.loads(self.alternate.read_text())
        self.assertEqual(worker["permissions"]["defaultMode"], "acceptEdits")
        self.assertEqual(worker["permissions"]["allow"], ["PersonalRule"])
        self.assertEqual(worker["statusLine"], {"type": "command", "command": "custom-status"})

    def test_invalid_override_cannot_replace_required_denies(self):
        self.write(self.alternate, {"permissions": {"deny": ["CustomRule"]}})
        original = self.alternate.read_bytes()
        for override in ({"permissions": SECRET}, {"permissions": {"deny": SECRET}}):
            with self.subTest(override="object" if isinstance(override["permissions"], dict) else "scalar"):
                self.register({"worker": {"configDir": "~/.claude_worker", "overrides": override}})
                result = self.settings("sync", "--json")
                self.assertEqual(result.returncode, 1)
                row = next(row for row in json.loads(result.stdout) if row["component"] == "settings:worker")
                self.assertEqual(row["status"], "conflict")
                self.assertEqual(self.alternate.read_bytes(), original)
                self.assertFalse(self.default.exists())
                self.assertFalse((self.alternate.parent / "CLAUDE.md").exists())

    def test_instruction_blocks_preserve_outside_bytes_and_track_source(self):
        self.register({"worker": {"configDir": "~/.claude_worker"}})
        default = self.default.parent / "CLAUDE.md"
        alternate = self.alternate.parent / "CLAUDE.md"
        default.parent.mkdir(parents=True)
        original = b"Private outside " + SECRET.encode() + b"\xff"
        prefix = original + b"\n"
        default.write_bytes(original)
        default.chmod(0o640)
        status = self.settings("status", "--json")
        self.assertEqual(status.returncode, 1)
        self.assertEqual({row["component"] for row in json.loads(status.stdout) if row["component"].startswith("instructions:")},
                         {"instructions:default", "instructions:worker"})
        self.assertEqual(self.settings("sync").returncode, 0)
        source = self.source.read_bytes()
        self.assertEqual(default.read_bytes(), prefix + BEGIN + b"\n" + source + END + b"\n")
        self.assertEqual(alternate.read_bytes(), BEGIN + b"\n" + source + END + b"\n")
        default.write_bytes(original)
        alternate.unlink()
        status = self.settings("status", "--json")
        self.assertEqual(status.returncode, 1)
        rows = {row["component"]: row["status"] for row in json.loads(status.stdout)}
        self.assertEqual(rows["settings:default"], "ok")
        self.assertEqual(rows["settings:worker"], "ok")
        self.assertEqual(rows["instructions:default"], "drift")
        self.assertEqual(rows["instructions:worker"], "drift")
        self.assertEqual(self.settings("sync").returncode, 0)
        suffix = b"\r\nPrivate suffix " + SECRET.encode() + b"\x80"
        default.write_bytes(prefix + BEGIN + b"\n" + source + END + suffix)
        updated = f"Updated instruction {SECRET}\n".encode()
        self.source.write_bytes(updated)
        status = self.settings("status", "--json")
        self.assertEqual(status.returncode, 1)
        self.assertTrue(all(row["status"] == "drift" for row in json.loads(status.stdout)
                            if row["component"].startswith("instructions:")))
        self.assertEqual(self.settings("sync").returncode, 0)
        self.assertEqual(default.read_bytes(), prefix + BEGIN + b"\n" + updated + END + suffix)
        self.assertEqual(alternate.read_bytes(), BEGIN + b"\n" + updated + END + b"\n")
        self.assertEqual(default.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.settings("status").returncode, 0)

    def test_malformed_or_symlinked_instruction_files_are_not_overwritten(self):
        self.register({"worker": {"configDir": "~/.claude_worker"}})
        self.assertEqual(self.settings("sync").returncode, 0)
        path = self.alternate.parent / "CLAUDE.md"
        private = SECRET.encode()
        cases = [
            BEGIN + b"\n" + private,
            private + b"\n" + END,
            END + b"\n" + BEGIN,
            BEGIN + b"\n" + END + b"\n" + BEGIN + b"\n" + END,
            b"<!-- BEGIN ramtoshiya:preferences -- >\n" + private + b"\n" + END,
            BEGIN + b"\n" + END + b"\n<!-- END ramtoshiya:preferences -- >",
        ]
        for contents in cases:
            with self.subTest(case=cases.index(contents)):
                path.write_bytes(contents)
                for command in ("status", "sync"):
                    result = self.settings(command, "--json")
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    row = next(row for row in json.loads(result.stdout) if row["component"] == "instructions:worker")
                    self.assertEqual(row["status"], "conflict")
                    self.assertEqual(path.read_bytes(), contents)
        target = self.base / "private-instructions"
        target.write_text(SECRET)
        path.unlink()
        path.symlink_to(target)
        result = self.settings("sync", "--json")
        self.assertEqual(result.returncode, 1)
        row = next(row for row in json.loads(result.stdout) if row["component"] == "instructions:worker")
        self.assertEqual(row["status"], "conflict")
        self.assertIn("symlinked", row["detail"])
        self.assertTrue(path.is_symlink())
        self.assertEqual(target.read_text(), SECRET)

    def test_mise_has_one_claude_profile_writer(self):
        config = tomllib.loads((ROOT / "mise.toml").read_text())
        dotfiles = config["dotfiles"]
        self.assertEqual(dotfiles["~/.codex/AGENTS.md"]["source"], "setup/agents/preferences.md")
        self.assertFalse(any(path == "~/.claude/CLAUDE.md" or path.startswith("~/.claude/settings.json/")
                             or path == "~/.claude/settings.json" for path in dotfiles))

    def test_bootstrap_task_reconciles_profiles_in_an_isolated_home(self):
        mise = shutil.which("mise")
        if mise is None:
            self.skipTest("mise is not installed")
        uv = next((candidate for directory in os.get_exec_path()
                   if (candidate := shutil.which("uv", path=directory))
                   and Path(candidate).resolve() != Path(mise).resolve()), None)
        if uv is None:
            self.skipTest("a standalone uv executable is not installed")
        runtime = subprocess.run([uv, "python", "dir"], capture_output=True, text=True,
                                 check=False, timeout=30)
        self.assertEqual(runtime.returncode, 0, runtime.stderr)
        managed_python = runtime.stdout.strip()
        env = {key: value for key, value in self.env.items() if not key.startswith("MISE_")}
        env.update({
            "PATH": str(self.bin) + os.pathsep + "/usr/bin:/bin:/usr/sbin:/sbin",
            "MISE_TRUSTED_CONFIG_PATHS": str(self.root),
            "MISE_DATA_DIR": str(self.base / "mise-data"),
            "MISE_CACHE_DIR": str(self.base / "mise-cache"),
            "MISE_STATE_DIR": str(self.base / "mise-state"),
            "MISE_CONFIG_DIR": str(self.base / "mise-config"),
            "MISE_AUTO_INSTALL": "0",
        })
        probe = subprocess.run([mise, "bootstrap", "--help"], env=env, cwd=self.root,
                               capture_output=True, text=True, check=False, timeout=30)
        if probe.returncode or "--only" not in probe.stdout or "task" not in probe.stdout:
            self.skipTest("mise does not support bootstrap task selection")
        dotfiles = tomllib.loads((ROOT / "mise.toml").read_text())["dotfiles"]
        shutil.copyfile(ROOT / "mise.toml", self.root / "mise.toml")
        for entry in dotfiles.values():
            if "source" in entry:
                source = Path(entry["source"])
                target = self.root / source
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / source, target)
        self.register({"worker": {"configDir": "~/.claude_worker", "overrides": {
            "disableBundledSkills": False, "permissions": {"deny": ["OverrideRule"]},
        }}})
        self.write(self.alternate, {"permissions": {"deny": ["CustomRule"]}})
        before = self.alternate.read_bytes()
        (self.bin / "uv").symlink_to(uv)
        env["UV_PYTHON_INSTALL_DIR"] = str(self.base / "missing-python")

        def bootstrap(*args, success=True):
            result = subprocess.run([mise, "bootstrap", *args], env=env, cwd=self.root,
                                    capture_output=True, text=True, check=False, timeout=60)
            self.assertNotIn(SECRET, result.stdout + result.stderr)
            if success:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            else:
                self.assertNotEqual(result.returncode, 0)
            return result

        home_entries = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))
        bootstrap("--dry-run")
        self.assertEqual(sorted(path.relative_to(self.home) for path in self.home.rglob("*")), home_entries)
        self.assertEqual(self.alternate.read_bytes(), before)
        self.assertFalse(self.default.exists())
        self.assertFalse((self.alternate.parent / "CLAUDE.md").exists())
        missing_runtime = bootstrap("--only", "task", success=False)
        self.assertIn("No interpreter found for Python >=3.11", missing_runtime.stderr)
        self.assertIn("offline", missing_runtime.stderr)
        self.assertEqual(self.alternate.read_bytes(), before)
        self.assertFalse(self.default.exists())
        self.assertFalse((self.alternate.parent / "CLAUDE.md").exists())
        env["UV_PYTHON_INSTALL_DIR"] = managed_python
        bootstrap("--only", "task")
        worker = json.loads(self.alternate.read_text())
        self.assertFalse(worker["disableBundledSkills"])
        self.assertEqual(set(worker["permissions"]["deny"]), {
            "CustomRule", "OverrideRule", "AskUserQuestion", "EnterPlanMode", "EnterWorktree", "SendFeedback",
        })
        self.assertNotIn("defaultMode", worker["permissions"])
        self.assertNotIn("statusLine", worker)
        self.assertTrue((self.default.parent / "CLAUDE.md").is_file())
        self.assertTrue((self.alternate.parent / "CLAUDE.md").is_file())
        paths = (self.default, self.alternate, self.default.parent / "CLAUDE.md", self.alternate.parent / "CLAUDE.md")
        before = [(path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) for path in paths]
        bootstrap("--only", "task")
        self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) for path in paths], before)

    def test_registry_defaults_to_home_config_directory(self):
        self.env.pop("XDG_CONFIG_HOME")
        self.registry = self.home / ".config/ramtoshiya/claude-profiles.json"
        self.register({"worker": {"configDir": "~/.claude_worker"}})
        self.assertEqual(self.settings("sync").returncode, 0)
        self.assertTrue(json.loads(self.alternate.read_text())["disableBundledSkills"])
        self.assertEqual(self.settings("status").returncode, 0)

    def test_unregistered_roots_are_reported_without_being_modified(self):
        self.write(self.alternate, {"env": {"PRIVATE_TOKEN": SECRET}})
        original = self.alternate.read_bytes()
        instructions = self.alternate.parent / "CLAUDE.md"
        instructions.write_text(SECRET)
        external = self.base / "external/worker"
        self.env["CLAUDE_CONFIG_DIR"] = str(external)
        for command in ("status", "sync"):
            result = self.settings(command, "--json")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            rows = json.loads(result.stdout)
            unregistered = [row for row in rows if row["component"] == "settings:unregistered"]
            self.assertEqual(len(unregistered), 2)
            details = " ".join(row["detail"] for row in unregistered)
            self.assertIn(str(self.alternate), details)
            self.assertIn(str(external / "settings.json"), details)
            self.assertIn("register", details)
            self.assertIn(str(self.registry), details)
            self.assertEqual(self.alternate.read_bytes(), original)
            self.assertEqual(instructions.read_text(), SECRET)
            self.assertFalse(external.exists())
        self.register({
            "worker": {"configDir": "~/.claude_worker"},
            "external": {"configDir": str(external)},
        })
        self.assertEqual(self.settings("sync").returncode, 0)
        self.assertTrue((external / "settings.json").is_file())
        self.assertEqual(json.loads(self.alternate.read_text())["env"]["PRIVATE_TOKEN"], SECRET)
        self.assertEqual(self.settings("status").returncode, 0)

    def test_invalid_registry_never_overwrites_managed_targets(self):
        self.write(self.default, {"env": {"PRIVATE_TOKEN": SECRET}})
        original = self.default.read_bytes()
        instructions = self.default.parent / "CLAUDE.md"
        instructions.write_text(SECRET)
        cases = [
            "{\"secret\": \"" + SECRET + "\",",
            "[]",
            json.dumps({"version": 2, "profiles": {}}),
            json.dumps({"version": 1, "profiles": {"worker": {"configDir": "relative/path"}}}),
            json.dumps({"version": 1, "profiles": {"worker": {"configDir": "~/.worker", "override": {}}}}),
            json.dumps({"version": 1, "profiles": {"worker": {"configDir": "~/.worker", "overrides": []}}}),
            json.dumps({"version": 1, "profiles": {
                "one": {"configDir": "~/.claude"}, "two": {"configDir": str(self.home / ".claude")},
            }}),
            '{"version": 1, "version": 1, "profiles": {}}',
        ]
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        for contents in cases:
            with self.subTest(contents=contents.replace(SECRET, "<secret>")):
                self.registry.write_text(contents)
                for command in ("status", "sync"):
                    result = self.settings(command, "--json")
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(json.loads(result.stdout)[0]["status"], "conflict")
                    self.assertIn(str(self.registry), result.stdout)
                    self.assertEqual(self.default.read_bytes(), original)
                    self.assertEqual(instructions.read_text(), SECRET)

    def test_invalid_settings_are_reported_without_overwriting_them(self):
        self.default.parent.mkdir(parents=True, exist_ok=True)
        cases = [
            '{"env": "' + SECRET + '",',
            "[]",
            json.dumps({"env": SECRET}),
            json.dumps({"permissions": {"deny": SECRET}}),
            '{"env": {}, "env": {}}',
            '{"autoCompactWindow": NaN}',
        ]
        for contents in cases:
            with self.subTest(contents=contents.replace(SECRET, "<secret>")):
                self.default.write_text(contents)
                for command in ("status", "sync"):
                    result = self.settings(command, "--json")
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(json.loads(result.stdout)[0]["status"], "conflict")
                    self.assertIn(str(self.default), result.stdout)
                    self.assertEqual(self.default.read_text(), contents)

    def test_cli_scope_does_not_run_unselected_reconciliation(self):
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text("invalid registry")
        log = self.base / "host-calls"
        for host in ("claude", "codex"):
            marketplaces = ([{"name": "test-market", "path": str(self.root)}] if host == "claude"
                            else {"marketplaces": [{"name": "test-market", "root": str(self.root)}]})
            inventory = [] if host == "claude" else {"installed": []}
            script = (
                "#!/bin/sh\n"
                f"printf '%s\\n' {shlex.quote(host)} >> {shlex.quote(str(log))}\n"
                'case "$*" in\n'
                f"  'plugin marketplace list --json') printf '%s\\n' {shlex.quote(json.dumps(marketplaces))} ;;\n"
                f"  'plugin list --json'|'plugin list --json --marketplace test-market') printf '%s\\n' {shlex.quote(json.dumps(inventory))} ;;\n"
                "  *) exit 99 ;;\nesac\n"
            )
            (self.bin / host).write_text(script)
        for command in ("status", "sync"):
            for args in (("--host", "claude", "--plugin", "example"), ("--host", "codex")):
                result = self.run_cli(command, *args, "--json")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout), [])
        log.unlink()
        self.register({})
        ownership = self.base / "state/ramtoshiya-agents/state.json"
        ownership.parent.mkdir(parents=True, exist_ok=True)
        ownership.write_text("invalid plugin ownership state")
        result = self.run_cli("sync", "--settings-only", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(log.exists())
        ownership.unlink()
        result = self.run_cli("status", "--host", "claude", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({row["component"] for row in json.loads(result.stdout)}, {
            "settings:default", "instructions:default",
        })
        for args in (("--settings-only", "--plugin", "example"), ("--settings-only", "--host", "codex")):
            result = self.run_cli("status", *args)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--settings-only", result.stderr)


if __name__ == "__main__":
    unittest.main()

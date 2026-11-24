"""Command-level contracts for the shared preferences in every Hermes profile's SOUL.md."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
BEGIN = b"<!-- BEGIN ramtoshiya:preferences -->"
END = b"<!-- END ramtoshiya:preferences -->"
PERSONA = b"You are Hermes Agent. Be direct."
OPERATOR = b"\n\n<!-- BEGIN ramtoshiya:operator -->\nYou are an operator.\n<!-- END ramtoshiya:operator -->\n"


def load_operator_profile():
    spec = importlib.util.spec_from_file_location("operator_profile_under_test", ROOT / "setup/hermes/operator_profile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HermesPreferencesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.root = base / "repo"
        (self.root / "setup/agents").mkdir(parents=True)
        for name in ("sync.py", "hook_binary.py", "level.py", "claude-settings.json", "claude-terminal-settings.json"):
            shutil.copyfile(ROOT / "setup/agents" / name, self.root / "setup/agents" / name)
        self.source = self.root / "setup/agents/preferences.md"
        self.source.write_bytes(b"# Preferences\n\nCatch mistakes.\n")
        self.env = {**os.environ, "HOME": str(self.home), "XDG_CONFIG_HOME": str(base / "config"),
                    "XDG_STATE_HOME": str(base / "state"), "PATH": "/usr/bin:/bin"}
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        self.hermes = self.home / ".hermes"

    def profile(self, name, files):
        directory = self.hermes / "profiles" / name if name != "default" else self.hermes
        directory.mkdir(parents=True, exist_ok=True)
        for file, data in files.items():
            (directory / file).parent.mkdir(parents=True, exist_ok=True)
            (directory / file).write_bytes(data)
        return directory

    def run_cli(self, command, *args):
        result = subprocess.run([sys.executable, "-I", str(self.root / "setup/agents/sync.py"), command,
                                 "--settings-only", *args, "--json"],
                                env=self.env, cwd=self.root, capture_output=True, text=True, check=False)
        return result.returncode, {row["component"]: row for row in json.loads(result.stdout) if row["host"] == "hermes"}

    def block(self):
        return BEGIN + b"\n" + self.source.read_bytes() + END + b"\n"

    def test_every_profile_loads_the_preferences_next_to_its_own_text(self):
        default = self.profile("default", {"SOUL.md": PERSONA})
        operator = self.profile("operator", {"config.yaml": b"{}\n", "SOUL.md": PERSONA + OPERATOR})
        work = self.profile("work", {".env": b"", "SOUL.md": PERSONA + b"\n"})
        ghost = self.profile("ghost", {"logs/run.log": b"cron\n"})
        gone = self.profile("gone", {"SOUL.md": PERSONA})
        (self.hermes / "profiles/.deleted/gone").mkdir(parents=True)

        code, rows = self.run_cli("status")
        self.assertEqual(code, 1)
        self.assertEqual({name: row["status"] for name, row in rows.items()}, {
            "instructions:default": "drift", "instructions:operator": "drift", "instructions:work": "drift"})

        code, rows = self.run_cli("sync")
        self.assertEqual(code, 0, rows)
        self.assertEqual((default / "SOUL.md").read_bytes(), PERSONA + b"\n" + self.block())
        self.assertEqual((operator / "SOUL.md").read_bytes(), PERSONA + OPERATOR + self.block())
        self.assertEqual((work / "SOUL.md").read_bytes(), PERSONA + b"\n" + self.block())
        self.assertEqual(sorted(p.name for p in ghost.rglob("*")), ["logs", "run.log"])
        self.assertEqual((gone / "SOUL.md").read_bytes(), PERSONA)
        self.assertEqual(self.run_cli("status")[0], 0)

        soul = operator / "SOUL.md"
        soul.write_text(load_operator_profile().with_soul_block(soul.read_text(), "You are a changed operator."))
        self.assertIn(self.block(), soul.read_bytes())
        self.assertEqual(self.run_cli("status")[0], 0)

        self.source.write_bytes(b"# Preferences\n\nCatch mistakes, not bypass.\n")
        code, rows = self.run_cli("status")
        self.assertEqual(code, 1)
        self.assertTrue(all(row["status"] == "drift" for row in rows.values()))
        self.assertEqual(self.run_cli("sync")[0], 0)
        self.assertIn(b"You are a changed operator.", soul.read_bytes())
        self.assertIn(self.block(), soul.read_bytes())
        self.assertEqual(self.run_cli("status")[0], 0)

    def test_profile_without_soul_is_reported_and_left_for_hermes_to_seed(self):
        self.profile("default", {"SOUL.md": PERSONA})
        operator = self.profile("operator", {"config.yaml": b"{}\n"})
        code, rows = self.run_cli("sync")
        self.assertEqual(code, 1)
        self.assertEqual(rows["instructions:operator"]["status"], "conflict")
        self.assertEqual(rows["instructions:default"]["status"], "updated")
        self.assertFalse((operator / "SOUL.md").exists())

    def test_machine_without_hermes_is_absent_and_unchanged(self):
        code, rows = self.run_cli("sync")
        self.assertEqual(code, 0)
        self.assertEqual(rows["host"]["status"], "absent")
        self.assertFalse(self.hermes.exists())

    def test_hermes_alone_skips_claude_profiles(self):
        self.profile("default", {"SOUL.md": PERSONA})
        result = subprocess.run([sys.executable, "-I", str(self.root / "setup/agents/sync.py"), "sync",
                                 "--settings-only", "--host", "hermes", "--json"],
                                env=self.env, cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({row["host"] for row in json.loads(result.stdout)}, {"hermes"})
        self.assertFalse((self.home / ".claude").exists())


if __name__ == "__main__":
    unittest.main()

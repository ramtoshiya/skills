import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3] / "plugins/ramtoshiya-cc/hermes-learning"
HOOK = ROOT / "hook.py"
LAUNCH = ROOT / "launch.py"
ENTRY = "runpy.run_module('hermes_learning_entry', run_name='__main__', alter_sys=True)"
# Stands in for Hermes's tools.skill_usage and appends each call to $CALLS.
FAKE_USAGE = """import json, os
def read_skill_name(path, fallback):
    for line in path.read_text().splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return fallback
def _log(*row):
    with open(os.environ["CALLS"], "a") as calls:
        calls.write(json.dumps([*row, os.environ["HERMES_HOME"]]) + "\\n")
def bump_view(name):
    _log("view", name, None)
def bump_use(name, *, session_id=None):
    _log("use", name, session_id)
"""


def skill(root, folder, name=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(f"---\nname: {name or folder}\ndescription: test\n---\n")
    return root


class HermesLearningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.store = self.tmp / "store"
        (self.store / "memories").mkdir(parents=True)
        self.calls = self.tmp / "calls.jsonl"
        self.env = {**os.environ, "HERMES_LEARNING_HOME": str(self.store), "CALLS": str(self.calls),
                    "PATH": f"{self.tmp / 'bin'}{os.pathsep}{os.environ['PATH']}"}
        self.env.pop("_HERMES_GATEWAY", None)
        self.fake_hermes()

    def fake_hermes(self):
        """A `hermes` whose runtime command runs the entry with a fake tools package on the path."""
        fake_root = self.tmp / "fake"
        (fake_root / "tools").mkdir(parents=True)
        (fake_root / "tools/__init__.py").write_text("")
        (fake_root / "tools/skill_usage.py").write_text(FAKE_USAGE)
        code = f"import runpy, sys; sys.path.insert(0, {str(fake_root)!r}); {ENTRY}"
        printed = json.dumps([sys.executable, "-I", "-c", code])
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        hermes = bin_dir / "hermes"
        hermes.write_text(f"#!/bin/sh\n[ \"$1\" = --print-runtime-command ] || exit 9\ncat <<'EOF'\n{printed}\nEOF\n")
        hermes.chmod(0o755)

    def hook(self, event, payload, env=None):
        result = subprocess.run([sys.executable, str(HOOK), event], input=json.dumps(payload),
                                capture_output=True, text=True, env=env or self.env, check=True)
        return json.loads(result.stdout)

    def test_session_start_adds_the_memory_snapshot(self):
        (self.store / "memories/USER.md").write_text("Prefers short answers.\n")
        (self.store / "memories/MEMORY.md").write_text("The build runs with npm test.\n")
        context = self.hook("session-start", {"session_id": "s1"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("## Hermes User profile (USER.md)\n\nPrefers short answers.", context)
        self.assertIn("## Hermes Environment memory (MEMORY.md)\n\nThe build runs with npm test.", context)

    def test_session_start_links_learned_skills_into_the_plugin(self):
        skills = self.store / "skills"
        skill(skills / "dev/flaky-checks", "flaky-checks")
        skill(skills / "bundled-one", "bundled-one")
        skill(skills / ".archive/old", "old")
        (skills / ".bundled_manifest").write_text("bundled-one:abc\n")
        plugin = self.store / "claude-skills-plugin"
        (plugin / "skills").mkdir(parents=True)
        (plugin / "skills/removed").symlink_to(self.tmp, target_is_directory=True)
        self.assertEqual(self.hook("session-start", {"session_id": "s1"}), {})
        self.assertEqual(json.loads((plugin / ".claude-plugin/plugin.json").read_text())["name"], "hermes-skills")
        links = {path.name: path.resolve() for path in (plugin / "skills").iterdir()}
        self.assertEqual(links, {"flaky-checks": (skills / "dev/flaky-checks").resolve()})

    def test_session_start_is_silent_in_the_coder_runtime_and_without_a_store(self):
        (self.store / "memories/USER.md").write_text("Prefers short answers.\n")
        self.assertEqual(self.hook("session-start", {"session_id": "s1"}, {**self.env, "_HERMES_GATEWAY": "1"}), {})
        self.assertFalse((self.store / "claude-skills-plugin").exists())
        missing = {**self.env, "HERMES_LEARNING_HOME": str(self.tmp / "absent")}
        self.assertEqual(self.hook("session-start", {"session_id": "s1"}, missing), {})

    def test_skill_use_records_view_and_use_under_the_frontmatter_name(self):
        skill(self.store / "skills/dev/flaky-checks", "flaky-checks", name="flaky-check-diagnosis")
        event = {"session_id": "sess-1", "tool_name": "Skill", "tool_input": {"skill": "hermes-skills:flaky-checks"}}
        self.assertEqual(self.hook("skill-used", event), {})
        rows = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(rows, [["view", "flaky-check-diagnosis", None, str(self.store)],
                                ["use", "flaky-check-diagnosis", "sess-1", str(self.store)]])

    def test_skill_use_of_other_plugins_records_nothing(self):
        skill(self.store / "skills/flaky-checks", "flaky-checks")
        for name in ("ramtoshiya:flaky-checks", "flaky-checks", "hermes-skills:unknown"):
            self.hook("skill-used", {"session_id": "s", "tool_name": "Skill", "tool_input": {"skill": name}})
        self.assertFalse(self.calls.exists())

    def test_launcher_names_what_is_missing(self):
        def launch(env):
            return subprocess.run([sys.executable, str(LAUNCH)], capture_output=True, text=True, env=env,
                                  stdin=subprocess.DEVNULL)

        result = launch({**self.env, "HERMES_LEARNING_HOME": str(self.tmp / "absent")})
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"the Hermes learning store {self.tmp / 'absent'} does not exist", result.stderr)
        no_hermes = {**self.env, "PATH": "/usr/bin:/bin", "HOME": str(self.tmp)}
        self.assertIn("Hermes is not installed", launch(no_hermes).stderr)
        self.assertIn("off in the Hermes coder runtime", launch({**self.env, "_HERMES_GATEWAY": "1"}).stderr)


if __name__ == "__main__":
    unittest.main()

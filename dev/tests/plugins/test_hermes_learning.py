import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3] / "plugins/ramtoshiya-cc/hermes-learning"
HOOK = ROOT / "hook.py"
CLI = ROOT / "cli.py"
CHECK = ROOT.parents[2] / "dev/automation/memory-consolidation/check.py"
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
        for name in ("BB_THREAD_ID", "BB_CLI"):
            self.env.pop(name, None)
        self.fake_hermes()

    def fake_hermes(self):
        """A `hermes` whose runtime command runs the entry with a fake tools package on the path."""
        fake_root = self.tmp / "fake"
        (fake_root / "tools").mkdir(parents=True)
        (fake_root / "tools/__init__.py").write_text("")
        (fake_root / "tools/skill_usage.py").write_text(FAKE_USAGE)
        (fake_root / "tools/registry.py").write_text("registry = None\n")
        (fake_root / "tools/skill_provenance.py").write_text(
            "import os\ndef set_current_write_origin(origin):\n    os.environ['ORIGIN'] = origin\n")
        (fake_root / "model_tools.py").write_text(
            "import json, os\ndef handle_function_call(name, args, **_):\n"
            "    return json.dumps({'tool': name, 'args': args, 'origin': os.environ['ORIGIN']})\n")
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

    def in_thread(self, thread):
        """The environment of a bb thread, which a fake `bb thread show` describes."""
        bb = self.tmp / "bb"
        bb.write_text(f"#!/bin/sh\ncat <<'EOF'\n{json.dumps({'thread': thread})}\nEOF\n")
        bb.chmod(0o755)
        return {**self.env, "BB_CLI": str(bb), "BB_THREAD_ID": "thr_test"}

    def role_of(self, thread):
        code = f"import runpy; print(runpy.run_path({str(ROOT / 'store.py')!r})['role']())"
        return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                              env=self.in_thread(thread), check=True).stdout.strip()

    def cli(self, *args, stdin="", env=None):
        return subprocess.run([sys.executable, str(CLI), *args], input=stdin, capture_output=True, text=True,
                              env=env or self.env)

    def test_only_a_titled_review_fork_writes_as_a_review(self):
        self.assertEqual(self.role_of({"originKind": "fork", "title": "Hermes review"}), "review")
        self.assertEqual(self.role_of({"originKind": "fork", "title": "(1) feature work"}), "top")
        self.assertEqual(self.role_of({"parentThreadId": "thr_parent"}), "child")
        self.assertEqual(self.role_of({}), "top")

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
        self.hook("session-start", {"session_id": "s1"})
        self.assertEqual(json.loads((plugin / ".claude-plugin/plugin.json").read_text())["name"], "hermes-skills")
        links = {path.name: path.resolve() for path in (plugin / "skills").iterdir()}
        self.assertEqual(links, {"flaky-checks": (skills / "dev/flaky-checks").resolve()})

    def test_session_start_is_silent_without_a_store(self):
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

    def test_cli_names_what_is_missing(self):
        result = self.cli("skill_view", env={**self.env, "HERMES_LEARNING_HOME": str(self.tmp / "absent")})
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"the Hermes learning store {self.tmp / 'absent'} does not exist", result.stderr)
        no_hermes = {**self.env, "PATH": "/usr/bin:/bin", "HOME": str(self.tmp)}
        self.assertIn("Hermes is not installed", self.cli("skill_view", env=no_hermes).stderr)

    def test_cli_runs_the_tool_with_the_role_origin_and_unprefixed_skill_name(self):
        """Claude Code lists the skills as hermes-skills:<name>, and agents pass that name to the tools."""
        arguments = json.dumps({"name": "hermes-skills:flaky-checks"})
        for thread, origin in (({}, "foreground"), ({"originKind": "fork", "title": "Hermes review"},
                                                    "background_review")):
            result = self.cli("skill_view", stdin=arguments, env=self.in_thread(thread))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.splitlines()[-1]),
                             {"tool": "skill_view", "args": {"name": "flaky-checks"}, "origin": origin})

    def test_cli_refuses_writes_to_child_threads(self):
        entry = json.dumps({"action": "add", "target": "memory", "content": "x"})
        child = self.cli("memory", stdin=entry, env=self.in_thread({"parentThreadId": "thr_parent"}))
        self.assertEqual(child.returncode, 1)
        self.assertIn("Learning proposals", child.stderr)
        self.assertFalse(self.calls.exists())

    def test_cli_leaves_staged_writes_to_foreground_sessions(self):
        review = self.cli("pending", "approve", "abc", env=self.in_thread({"originKind": "fork",
                                                                          "title": "Hermes review"}))
        self.assertEqual(review.returncode, 1)
        self.assertIn("cannot decide them itself", review.stderr)

    def consolidation_check(self, *args):
        spawns = self.tmp / "spawns.jsonl"
        spawns.unlink(missing_ok=True)
        bb = self.tmp / "bb-spawn"
        bb.write_text("#!/bin/sh\n"
                      f"python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \"$@\" >> {spawns}\n"
                      "for arg; do case $prev in --prompt-file) cp \"$arg\" " f"{self.tmp}/prompt.md;; esac; prev=$arg; done\n"
                      "echo '{\"id\": \"thr_new\"}'\n")
        bb.chmod(0o755)
        result = subprocess.run([sys.executable, str(CHECK), *args], capture_output=True, text=True, check=True,
                                env={**self.env, "BB_CLI": str(bb), "BB_PROJECT_ID": "proj_test"})
        calls = [json.loads(line) for line in spawns.read_text().splitlines()] if spawns.exists() else []
        return result.stdout, calls

    def test_consolidation_check_is_silent_when_nothing_changed_since_the_last_consolidation(self):
        (self.store / "memories/USER.md").write_text("Prefers tables.")
        skill(self.store / "skills/dev/ui-review", "ui-review")
        self.consolidation_check("--mark")
        (self.store / "skills/.usage.json").write_text("{}")
        self.assertEqual(self.consolidation_check(), ("", []))

    def test_consolidation_check_starts_one_full_access_thread_for_each_kind_of_change(self):
        def change_memory():
            (self.store / "memories/USER.md").write_text("Prefers tables.\n\u00a7\nPrefers lists.")

        def change_skill():
            (self.store / "skills/dev/ui-review/SKILL.md").write_text("---\nname: ui-review\n---\nChanged\n")

        def stage_write():
            (self.store / "pending/memory").mkdir(parents=True, exist_ok=True)
            (self.store / "pending/memory/b281298d.json").write_text("{}")

        for change, expected in ((change_memory, '"user"'), (change_skill, '"ui-review"'),
                                 (stage_write, '"b281298d"')):
            with self.subTest(change=change.__name__):
                (self.store / "memories/USER.md").write_text("Prefers tables.")
                skill(self.store / "skills/dev/ui-review", "ui-review")
                for pending in (self.store / "pending/memory").glob("*.json"):
                    pending.unlink()
                self.consolidation_check("--mark")
                change()
                output, calls = self.consolidation_check()
                self.assertIn("Started thr_new", output)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][calls[0].index("--permission-mode") + 1], "full")
                self.assertEqual(calls[0][calls[0].index("--environment") + 1], str(ROOT.parents[2]))
                prompt = (self.tmp / "prompt.md").read_text()
                self.assertIn(f"HERMES_LEARNING_HOME={self.store} {ROOT / 'hermes-learning'}", prompt)
                self.assertIn(f"{CHECK} --mark", prompt)
                self.assertNotIn("{{", prompt)
                self.assertIn(expected, prompt.split("## State")[1])

    def test_session_start_tells_each_role_how_to_learn(self):
        def context(thread):
            output = self.hook("session-start", {"session_id": "s1"}, self.in_thread(thread))
            return output["hookSpecificOutput"]["additionalContext"]

        top = context({})
        self.assertIn(f"{ROOT / 'hermes-learning'} schema <tool>", top)
        self.assertIn("--title \"Hermes review\"", top)
        self.assertIn("Learning proposals", context({"parentThreadId": "thr_parent"}))


if __name__ == "__main__":
    unittest.main()

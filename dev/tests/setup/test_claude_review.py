import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[3] / "setup/agents/claude-review.py"
T3_SETTINGS = '{"fastMode":false,"showThinkingSummaries":true}'
# Stands in for claude: records the arguments and environment it was started with.
FAKE_CLAUDE = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["CAPTURE"], "w") as file:
    json.dump({{"argv": sys.argv[1:], "env": dict(os.environ)}}, file)
"""
STOPPED = {"continue": False, "stopReason": "Review time budget of 30 minutes is used up."}


class ClaudeReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        # The quote and the space show that the hook command quotes the script path.
        self.script = root / "it's here" / "claude-review.py"
        self.script.parent.mkdir()
        shutil.copy(SCRIPT, self.script)
        self.bin = root / "bin"
        self.bin.mkdir()
        (self.bin / "claude").write_text(FAKE_CLAUDE)
        (self.bin / "claude").chmod(0o755)
        self.tmp = root / "tmp"
        self.tmp.mkdir()
        self.capture = root / "capture.json"
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("CLAUDE_REVIEW_")}
        self.env.update(PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", CAPTURE=str(self.capture),
                        TMPDIR=str(self.tmp))

    def launch(self, args, **env):
        """Run the launcher. Return its result and what the fake claude recorded, or None."""
        self.capture.unlink(missing_ok=True)
        result = subprocess.run([sys.executable, str(self.script), *args], capture_output=True, text=True,
                                env={**self.env, **env}, timeout=30)
        return result, json.loads(self.capture.read_text()) if self.capture.exists() else None

    def assert_refused(self, args, **env):
        result, claude = self.launch(args, **env)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertRegex(result.stderr, r"\Aclaude-review: [^\n]+\n\Z")
        self.assertNotIn("private", result.stderr)
        self.assertIsNone(claude, "claude was started")

    def test_folds_settings_into_one_flag_and_adds_the_hooks(self):
        extra = self.script.parent / "extra.json"
        extra.write_text('{"showThinkingSummaries": false, "env": {"B": "3", "C": "4"}, "extra": 1}')
        theirs = {"matcher": "Bash", "hooks": [{"type": "command", "command": "theirs"}]}
        inline = json.dumps({"fastMode": False, "showThinkingSummaries": True, "env": {"A": "1", "B": "2"},
                             "hooks": {"PreToolUse": [theirs]}})
        result, claude = self.launch(["--output-format", "stream-json", "--settings", inline, "--verbose",
                                      f"--settings={extra}", "--model", "m", "--", "--settings", "kept"])
        self.assertEqual(result.returncode, 0, result.stderr)
        flag, merged, *rest = claude["argv"]
        self.assertEqual(flag, "--settings")
        self.assertEqual(rest, ["--output-format", "stream-json", "--verbose", "--model", "m",
                                "--", "--settings", "kept"])
        settings = json.loads(merged)
        hooks = settings.pop("hooks")
        self.assertEqual(settings, {"fastMode": False, "showThinkingSummaries": False,
                                    "env": {"A": "1", "B": "3", "C": "4"}, "extra": 1})
        self.assertEqual(hooks["PreToolUse"][0], theirs)
        for event, entries in {"UserPromptSubmit": 1, "PreToolUse": 2, "PostToolUse": 1}.items():
            self.assertEqual(len(hooks[event]), entries)
            self.assertEqual([hook["type"] for hook in hooks[event][-1]["hooks"]], ["command"])

    def test_settings_hook_commands_run_the_hook(self):
        _, claude = self.launch(["--settings", T3_SETTINGS])
        hooks = json.loads(claude["argv"][1])["hooks"]

        def run(event):
            result = subprocess.run(hooks[event][-1]["hooks"][0]["command"], shell=True, capture_output=True,
                                    input=json.dumps({"hook_event_name": event, "session_id": "s"}),
                                    text=True, env=self.env, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

        self.assertEqual(run("UserPromptSubmit"), "")
        self.set_started(31 * 60)
        self.assertEqual(json.loads(run("PreToolUse"))["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_refuses_bad_settings_and_budgets_without_starting_claude(self):
        array = self.script.parent / "array.json"
        array.write_text('["private"]')
        for args in [
            ["--settings", '{"private": '],
            ["--settings", '{"env": "private"}'],
            ["--settings", '{"env": null, "x": "private"}'],
            ["--settings", '{"x": NaN, "y": "private"}'],
            ["--settings", str(array)],
            [f"--settings={array}"],
            ["--settings", str(self.script.parent / "private-missing.json")],
            ["--settings", T3_SETTINGS, "--settings", "private-missing.json"],
            ["--settings", '{"hooks": {"PreToolUse": "private"}}'],
        ]:
            with self.subTest(args=args):
                self.assert_refused(args)
        for env in [
            {"CLAUDE_REVIEW_MINUTES": "abc"}, {"CLAUDE_REVIEW_MINUTES": ""}, {"CLAUDE_REVIEW_MINUTES": "0"},
            {"CLAUDE_REVIEW_MINUTES": "-5"}, {"CLAUDE_REVIEW_MINUTES": "nan"}, {"CLAUDE_REVIEW_MINUTES": "inf"},
            {"CLAUDE_REVIEW_WARN_MINUTES": "0"},
            # The warning must come before the budget, and the defaults are 20 and 30.
            {"CLAUDE_REVIEW_WARN_MINUTES": "30"}, {"CLAUDE_REVIEW_MINUTES": "10"},
            {"CLAUDE_REVIEW_MINUTES": "5", "CLAUDE_REVIEW_WARN_MINUTES": "5"},
        ]:
            with self.subTest(env=env):
                self.assert_refused(["--settings", T3_SETTINGS], **env)

    def test_claude_receives_the_budget_values_and_the_callers_path(self):
        def budget(claude):
            return claude["env"]["CLAUDE_REVIEW_MINUTES"], claude["env"]["CLAUDE_REVIEW_WARN_MINUTES"]

        self.assertEqual(budget(self.launch(["--settings", T3_SETTINGS])[1]), ("30", "20"))
        _, claude = self.launch([], CLAUDE_REVIEW_MINUTES="0.5", CLAUDE_REVIEW_WARN_MINUTES="0.25")
        self.assertEqual(budget(claude), ("0.5", "0.25"))
        # uv puts the directory of its Python first on PATH. Claude must not see it.
        interpreter = os.path.dirname(sys.executable)
        _, claude = self.launch([], PATH=f"{interpreter}{os.pathsep}{self.bin}")
        self.assertEqual(claude["env"]["PATH"], str(self.bin))

    def test_version_and_help_run_claude_unchanged(self):
        for flag in ("--version", "-v", "--help", "-h"):
            with self.subTest(flag=flag):
                result, claude = self.launch([flag])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(claude["argv"], [flag])

    def test_reports_a_missing_claude(self):
        empty = self.script.parent / "empty"
        empty.mkdir()
        result, _ = self.launch(["--settings", T3_SETTINGS], PATH=str(empty))
        self.assertEqual((result.returncode, result.stderr),
                         (1, "claude-review: Could not start claude. Install Claude Code and put it on PATH.\n"))

    def state_file(self, session="s"):
        return self.tmp / "claude-review" / f"{session}.json"

    def set_started(self, seconds_ago, session="s"):
        """Move the turn start back in time and keep the recorded flags."""
        path = self.state_file(session)
        path.parent.mkdir(exist_ok=True)
        state = json.loads(path.read_text()) if path.exists() else {"warned": False, "denied": False}
        path.write_text(json.dumps({**state, "started": time.time() - seconds_ago}))

    def run_hook(self, payload, **env):
        result = subprocess.run([sys.executable, str(self.script), "hook"], input=payload, capture_output=True,
                                text=True, env={**self.env, **env}, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def hook(self, event, session="s", **env):
        """Send one event to the hook. Return the JSON it printed, or None."""
        result = self.run_hook(json.dumps({"hook_event_name": event, "session_id": session}), **env)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout) if result.stdout else None

    def test_warns_once_after_the_warning_time(self):
        self.assertIsNone(self.hook("PostToolUse"))
        self.assertAlmostEqual(json.loads(self.state_file().read_text())["started"], time.time(), delta=60)
        self.set_started(10 * 60)
        self.assertIsNone(self.hook("PostToolUse"))
        self.set_started(21 * 60)
        warning = self.hook("PostToolUse")["hookSpecificOutput"]
        self.assertEqual(warning["hookEventName"], "PostToolUse")
        self.assertRegex(warning["additionalContext"], r"21(\.\d+)? of 30 minutes")
        self.assertIsNone(self.hook("PostToolUse"))
        self.assertIsNone(self.hook("PreToolUse"))
        # The hooks read the same variables the launcher passes on.
        budget = {"CLAUDE_REVIEW_MINUTES": "0.5", "CLAUDE_REVIEW_WARN_MINUTES": "0.25"}
        self.set_started(10, "short")
        self.assertIsNone(self.hook("PostToolUse", "short", **budget))
        self.set_started(20, "short")
        warning = self.hook("PostToolUse", "short", **budget)["hookSpecificOutput"]
        self.assertIn("of 0.5 minutes", warning["additionalContext"])

    def test_after_the_budget_denies_each_call_and_stops_the_turn_from_the_second(self):
        self.set_started(25 * 60)
        self.assertIsNone(self.hook("PreToolUse"))
        self.set_started(31 * 60)
        self.assertIsNotNone(self.hook("PostToolUse"))
        denial = self.hook("PreToolUse")["hookSpecificOutput"]
        self.assertEqual((denial["hookEventName"], denial["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertIn("30 minutes", denial["permissionDecisionReason"])
        # The stop carries the refusal too, so the call that triggers it does not run.
        stopped = {**STOPPED, "hookSpecificOutput": denial}
        self.assertEqual(self.hook("PreToolUse"), stopped)
        self.assertEqual(self.hook("PreToolUse"), stopped)
        self.assertIsNone(self.hook("PreToolUse", "other"))
        # A new prompt starts a new turn with a fresh clock and both flags cleared.
        self.assertIsNone(self.hook("UserPromptSubmit"))
        self.assertIsNone(self.hook("PreToolUse"))
        self.assertIsNone(self.hook("PostToolUse"))
        self.set_started(31 * 60)
        self.assertIsNotNone(self.hook("PostToolUse"))
        self.assertEqual(self.hook("PreToolUse")["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_hook_failures_print_one_line_and_never_block(self):
        def event(**fields):
            return json.dumps({"hook_event_name": "PreToolUse", "session_id": "s", **fields})

        for payload in ["not json", "[]", event(hook_event_name="Stop"), event(session_id=""),
                        event(session_id="../escape"), event(session_id="a/b"), event(session_id="a b"),
                        event(session_id="séance"), event(session_id=None)]:
            with self.subTest(payload=payload):
                result = self.run_hook(payload)
                self.assertEqual(result.stdout, "")
                self.assertRegex(result.stderr, r"\Aclaude-review: [^\n]+\n\Z")
        self.assertFalse((self.tmp / "escape.json").exists())
        result = self.run_hook(event(), CLAUDE_REVIEW_MINUTES="abc")
        self.assertEqual((result.stdout, result.stderr.count("\n")), ("", 1))
        # A file where the state directory belongs makes the state unwritable.
        blocked = self.tmp / "blocked"
        blocked.mkdir()
        (blocked / "claude-review").write_text("")
        result = self.run_hook(event(), TMPDIR=str(blocked))
        self.assertEqual((result.stdout, result.stderr.count("\n")), ("", 1))


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/ramtoshiya-cc/hooks/context-budget.py"


def assistant(tokens, sidechain=False):
    usage = {"input_tokens": 1, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": tokens - 1, "output_tokens": 0}
    return {"type": "assistant", "isSidechain": sidechain, "message": {"usage": usage}}


class ContextBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.config = self.tmp / "config"
        self.project = self.tmp / "project"
        self.scratch = self.tmp / "scratch"
        for path in (self.config, self.project / ".claude", self.scratch):
            path.mkdir(parents=True)
        self.write_settings(self.config / "settings.json", {"autoCompactWindow": 100000})
        self.transcript = self.tmp / "session.jsonl"
        self.transcript.write_text("")
        self.env = {**os.environ, "CLAUDE_CONFIG_DIR": str(self.config),
                    "XDG_STATE_HOME": str(self.tmp / "state"), "CLAUDE_PROJECT_DIR": str(self.project)}
        self.env.pop("T3CODE_THREAD_ID", None)

    def write_settings(self, path, data):
        path.write_text(json.dumps(data))

    def append(self, *entries):
        with self.transcript.open("a") as stream:
            for entry in entries:
                stream.write(json.dumps(entry) + "\n")

    def run_hook(self, event="PostToolUse", env=None, **extra):
        payload = {"session_id": "s1", "transcript_path": str(self.transcript), "cwd": str(self.project),
                   "scratchpad_dir": str(self.scratch), "hook_event_name": event, **extra}
        result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload),
                                capture_output=True, text=True, env=env or self.env, check=True)
        if not result.stdout.strip():
            return None
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], event)
        return output["additionalContext"]

    def test_silent_below_threshold(self):
        self.append(assistant(74000))
        self.assertIsNone(self.run_hook())

    def test_warns_once_per_five_point_band(self):
        self.append(assistant(76000))
        text = self.run_hook()
        self.assertIn("about 76% of the 100,000-token", text)
        self.assertIn(f"Handoff note path: {self.scratch / 'handoff.md'}", text)
        self.assertIn("not run in T3 Code", text)
        self.append(assistant(79000))
        self.assertIsNone(self.run_hook(event="UserPromptSubmit"))
        self.append(assistant(81000))
        self.assertIn("about 81%", self.run_hook(event="UserPromptSubmit"))

    def test_compaction_resets_the_band(self):
        self.append(assistant(80000))
        self.assertIsNotNone(self.run_hook())
        self.append({"type": "system", "subtype": "compact_boundary"})
        self.assertIsNone(self.run_hook())
        self.append(assistant(30000), assistant(80000))
        self.assertIsNotNone(self.run_hook())

    def test_ignores_subagent_entries_and_subagent_hooks(self):
        self.append(assistant(50000), assistant(90000, sidechain=True))
        self.assertIsNone(self.run_hook())
        self.append(assistant(90000))
        self.assertIsNone(self.run_hook(agent_id="a1"))

    def test_names_the_t3_thread(self):
        self.append(assistant(76000))
        text = self.run_hook(env={**self.env, "T3CODE_THREAD_ID": "thread-9"})
        self.assertIn("T3 Code, thread id thread-9", text)

    def test_project_settings_override_user_settings(self):
        self.write_settings(self.project / ".claude/settings.json", {"autoCompactWindow": 200000})
        self.append(assistant(160000))
        self.assertIn("about 80% of the 200,000-token", self.run_hook())
        self.write_settings(self.project / ".claude/settings.local.json", {"autoCompactWindow": "auto"})
        self.append(assistant(190000))
        self.assertIsNone(self.run_hook())

    def test_silent_without_a_numeric_window(self):
        self.write_settings(self.config / "settings.json", {})
        self.append(assistant(99000))
        self.assertIsNone(self.run_hook())

    def test_finds_usage_before_a_long_tool_result(self):
        self.append(assistant(90000), {"type": "user", "content": "x" * (600 << 10)})
        self.assertIn("about 90%", self.run_hook())

    def test_session_start_after_compaction_points_to_the_note(self):
        self.assertIsNone(self.run_hook(event="SessionStart", source="compact"))
        (self.scratch / "handoff.md").write_text("next step")
        text = self.run_hook(event="SessionStart", source="compact")
        self.assertIn(str(self.scratch / "handoff.md"), text)
        self.assertIsNone(self.run_hook(event="SessionStart", source="resume"))

    def test_bad_input_prints_nothing(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], input="not json",
                                capture_output=True, text=True, env=self.env, check=True)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()

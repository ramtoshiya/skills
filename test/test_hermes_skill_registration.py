"""Hermes registration and advisory delivery at the native callback boundary."""

import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "setup/agents/hermes-skills.py"
SPEC = importlib.util.spec_from_file_location("hermes_skills", SOURCE)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class HermesSkillRegistrationTests(unittest.TestCase):
    def test_registers_external_skills_with_frontmatter_and_advisory_callbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "source/skills/writing/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\ndescription: Write clearly\n---\n")
            (root / "source/hooks").mkdir()
            (root / "source/hooks/hooks.json").write_text('{"hooks":{"PreToolUse":[]}}')
            (root / "source.json").write_text(json.dumps({
                "root": str(root / "source"), "skills": ["skills/writing"], "advisory_hooks": True,
            }))
            context = SimpleNamespace(register_skill=Mock(), register_hook=Mock())
            parser = SimpleNamespace(parse_frontmatter=lambda text: ({"description": "Write clearly"}, ""))
            with patch.object(adapter, "__file__", str(root / "__init__.py")), patch.dict("sys.modules", {"agent.skill_utils": parser}):
                adapter.register(context)
            context.register_skill.assert_called_once_with("writing", skill, "Write clearly", {"description": "Write clearly"})
            self.assertEqual({call.args[0] for call in context.register_hook.call_args_list}, {"pre_tool_call", "transform_tool_result"})

    def test_advisory_reaches_only_the_matching_tool_result_and_never_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hooks").mkdir()
            warning = {"hookSpecificOutput": {"additionalContext": "fixture advisory"}}
            command = "printf '%s' '" + json.dumps(warning) + "'"
            (root / "hooks/hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [{
                "matcher": "^Write$", "hooks": [{"type": "command", "command": command}],
            }]}}))
            context = SimpleNamespace(register_hook=Mock())
            adapter.advisory_hooks(context, {"root": str(root)})
            callbacks = {call.args[0]: call.args[1] for call in context.register_hook.call_args_list}
            before = callbacks["pre_tool_call"]
            after = callbacks["transform_tool_result"]
            args = {"path": str(root / "draft.md"), "content": "draft"}
            ids = {"session_id": "session", "tool_call_id": "write"}
            self.assertIsNone(before("write_file", args, **ids))
            self.assertIsNone(after("write_file", args, "other session", session_id="other", tool_call_id="write"))
            result = after("write_file", args, '{"success":true}', **ids)
            self.assertEqual(json.loads(result), {"success": True, "humanize_warning": "fixture advisory"})
            self.assertIsNone(after("write_file", args, "second delivery", **ids))
            self.assertIsNone(before("terminal", {"command": "git status"}, **ids))
            self.assertIsNone(after("terminal", {"command": "git status"}, "clean", **ids))
            with patch.object(adapter.subprocess, "run", side_effect=OSError("unavailable")):
                self.assertIsNone(before("write_file", args, **ids))
            self.assertIsNone(after("write_file", args, "tool completed", **ids))


if __name__ == "__main__":
    unittest.main()

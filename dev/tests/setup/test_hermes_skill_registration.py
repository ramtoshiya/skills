import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[3] / "setup/agents/hermes-skills.py"
SPEC = importlib.util.spec_from_file_location("hermes_skills", SOURCE)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def parse_frontmatter(text):
    header = text.split("---\n", 2)[1]
    return dict(line.split(": ", 1) for line in header.splitlines() if ": " in line), ""


class HermesSkillRegistrationTests(unittest.TestCase):
    def register_source(self, root, advisory_hooks):
        skill = root / "source/skills/writing/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\ndescription: Write clearly\n---\n")
        (root / "source/hooks").mkdir()
        (root / "source/hooks/hooks.json").write_text('{"hooks":{"PreToolUse":[]}}')
        (root / "source.json").write_text(json.dumps({
            "root": str(root / "source"), "skills": ["skills/writing"], "advisory_hooks": advisory_hooks,
        }))
        context = SimpleNamespace(register_skill=Mock(), register_hook=Mock())
        parser = SimpleNamespace(parse_frontmatter=parse_frontmatter)
        with patch.object(adapter, "__file__", str(root / "__init__.py")), patch.dict("sys.modules", {"agent.skill_utils": parser}):
            adapter.register(context)
        return context, skill

    def advisory_callbacks(self, root):
        (root / "hooks").mkdir()
        warning = {"hookSpecificOutput": {"additionalContext": "fixture advisory"}}
        command = "printf '%s' '" + json.dumps(warning) + "'"
        (root / "hooks/hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [{
            "matcher": "^Write$", "hooks": [{"type": "command", "command": command}],
        }]}}))
        context = SimpleNamespace(register_hook=Mock())
        adapter.advisory_hooks(context, {"root": str(root)})
        callbacks = {call.args[0]: call.args[1] for call in context.register_hook.call_args_list}

        def before(tool_name, args, **ids):
            return callbacks["pre_tool_call"](
                tool_name=tool_name, args=args, task_id="", turn_id="turn", api_request_id="",
                middleware_trace=[], **ids,
            )

        def after(tool_name, args, result, **ids):
            return callbacks["transform_tool_result"](
                tool_name=tool_name, args=args, result=result, task_id="", turn_id="turn", api_request_id="",
                duration_ms=12, status="ok", error_type=None, error_message=None, **ids,
            )

        return before, after

    def test_registers_external_skills_with_frontmatter_and_advisory_callbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            context, skill = self.register_source(Path(directory), True)
            context.register_skill.assert_called_once_with("writing", skill, "Write clearly", {"description": "Write clearly"})
            self.assertEqual({call.args[0] for call in context.register_hook.call_args_list}, {"pre_tool_call", "transform_tool_result"})

    def test_registers_no_callbacks_for_a_source_without_the_advisory_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            context, skill = self.register_source(Path(directory), False)
            context.register_skill.assert_called_once_with("writing", skill, "Write clearly", {"description": "Write clearly"})
            context.register_hook.assert_not_called()

    def test_advisory_reaches_only_the_matching_tool_result_and_never_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, after = self.advisory_callbacks(root)
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

    def test_advisory_is_appended_as_text_to_a_result_that_is_not_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, after = self.advisory_callbacks(root)
            args = {"path": str(root / "draft.md"), "content": "draft"}
            ids = {"session_id": "session", "tool_call_id": "write"}
            self.assertIsNone(before("write_file", args, **ids))
            self.assertEqual(after("write_file", args, "Wrote draft.md", **ids), "Wrote draft.md\n\nfixture advisory")


if __name__ == "__main__":
    unittest.main()

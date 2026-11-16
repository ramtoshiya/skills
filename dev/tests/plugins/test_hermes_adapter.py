import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[3] / "plugins/ramtoshiya/__init__.py"
SPEC = importlib.util.spec_from_file_location("hermes_adapter", SOURCE)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def parse_frontmatter(text):
    header = text.split("---\n", 2)[1]
    return dict(line.split(": ", 1) for line in header.splitlines() if ": " in line), ""


HERMES_MODULES = {"agent.skill_utils": SimpleNamespace(parse_frontmatter=parse_frontmatter)}


class HermesAdapterTests(unittest.TestCase):
    def register_with_home(self, home):
        context = SimpleNamespace(
            register_hook=Mock(), register_skill=Mock(), register_system_prompt_section=Mock(),
        )
        constants = SimpleNamespace(get_hermes_home=lambda: home)
        with patch.dict(sys.modules, {**HERMES_MODULES, "hermes_constants": constants}):
            adapter.register(context)
        return context

    def test_registers_every_shipped_skill_with_its_frontmatter_and_only_the_package_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.register_with_home(Path(directory))
            hooks = {call.args[0] for call in context.register_hook.call_args_list}
            self.assertEqual(hooks, {"pre_tool_call"})
            registered = {call.args[1] for call in context.register_skill.call_args_list}
            shipped = set((adapter.ROOT / "skills").glob("*/SKILL.md"))
            self.assertTrue(shipped)
            self.assertEqual(registered, shipped)
            for name, path, description, frontmatter in (call.args for call in context.register_skill.call_args_list):
                self.assertEqual(name, path.parent.name)
                self.assertEqual(frontmatter["name"], name)
                self.assertEqual(description, frontmatter["description"])
                self.assertTrue(description.strip())

    def test_machine_preferences_become_a_prompt_section_when_agents_md_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            preferences = "Prefer short answers.\n"
            (Path(directory) / "AGENTS.md").write_text(preferences)
            context = self.register_with_home(Path(directory))
            context.register_system_prompt_section.assert_called_once_with(
                "ramtoshiya.preferences", preferences, max_chars=4000,
            )

    def test_no_prompt_section_is_registered_without_agents_md(self):
        with tempfile.TemporaryDirectory() as directory:
            context = self.register_with_home(Path(directory))
            context.register_system_prompt_section.assert_not_called()

    def test_terminal_protocol_and_unrelated_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            args = {"command": "git status", "workdir": directory}
            self.assertIsNone(adapter.package_guard("terminal", args))
            args["command"] = "hf download publisher/model --revision " + "a" * 40
            self.assertIsNone(adapter.package_guard("terminal", args))
            args["command"] = "hf download publisher/model"
            result = adapter.package_guard("terminal", args)
            self.assertEqual(result["action"], "block")
            self.assertIn("40-character commit hash", result["message"])
            self.assertIsNone(adapter.package_guard("read_file", args))

    def test_guard_failure_blocks_the_command(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PATH": directory, "TERMINAL_CWD": directory}):
                result = adapter.package_guard("terminal", {"command": "git status"})
                self.assertEqual(result["action"], "block")
                self.assertIn("could not verify", result["message"])

    def test_guard_output_that_is_not_json_blocks_the_command(self):
        with tempfile.TemporaryDirectory() as directory:
            uv = Path(directory) / "uv"
            uv.write_text("#!/bin/sh\necho 'not json'\n")
            uv.chmod(0o755)
            with patch.dict(os.environ, {"PATH": directory, "TERMINAL_CWD": directory}):
                result = adapter.package_guard("terminal", {"command": "git status"})
                self.assertEqual(result["action"], "block")
                self.assertIn("could not verify", result["message"])


if __name__ == "__main__":
    unittest.main()

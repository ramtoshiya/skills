"""Hermes callback contracts, without requiring Hermes in the test environment."""

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


class HermesAdapterTests(unittest.TestCase):
    def test_registers_every_shipped_skill_and_only_the_package_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            context = SimpleNamespace(register_hook=Mock(), register_skill=Mock())
            constants = SimpleNamespace(get_hermes_home=lambda: Path(directory))
            with patch.dict(sys.modules, {"hermes_constants": constants}):
                adapter.register(context)
            hooks = {call.args[0] for call in context.register_hook.call_args_list}
            self.assertEqual(hooks, {"pre_tool_call"})
            registered = {call.args[1] for call in context.register_skill.call_args_list}
            shipped = set((adapter.ROOT / "skills").glob("*/SKILL.md"))
            self.assertTrue(shipped)
            self.assertEqual(registered, shipped)
            for call in context.register_skill.call_args_list:
                self.assertEqual(call.args[0], call.args[1].parent.name)
                self.assertTrue(call.args[2].strip())

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


if __name__ == "__main__":
    unittest.main()

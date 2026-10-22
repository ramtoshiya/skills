"""Hermes callback contracts, without requiring Hermes in the test environment."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "plugins/ramtoshiya/__init__.py"
SPEC = importlib.util.spec_from_file_location("hermes_adapter", SOURCE)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class HermesAdapterTests(unittest.TestCase):
    def test_terminal_protocol_and_unrelated_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            args = {"command": "git status", "workdir": directory}
            self.assertIsNone(adapter.package_guard("terminal", args))
            args["command"] = "pip --version"
            result = adapter.package_guard("terminal", args)
            self.assertEqual(result["action"], "block")
            self.assertIn("Bare Python/pip", result["message"])
            self.assertIsNone(adapter.package_guard("read_file", args))

    def test_guard_failures_block_commands_but_allow_finishing(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PATH": directory, "TERMINAL_CWD": directory}):
                result = adapter.package_guard("terminal", {"command": "git status"})
                self.assertEqual(result["action"], "block")
                self.assertIn("could not verify", result["message"])
                self.assertIsNone(adapter.git_hygiene())

    def test_dirty_stop_is_translated_and_retry_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", "-q", directory], check=True)
            Path(directory, "pending.txt").write_text("pending\n")
            with patch.dict(os.environ, {"TERMINAL_CWD": directory}):
                result = adapter.git_hygiene(attempt=0, session_id="first")
                self.assertEqual(result["decision"], "block")
                self.assertIn("pending.txt", result["reason"])
                self.assertIsNone(adapter.git_hygiene(attempt=1, session_id="first"))
                self.assertEqual(adapter.git_hygiene(attempt=0, session_id="next")["decision"], "block")


if __name__ == "__main__":
    unittest.main()

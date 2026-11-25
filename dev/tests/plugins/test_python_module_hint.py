import json
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[3] / "plugins/ramtoshiya/hooks/python-module-hint.py"


def run_hook(payload):
    result = subprocess.run([sys.executable, str(SCRIPT)], input=payload, text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout else None


def failed_import(module):
    return subprocess.run([sys.executable, "-I", "-c", f"import {module}"],
                          text=True, capture_output=True).stderr


class PythonModuleHintTests(unittest.TestCase):
    def test_missing_module_in_bash_output_points_at_uv(self):
        stderr = failed_import("ramtoshiya_missing_module")
        response = {"stdout": "", "stderr": stderr, "interrupted": False}
        output = run_hook(json.dumps({"tool_name": "Bash", "tool_response": response}))
        self.assertEqual(output["hookEventName"], "PostToolUse")
        context = output["additionalContext"]
        self.assertIn("`ramtoshiya_missing_module`", context)
        self.assertIn("uv run --with PACKAGE==VERSION python", context)

    def test_other_output_and_unreadable_input_add_nothing(self):
        for payload in (json.dumps({"tool_name": "Bash", "tool_response": {"stdout": "ok"}}),
                        json.dumps(["not", "an", "event"]), "not json"):
            with self.subTest(payload=payload):
                self.assertIsNone(run_hook(payload))


if __name__ == "__main__":
    unittest.main()

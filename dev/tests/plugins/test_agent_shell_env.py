import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[3] / "plugins/ramtoshiya-cc/hooks/agent-shell-env.py"


class AgentShellEnvTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.env_file = self.tmp / "sessionstart-hook-1.sh"

    def run_hook(self, env_file):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_ENV_FILE", "AGENTMEMORY_SDK_CHILD")}
        env["CLAUDE_ENV_FILE"] = str(env_file)
        payload = {"session_id": "s1", "hook_event_name": "SessionStart", "source": "startup"}
        return subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, check=True)

    def sourced(self, *names):
        env = {k: v for k, v in os.environ.items() if k not in names}
        script = f'. "{self.env_file}"; ' + "; ".join(f'printf "%s\\n" "${{{n}:-unset}}"' for n in names)
        result = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, env=env, check=True)
        return result.stdout.split()

    def test_bash_commands_inherit_the_flag_and_keep_other_exports(self):
        self.env_file.write_text("export OTHER_HOOK=kept")  # another hook's line, no trailing newline
        self.run_hook(self.env_file)
        # SessionStart fires again on resume, clear, and compact.
        self.run_hook(self.env_file)
        self.assertEqual(self.sourced("AGENTMEMORY_SDK_CHILD", "OTHER_HOOK"), ["1", "kept"])
        self.assertEqual(self.env_file.read_text().count("AGENTMEMORY_SDK_CHILD"), 1)

    def test_unwritable_env_file_does_not_fail_session_start(self):
        result = self.run_hook(self.tmp / "missing" / "sessionstart-hook-1.sh")
        self.assertEqual((result.stdout, result.stderr), ("", ""))


if __name__ == "__main__":
    unittest.main()

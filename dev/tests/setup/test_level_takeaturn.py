import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class TakeaturnStatusWithoutMiseTests(unittest.TestCase):
    def test_status_reports_an_installed_takeaturn_when_mise_is_not_on_path(self):
        pin = re.search(r'^COMMIT = "([0-9a-f]{40})"$', (ROOT / "setup/agents/takeaturn.py").read_text(), re.M)[1]
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve() / "home"
            binary = home / ".local/bin/takeaturn"
            binary.parent.mkdir(parents=True)
            version = json.dumps({"version": f"v0.0.0-20261121000000-{pin[:12]}"})
            binary.write_text(f"#!/bin/sh\necho '{version}'\n")
            binary.chmod(0o755)
            env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "XDG_STATE_HOME": str(Path(temporary) / "state")}
            result = subprocess.run([sys.executable, "-I", str(ROOT / "setup/agents/level.py"), "status", "--json"],
                                    env=env, capture_output=True, text=True)
        rows = {(row["host"], row["component"]): row for row in json.loads(result.stdout)}
        self.assertEqual(rows[("mise", "dotfiles")]["status"], "absent")
        self.assertEqual(rows[("takeaturn", "cli")]["status"], "ok", rows[("takeaturn", "cli")])


if __name__ == "__main__":
    unittest.main()

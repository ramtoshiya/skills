import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/ramtoshiya/hooks/git-hygiene-guard.py"
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class GitHygieneGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name).resolve() / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "tracked.txt").write_text("one\n")
        self.git("init", "-q")
        self.git("add", "tracked.txt")
        self.git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "init")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, env=GIT_ENV)

    def stop(self, payload):
        text = payload if isinstance(payload, str) else json.dumps({"hook_event_name": "Stop", **payload})
        result = subprocess.run([sys.executable, str(SCRIPT)], input=text, capture_output=True,
                                text=True, env=GIT_ENV, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_blocks_dirty_repository_from_a_subdirectory(self):
        (self.repo / "tracked.txt").write_text("two\n")
        (self.repo / "src/new.txt").write_text("new\n")
        output = self.stop({"cwd": str(self.repo / "src"), "stop_hook_active": False})
        self.assertEqual(output["decision"], "block")
        self.assertIn(f"{self.repo} has uncommitted changes", output["reason"])
        self.assertIn(" M tracked.txt", output["reason"])
        self.assertIn("?? src/", output["reason"])
        self.assertIn("Commit completed work locally by default", output["reason"])

    def test_allows_clean_repository(self):
        self.assertIsNone(self.stop({"cwd": str(self.repo), "stop_hook_active": False}))

    def test_allows_the_retry_after_a_block(self):
        (self.repo / "tracked.txt").write_text("two\n")
        self.assertIsNone(self.stop({"cwd": str(self.repo), "stop_hook_active": True}))

    def test_allows_stop_when_it_cannot_check(self):
        outside = self.repo.parent / "outside"
        outside.mkdir()
        for payload in [
            {"cwd": str(outside), "stop_hook_active": False},
            {"cwd": str(self.repo / "missing"), "stop_hook_active": False},
            {"stop_hook_active": False},
            "not JSON",
        ]:
            with self.subTest(payload=payload):
                self.assertIsNone(self.stop(payload))


if __name__ == "__main__":
    unittest.main()

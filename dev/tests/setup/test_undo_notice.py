import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOK = Path(__file__).resolve().parents[3] / "setup/git/undo-notice.py"
NOW = 1_800_000_000


class UndoNoticeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
                            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
        self.git("init", "-q")

    def git(self, *args, time=NOW):
        environment = {**self.environment, "GIT_AUTHOR_DATE": f"@{time} +0000", "GIT_COMMITTER_DATE": f"@{time} +0000"}
        subprocess.run(["git", *args], cwd=self.repo, env=environment, check=True, capture_output=True)

    def commit(self, text, message, time):
        (self.repo / "budget.ts").write_text(text)
        self.git("add", ".", time=time)
        self.git("commit", "-qm", message, time=time)

    def notice(self):
        result = subprocess.run([sys.executable, str(HOOK)], cwd=self.repo, env=self.environment,
                                capture_output=True, text=True, check=True)
        return result.stderr

    def history(self, gap):
        sized = "const budget = sized(load);\nconst limit = budget * 2;\nexport { limit };\n"
        fixed = "const budget = 120_000;\nconst limit = 300_000;\nexport { limit };\n"
        self.commit(fixed, "Use a fixed hang guard", NOW - 10 * 3600)
        self.commit(sized, "Size test budgets from load", NOW - gap)
        self.commit(fixed, "Restore the fixed hang guard", NOW)

    def test_names_an_earlier_session_commit_that_the_new_commit_switches_back(self):
        self.history(gap=3 * 3600)
        notice = self.notice()
        self.assertIn("undo-notice", notice)
        self.assertIn("Size test budgets from load", notice)
        self.assertIn("budget.ts", notice)
        self.assertNotIn("Use a fixed hang guard", notice)

    def test_stays_quiet_when_the_switched_back_commit_is_recent(self):
        self.history(gap=30 * 60)
        self.assertEqual(self.notice(), "")

    def test_stays_quiet_for_an_ordinary_edit(self):
        self.commit("const budget = 1;\nconst limit = 2;\n", "Add limits", NOW - 5 * 3600)
        self.commit("const budget = 1;\nconst limit = 3;\nconst floor = 4;\n", "Raise the limit", NOW)
        self.assertEqual(self.notice(), "")


if __name__ == "__main__":
    unittest.main()

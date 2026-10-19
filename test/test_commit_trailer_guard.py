import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/ramtoshiya-cc/hooks/commit-trailer-guard.py"
spec = importlib.util.spec_from_file_location("commit_trailer_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


class CommitTrailerGuardTests(unittest.TestCase):
    def check(self, command, cwd=None):
        return guard.reason(command, cwd)

    def test_blocks_attribution_in_commit_and_pr_text(self):
        for command in [
            # A commit message passed through a heredoc, as Claude Code writes it.
            f"git add -A && git commit -q -F - <<'EOF'\nRemove a component\n\nWhy it went.\n\n{TRAILER}\nEOF",
            f'git commit -m "Fix a bug" -m "{TRAILER}"',
            f"git -C repo commit --amend -m 'Subject\n\n{TRAILER}'",
            f"git -c user.name=x commit -m 'Subject\n\n{TRAILER}'",
            f"git merge --no-ff topic -m 'Merge topic\n\n{TRAILER}'",
            f"git tag -a v1 -m 'Release\n\n{TRAILER}'",
            f"gs commit create -m 'Subject\n\n{TRAILER}'",
            f"gs cc -m 'Subject\n\n{TRAILER}'",
            "gh pr create --title T --body 'Summary\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)'",
            "gh pr edit 3 --body \"$(cat <<'EOF'\nSummary\n\nhttps://claude.ai/code/session_abc\nEOF\n)\"",
            "cd repo && git commit -m 'x\n\nco-authored-by: Codex <noreply@openai.com>'",
        ]:
            with self.subTest(command=command):
                self.assertIsNotNone(self.check(command))

    def test_reads_message_and_body_files(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "msg.txt").write_text(f"Subject\n\n{TRAILER}\n")
            Path(directory, "clean.txt").write_text("Subject\n\nBody.\n")
            self.assertIsNotNone(self.check("git commit -F msg.txt", directory))
            self.assertIsNotNone(self.check("git commit --file=msg.txt", directory))
            self.assertIsNotNone(self.check("gh pr create --title T --body-file msg.txt", directory))
            self.assertIsNone(self.check("git commit -F clean.txt", directory))
            self.assertIsNone(self.check("git commit -F missing.txt", directory))

    def test_allows_clean_commits_and_reading_history(self):
        for command in [
            "git add -A && git commit -q -F - <<'EOF'\nRemove a component\n\nWhy it went.\nEOF",
            "git commit -m 'Co-authored-by: Ada Lovelace <ada@example.com>'",
            f"git log --all --grep='{TRAILER}'",
            f"git log --format=%B -1 | grep -c '{TRAILER}'",
            f"rg -n '{TRAILER}' .",
            "gh pr view 3 --json body",
            f"echo '{TRAILER}' > notes.txt",
        ]:
            with self.subTest(command=command):
                self.assertIsNone(self.check(command))

    def run_hook(self, payload):
        return subprocess.run([sys.executable, str(SCRIPT)], input=payload,
                              capture_output=True, text=True, check=True).stdout

    def test_hook_protocol(self):
        denied = json.loads(self.run_hook(json.dumps({
            "tool_name": "Bash", "cwd": "/tmp",
            "tool_input": {"command": f"git commit -m 'x\n\n{TRAILER}'"}})))
        output = denied["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("Co-Authored-By", output["permissionDecisionReason"])
        monitor = self.run_hook(json.dumps({
            "tool_name": "Monitor", "tool_input": {"command": f"git commit -m 'x\n\n{TRAILER}'"}}))
        self.assertIn("deny", monitor)
        for payload in [
            json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m 'Clean'"}}),
            json.dumps({"tool_name": "Write", "tool_input": {"content": TRAILER}}),
            "not json",
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.run_hook(payload), "")


if __name__ == "__main__":
    unittest.main()

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "plugins/ramtoshiya/skills/owner-decisions/scripts/decisions.py"


def run(root, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root, capture_output=True, text=True)


class OwnerDecisionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.assertEqual(run(self.root, "init").returncode, 0)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def rules(self):
        result = run(self.root, "check")
        return result.returncode, sorted({line.split()[1] for line in result.stdout.splitlines() if not line.startswith(" ")})

    def test_init_in_an_empty_repository_passes_and_keeps_existing_files(self):
        self.assertEqual(self.rules(), (0, []))
        self.write(".claude/rules/process.md", "# Mine\n")
        run(self.root, "init")
        self.assertEqual((self.root / ".claude/rules/process.md").read_text(), "# Mine\n")
        self.assertEqual((self.root / "AGENTS.md").read_text().count("## Owner decisions"), 1)

    def test_a_cited_decision_passes_and_an_uncited_one_fails(self):
        self.write("docs/decisions/2026-01-02-use-tabs.md", "# Use tabs\n")
        self.assertEqual(self.rules(), (1, ["decisions/uncited"]))
        self.write(".claude/rules/style.md", "- Indent with tabs. [Use tabs](../../docs/decisions/2026-01-02-use-tabs.md)\n")
        self.assertEqual(self.rules(), (0, []))

    def test_a_numbered_record_fails_its_name(self):
        self.write("docs/decisions/0007-use-tabs.md", "# Use tabs\n")
        self.assertEqual(self.rules(), (1, ["decisions/name"]))

    def test_a_link_to_a_missing_record_fails_anywhere(self):
        self.write("docs/notes.md", "See [gone](decisions/2026-01-02-gone.md).\n")
        self.assertEqual(self.rules(), (1, ["decisions/reference"]))

    def test_citing_a_superseded_record_fails_and_the_old_record_needs_no_citation(self):
        self.write("docs/decisions/2026-01-02-use-tabs.md", "# Use tabs\n")
        self.write("docs/decisions/2026-02-03-use-spaces.md", "# Use spaces\n\nSupersedes: [Use tabs](2026-01-02-use-tabs.md)\n")
        self.write(".claude/rules/style.md", "- Indent with spaces. [Use spaces](../../docs/decisions/2026-02-03-use-spaces.md)\n")
        self.assertEqual(self.rules(), (0, []))
        self.write(".claude/rules/old.md", "- [Use tabs](../../docs/decisions/2026-01-02-use-tabs.md)\n")
        self.assertEqual(self.rules(), (1, ["decisions/superseded-citation"]))

    def test_a_record_past_its_deadline_needs_no_citation_and_list_marks_it(self):
        self.write("docs/decisions/2020-01-02-today-only.md", "# Today only\n\nUntil: 2020-01-03 05:00 KST\n")
        self.write("docs/decisions/2020-01-02-until-later.md", "# Until later\n\nUntil: 2999-01-01 00:00 +00:00\n")
        self.assertEqual(self.rules(), (1, ["decisions/uncited"]))
        listed = run(self.root, "list", "--all").stdout
        self.assertIn("Today only  (inactive)", listed)
        self.assertNotIn("Until later  (inactive)", listed)


if __name__ == "__main__":
    unittest.main()

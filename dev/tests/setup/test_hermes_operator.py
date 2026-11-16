import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "setup/hermes/plugins/skill-drafts/__init__.py"
SETUP = ROOT / "setup/hermes/operator_profile.py"
# Stands in for the bb CLI: lists one project and records the draft it was asked to create.
FAKE_BB = f"""#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
if args[:2] == ["projects", "list"]:
    print(json.dumps([{{"id": "proj_skills", "sources": [{{"path": os.environ["REPO"]}}]}}]))
elif args[:2] == ["draft", "create"]:
    if os.environ.get("FAIL"):
        sys.exit("HTTP 500: server down")
    with open(os.environ["CAPTURE"], "w") as file:
        json.dump(args, file)
    print(json.dumps({{"threadId": "thr_new", "held": True}}))
"""


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def option(args, name):
    return args[args.index(name) + 1]


class SkillDraftsHookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.repo = root / "skills"
        installed = root / "profile/skills/unslop"
        installed.mkdir(parents=True)
        self.skill_md = installed / "SKILL.md"
        self.skill_md.write_text("# Unslop\n\nCut filler.\n")
        sources = root / "sources.json"
        sources.write_text(json.dumps({
            "profile": "operator", "modePath": "/pstack/mode.md", "defaultRepo": str(self.repo),
            "skillsRepo": str(self.repo), "sourceCheckouts": [str(self.repo)], "provider": "claude-code",
            "skills": {"unslop": {"repo": str(self.repo), "path": "skills/unslop", "installed": str(installed)}},
        }))
        bb = root / "bb"
        bb.write_text(FAKE_BB)
        bb.chmod(0o755)
        self.capture = root / "capture.json"
        self.hook = load("skill_drafts_under_test", PLUGIN)
        self.enterContext(mock.patch.object(self.hook, "SOURCES", sources))
        self.enterContext(mock.patch.dict(os.environ, {
            "BB_CLI": str(bb), "REPO": str(self.repo), "CAPTURE": str(self.capture)}))

    def call(self, args):
        return self.hook.on_pre_tool_call(tool_name="skill_manage", args=args, session_id="sess_1")

    def test_other_tools_pass_through(self):
        self.assertIsNone(self.hook.on_pre_tool_call(tool_name="terminal", args={"command": "ls"}))

    def test_skill_write_becomes_draft_and_is_blocked(self):
        result = self.call({"operations": [{"action": "patch", "name": "unslop",
                                            "old_string": "Cut filler.", "new_string": "Cut all filler."}]})

        self.assertEqual(result["action"], "block")
        self.assertIn("@thread:thr_new", result["message"])
        args = json.loads(self.capture.read_text())
        self.assertEqual(option(args, "--project"), "proj_skills")
        self.assertEqual(option(args, "--new-environment"), "worktree")
        brief = option(args, "--prompt")
        self.assertTrue(brief.startswith("Read /pstack/mode.md and follow it"))
        self.assertIn("-Cut filler.\n+Cut all filler.", brief)
        self.assertIn("Sending this draft is the user's approval", brief)
        self.assertIn("--session-id sess_1", brief)
        self.assertEqual(self.skill_md.read_text(), "# Unslop\n\nCut filler.\n")

    def test_new_skill_goes_to_default_repo(self):
        self.call({"action": "create", "name": "fresh", "content": "---\nname: fresh\n---\n"})

        brief = option(json.loads(self.capture.read_text()), "--prompt")
        self.assertIn(f"a new skill. Place it in `{self.repo}`", brief)
        self.assertIn("+name: fresh", brief)

    def test_bb_failure_still_blocks(self):
        with mock.patch.dict(os.environ, {"FAIL": "1"}):
            result = self.call({"action": "delete", "name": "unslop"})

        self.assertEqual(result["action"], "block")
        self.assertIn("server down", result["message"])
        self.assertFalse(self.capture.exists())


class SoulBlockTests(unittest.TestCase):
    def setUp(self):
        self.setup = load("operator_profile_under_test", SETUP)

    def test_block_is_appended_once_and_replaced_on_update(self):
        first = self.setup.with_soul_block("Default soul.", "Old lines.")
        second = self.setup.with_soul_block(first + "User text.\n", "New lines.")

        self.assertEqual(second.count(self.setup.SOUL_BEGIN), 1)
        self.assertIn("New lines.", second)
        self.assertNotIn("Old lines.", second)
        self.assertTrue(second.startswith("Default soul.\n\n"))
        self.assertIn("User text.", second)


if __name__ == "__main__":
    unittest.main()

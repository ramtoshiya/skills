import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "setup/hermes/plugins/skill-drafts/__init__.py"
SETUP = ROOT / "setup/hermes/operator_profile.py"
THREAD_ENV = ROOT / "setup/hermes/plugins/bb-thread-env/__init__.py"
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


class BbThreadEnvTests(unittest.TestCase):
    """The resolver Hermes calls when a session's command is spawned."""

    def setUp(self):
        self.plugin = load("bb_thread_env_under_test", THREAD_ENV)
        bridge = {"name": "bb-bridge", "command": "node", "args": [], "env": [
            {"name": "BB_ACP_DYNAMIC_TOOL_HOST", "value": "127.0.0.1"},
            {"name": "BB_ACP_DYNAMIC_TOOL_PORT", "value": "5555"},
            {"name": "BB_ACP_DYNAMIC_TOOL_TOKEN", "value": "secret-token"},
            {"name": "BB_ACP_DYNAMIC_TOOL_THREAD_ID", "value": "thr_a"},
        ]}
        sessions = {"sess_a": [{"name": "github", "env": []}, bridge], "sess_plain": []}
        self.enterContext(mock.patch.object(
            self.plugin, "session_thread_id",
            lambda sid: self.plugin.bridge_thread_id(sessions[sid]) if sid in sessions else None))

    def test_bridge_session_gets_its_thread_and_nothing_else(self):
        env = self.plugin.resolve("sess_a")

        self.assertEqual(env, {"BB_THREAD_ID": "thr_a", "BB_PROJECT_ID": None,
                               "BB_ENVIRONMENT_ID": None, "BB_THREAD_STORAGE": None})
        self.assertNotIn("secret-token", json.dumps(env))

    def test_session_without_bridge_unsets_thread_identity(self):
        for sid in ("sess_plain", "sess_unknown"):
            self.assertEqual(set(self.plugin.resolve(sid).values()), {None})


# Stands in for the hermes CLI. A home's settings live in fake-config.json beside its skills/.
# `skills opt-out --remove` deletes the skills its .bundled_manifest lists, like Hermes does.
FAKE_HERMES = f"""#!{sys.executable}
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ["HOME"]) / ".hermes"
with open(Path(os.environ["HOME"]) / "hermes-calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
def home(name):
    return root if name == "default" else root / "profiles" / name
def config(name):
    path = home(name) / "fake-config.json"
    return path, json.loads(path.read_text()) if path.exists() else {{}}
if args[0] == "profile":
    if args[1] == "show" and not home(args[2]).is_dir():
        sys.exit(1)
    if args[1] == "create":
        (home(args[2]) / "skills").mkdir(parents=True)
    if args[1] == "use":
        (root / "active_profile").write_text(args[2])
    sys.exit(0)
assert args[0] == "-p", args
name, command = args[1], args[2:]
path, values = config(name)
if command[:2] == ["config", "get"]:
    print(json.dumps(values.get(command[2], [])))
elif command[:2] == ["config", "set"]:
    try:
        values[command[2]] = json.loads(command[3])
    except ValueError:
        values[command[2]] = command[3]
elif command[:2] == ["plugins", "enable"]:
    values.setdefault("plugins.enabled", []).append(command[2])
elif command[:2] == ["skills", "opt-out"] and "--remove" in command:
    skills = home(name) / "skills"
    manifest = skills / ".bundled_manifest"
    bundled = {{line.split(":")[0] for line in manifest.read_text().split()}} if manifest.exists() else set()
    for skill_md in list(skills.rglob("SKILL.md")):
        if skill_md.parent.name in bundled:
            shutil.rmtree(skill_md.parent)
    (home(name) / ".no-bundled-skills").touch()
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(values))
"""
SUPPORT_DIRS = {"references", "scripts", "templates", "assets"}
PSTACK_ALLOWED = ["in-your-own-words", "why", "how", "interrogate", "statechart", "technical-writing", "unslop"]
CC_DESCRIPTION = "Skills that only work in Claude Code."


def git(*args, cwd):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                           cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def write_tree(root, files):
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)


def commit_repo(root, files):
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        git("init", "-q", cwd=root)
    write_tree(root, files)
    git("add", "-A", cwd=root)
    git("commit", "-q", "-m", "fixture", cwd=root)
    return git("rev-parse", "HEAD", cwd=root)


def skill(name):
    return {f"{name}/SKILL.md": f"---\nname: {name}\ndescription: {name} skill\n---\n\n# {name}\n"}


def under(prefix, files):
    return {f"{prefix}/{name}": text for name, text in files.items()}


def skill_dirs(home):
    """Skill name -> directories, from the roots a profile reads and that bb's Hermes catalog reads:
    the home's skills/ and its skills.external_dirs."""
    config = home / "fake-config.json"
    external = json.loads(config.read_text()).get("skills.external_dirs", []) if config.exists() else []
    found = {}
    for root in [home / "skills", *map(Path, external)]:
        for skill_md in root.rglob("SKILL.md"):
            if SUPPORT_DIRS.isdisjoint(skill_md.relative_to(root).parts[:-1]):
                found.setdefault(skill_md.parent.name, []).append(skill_md.parent)
    return found


class OperatorProfileSetupTests(unittest.TestCase):
    """Runs the real setup script from a fixture checkout against a fake hermes."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name).resolve()
        self.home = self.tmp / "home"
        self.state = self.tmp / "state"
        self.repo = self.tmp / "skills"
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "hermes").write_text(FAKE_HERMES)
        (bin_dir / "hermes").chmod(0o755)
        self.env = {"HOME": str(self.home), "XDG_STATE_HOME": str(self.state),
                    "PATH": os.pathsep.join([str(bin_dir), str(Path(shutil.which("git")).parent), "/usr/bin", "/bin"])}

        self.pstack = self.tmp / "pstack"
        commit_repo(self.pstack, {"plugins/pstack-mode/mode.md": "# Mode\n", **under(
            "plugins/pstack-mode/skills", {k: v for s in [*PSTACK_ALLOWED, "tdd"] for k, v in skill(s).items()})})
        grill_sha = self.pinned("fork/grill-skills", {**under("skills/productivity", {
            **skill("grilling"), **skill("caveman"), "grilling/references/rounds.md": "Rounds.\n"})})
        korean_sha = self.pinned("fork/korean", under("plugins/korean-pack", {
            "plugin.yaml": "name: korean-pack\ndescription: Korean editing\n",
            "__init__.py": "def register(ctx):\n    pass\n",
            ".claude-plugin/plugin.json": "{}\n",
            "scripts/check.py": "print('ok')\n",
            **under("skills", skill("korean")),
            **under("hermes/skills", skill("korean")),
        }))
        self.marketplace = {"name": "fixture", "plugins": [
            {"name": "ramtoshiya", "description": "Personal skills.", "source": "./plugins/ramtoshiya"},
            {"name": "ramtoshiya-cc", "description": CC_DESCRIPTION, "source": "./plugins/ramtoshiya-cc"},
            {"name": "grill-pack", "description": "Grilling interviews.", "skills": ["./grilling"],
             "source": {"source": "git-subdir", "url": "fork/grill-skills", "path": "skills/productivity", "sha": grill_sha}},
            {"name": "korean-pack", "description": "Korean editing.",
             "source": {"source": "git-subdir", "url": "fork/korean", "path": "plugins/korean-pack", "sha": korean_sha}},
            {"name": "pstack-mode", "description": "Pstack workflows.",
             "source": {"source": "git-subdir", "url": "fork/pstack", "path": "plugins/pstack-mode", "sha": "f" * 40}},
        ]}
        setup_files = {str(p.relative_to(ROOT)): p.read_text() for p in (ROOT / "setup").rglob("*")
                       if p.is_file() and p.parts[len(ROOT.parts) + 1] in {"hermes", "agents"}
                       and "__pycache__" not in p.parts and p.suffix in {".py", ".md", ".json", ".yaml"}}
        commit_repo(self.repo, {
            **setup_files,
            ".claude-plugin/marketplace.json": json.dumps(self.marketplace),
            **under("plugins/ramtoshiya/skills", skill("read-x")),
            **under("plugins/ramtoshiya-cc/skills", {**skill("self-compact"), "self-compact/scripts/compact.mjs": "//\n"}),
        })
        self.operator = self.home / ".hermes/profiles/operator"
        self.default = self.home / ".hermes"
        bundled = {**skill("arxiv"), **skill("apple-notes"), ".bundled_manifest": "arxiv:1\napple-notes:2\n"}
        write_tree(self.default / "skills", bundled)

    def pinned(self, repo, files):
        """A third-party source fetched by agents:sync at its approved commit."""
        upstream = self.tmp / "upstream" / repo
        sha = commit_repo(upstream, files)
        target = self.state / "ramtoshiya-agents/sources" / repo / sha
        target.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "-q", str(upstream), str(target), cwd=self.tmp)
        return sha

    def setup_profile(self):
        result = subprocess.run([sys.executable, str(self.repo / "setup/hermes/operator_profile.py"),
                                 "--pstack", str(self.pstack)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def expected(self):
        return {"read-x", "self-compact", "grilling", "operator-handoff", *PSTACK_ALLOWED}

    def test_operator_knows_every_repository_skill_without_bundled_ones(self):
        write_tree(self.operator / "skills", {**skill("apple-notes"), ".bundled_manifest": "apple-notes:2\n",
                                              **skill("my-hub-skill")})

        self.setup_profile()

        skills = skill_dirs(self.operator)
        self.assertEqual(set(skills), self.expected() | {"my-hub-skill"})
        self.assertTrue((skills["self-compact"][0] / "scripts/compact.mjs").is_file())
        self.assertTrue((skills["grilling"][0] / "references/rounds.md").is_file())
        config = json.loads((self.operator / "fake-config.json").read_text())
        self.assertIn("korean-pack", config["plugins.enabled"])
        package = self.operator / "plugins/korean-pack"
        self.assertTrue((package / "hermes/skills/korean/SKILL.md").is_file())
        self.assertTrue((package / "scripts/check.py").is_file())
        self.assertEqual(config["skills.auto_load"], ["operator-handoff"])
        self.assertEqual(config["agent.disabled_toolsets"], ["file", "code_execution"])
        self.assertFalse(config["memory.write_approval"])
        handoff = (skills["operator-handoff"][0] / "SKILL.md").read_text()
        self.assertIn(CC_DESCRIPTION, handoff)
        self.assertIn("`self-compact`", handoff)

    def test_bb_catalog_lists_the_operator_skills(self):
        """bb reads the default home's skills/ and its skills.external_dirs, not the sticky profile."""
        self.setup_profile()

        self.assertEqual((self.default / "active_profile").read_text(), "operator")
        self.assertEqual(set(skill_dirs(self.default)), set(skill_dirs(self.operator)))
        self.assertEqual(set(skill_dirs(self.default)), self.expected())

    def test_rerun_converges_on_the_marketplace_selection(self):
        old_copy = self.operator / "skills/unslop"
        write_tree(old_copy, {"SKILL.md": "---\nname: unslop\n---\nOld.\n"})
        write_tree(self.operator / "plugins/skill-drafts", {"sources.json": json.dumps(
            {"skills": {"unslop": {"repo": str(self.pstack), "path": "x", "installed": str(old_copy)}}})})
        self.operator.joinpath("skills").mkdir(exist_ok=True)
        self.setup_profile()
        self.setup_profile()

        for home in (self.operator, self.default):
            skills = skill_dirs(home)
            self.assertEqual(set(skills), self.expected())
            self.assertEqual([name for name, dirs in skills.items() if len(dirs) > 1], [])

        self.marketplace["plugins"] = [p for p in self.marketplace["plugins"] if p["name"] != "grill-pack"]
        commit_repo(self.repo, {".claude-plugin/marketplace.json": json.dumps(self.marketplace)})
        self.setup_profile()

        self.assertEqual(set(skill_dirs(self.operator)), self.expected() - {"grilling"})
        self.assertEqual(set(skill_dirs(self.default)), self.expected() - {"grilling"})

    def test_skill_change_draft_names_the_owning_source(self):
        self.setup_profile()
        sources = self.operator / "plugins/skill-drafts/sources.json"
        bb = self.tmp / "bin/bb"
        bb.write_text(FAKE_BB)
        bb.chmod(0o755)
        capture = self.tmp / "capture.json"
        hook = load("skill_drafts_installed", self.operator / "plugins/skill-drafts/__init__.py")
        self.enterContext(mock.patch.object(hook, "SOURCES", sources))
        self.enterContext(mock.patch.dict(os.environ, {
            "BB_CLI": str(bb), "REPO": str(self.repo), "CAPTURE": str(capture)}))
        grill_sha = self.marketplace["plugins"][2]["source"]["sha"]

        hook.on_pre_tool_call(tool_name="skill_manage", session_id="sess_1", args={
            "action": "patch", "name": "grilling", "old_string": "# grilling", "new_string": "# Grilling"})

        args = json.loads(capture.read_text())
        self.assertEqual(option(args, "--project"), "proj_skills")
        brief = option(args, "--prompt")
        self.assertIn("`skills/productivity/grilling` in https://github.com/fork/grill-skills", brief)
        self.assertIn(grill_sha, brief)
        self.assertIn("-# grilling\n+# Grilling", brief)

        hook.on_pre_tool_call(tool_name="skill_manage", session_id="sess_1", args={
            "action": "patch", "name": "read-x", "old_string": "# read-x", "new_string": "# Read X"})

        brief = option(json.loads(capture.read_text()), "--prompt")
        self.assertIn(f"`plugins/ramtoshiya/skills/read-x` in `{self.repo.resolve()}`", brief)


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

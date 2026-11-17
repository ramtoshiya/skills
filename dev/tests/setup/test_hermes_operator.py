import hashlib
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
# Stands in for the bb CLI: lists one project, records the draft it was asked to create, and
# keeps the provider-acp plugin settings in $HOME/bb-provider-acp.json. Like the real CLI with
# the tracker plugin installed, the plural `projects` group has no `list`, and any command the
# fake does not know fails.
FAKE_BB = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[:3] == ["plugin", "config", "provider-acp"]:
    store = Path(os.environ["HOME"]) / "bb-provider-acp.json"
    values = json.loads(store.read_text()) if store.exists() else {{"customAgents": ""}}
    if args[3:4] == ["set"]:
        values[args[4]] = args[5]
        store.write_text(json.dumps(values))
    else:
        print(json.dumps({{"ok": True, "values": values}}))
elif args[:2] == ["project", "list"]:
    print(json.dumps([{{"id": "proj_skills", "sources": [{{"path": os.environ["REPO"]}}]}}]))
elif args[:2] == ["draft", "create"]:
    if os.environ.get("FAIL"):
        sys.exit("HTTP 500: server down")
    with open(os.environ["CAPTURE"], "w") as file:
        json.dump(args, file)
    print(json.dumps({{"threadId": "thr_new", "held": True}}))
else:
    print(json.dumps({{"ok": False, "error": {{"code": "unknown_command", "message": "unknown command"}}}}))
    sys.exit(1)
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
# Bundled skills come from $FAKE_BUNDLED. `sync` follows tools/skills_sync.sync_skills, which
# profile creation, `skills reset`, chat and gateway startup, and `hermes update` all run.
FAKE_HERMES = """#!PYTHON
import hashlib, json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ["HOME"]) / ".hermes"
bundled_root = Path(os.environ["FAKE_BUNDLED"])
ESSENTIAL = {"hermes-agent"}
with open(Path(os.environ["HOME"]) / "hermes-calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
def home(name):
    return root if name == "default" else root / "profiles" / name
def digest(directory):
    return hashlib.sha256((directory / "SKILL.md").read_bytes()).hexdigest()[:8]
def bundled():
    return {md.parent.name: md.parent for md in bundled_root.rglob("SKILL.md")}
def dest(h, name):
    return h / "skills" / bundled()[name].relative_to(bundled_root)
def manifest(h):
    path = h / "skills/.bundled_manifest"
    return dict(line.split(":", 1) for line in path.read_text().split()) if path.exists() else {}
def save(h, entries):
    (h / "skills/.bundled_manifest").write_text("".join(f"{k}:{v}\\n" for k, v in entries.items()))
def sync(h):
    # Opted-out homes get only essential skills. A tracked skill missing on disk was deleted by the user.
    entries = manifest(h)
    for name, source in bundled().items():
        if (h / ".no-bundled-skills").exists() and name not in ESSENTIAL:
            continue
        target = dest(h, name)
        if name not in entries:
            if not target.exists():
                shutil.copytree(source, target)
            if digest(target) == digest(source):
                entries[name] = digest(source)
    save(h, entries)
def reload_gateway(h):
    # A gateway serving h, marked by gateway-running, re-imports the enabled plugins' code from disk.
    marker = h / "gateway-running"
    if not marker.exists():
        return None
    if marker.read_text() == "refuse":
        return {"reloaded": False, "error": "reload refused"}
    enabled = json.loads((h / "fake-config.json").read_text()).get("plugins.enabled", [])
    loaded = {p: hashlib.sha256((h / "plugins" / p / "__init__.py").read_bytes()).hexdigest() for p in enabled}
    (h / "gateway-plugins.json").write_text(json.dumps(loaded))
    return {"reloaded": True, "plugins": sorted(loaded)}
def run_plugin_command(h, command):
    # Hermes attaches the CLI commands that enabled plugins register, then calls the handler.
    import argparse, importlib.util, types
    activation = types.ModuleType("hermes_cli.plugins_activation")
    activation.reload_running_gateway = lambda: reload_gateway(h)
    sys.modules["hermes_cli"] = types.ModuleType("hermes_cli")
    sys.modules["hermes_cli.plugins_activation"] = activation
    commands = {}
    class Context:
        def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
            commands[name] = (setup_fn, handler_fn)
        def __getattr__(self, name):
            return lambda *a, **k: None
    for plugin in json.loads((h / "fake-config.json").read_text()).get("plugins.enabled", []):
        spec = importlib.util.spec_from_file_location(f"plugin_{plugin}".replace("-", "_"), h / "plugins" / plugin / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.register(Context())
    if command[0] not in commands:
        sys.exit(f"hermes: '{command[0]}' is not a `hermes` command.")
    parser = argparse.ArgumentParser(prog=f"hermes {command[0]}")
    setup_fn, handler_fn = commands[command[0]]
    setup_fn(parser)
    parsed = parser.parse_args(command[1:])
    sys.exit((handler_fn or parsed.func)(parsed) or 0)
if args[0] == "profile":
    if args[1] == "show" and not home(args[2]).is_dir():
        sys.exit(1)
    if args[1] == "create":
        (home(args[2]) / "skills").mkdir(parents=True)
        if "--no-skills" in args:
            (home(args[2]) / ".no-bundled-skills").touch()
        sync(home(args[2]))
    if args[1] == "use":
        (root / "active_profile").write_text(args[2])
    sys.exit(0)
assert args[0] == "-p", args
name, command = args[1], args[2:]
h = home(name)
path = h / "fake-config.json"
values = json.loads(path.read_text()) if path.exists() else {}
if command[:2] == ["config", "get"]:
    print(json.dumps(values.get(command[2], [])))
elif command[:2] == ["config", "set"]:
    try:
        values[command[2]] = json.loads(command[3])
    except ValueError:
        values[command[2]] = command[3]
elif command[:2] == ["plugins", "enable"]:
    # Like Hermes, only an enable that changes the list reloads the running gateway.
    if command[2] not in values.get("plugins.enabled", []):
        values.setdefault("plugins.enabled", []).append(command[2])
        path.write_text(json.dumps(values))
        reload_gateway(h)
elif command[:2] == ["plugins", "disable"]:
    if command[2] in values.get("plugins.enabled", []):
        values["plugins.enabled"].remove(command[2])
        path.write_text(json.dumps(values))
        reload_gateway(h)
elif command[:2] == ["skills", "opt-out"]:
    (h / ".no-bundled-skills").touch()
    if "--remove" in command:
        entries = manifest(h)
        for skill_name, origin in list(entries.items()):
            target = dest(h, skill_name)
            if not target.exists():
                del entries[skill_name]
            elif digest(target) == origin:
                shutil.rmtree(target)
                del entries[skill_name]
        save(h, entries)
elif command[:2] == ["skills", "reset"]:
    if "--restore" in command:
        shutil.rmtree(dest(h, command[2]), ignore_errors=True)
    entries = manifest(h)
    entries.pop(command[2], None)
    save(h, entries)
    sync(h)
elif command == ["sync"]:
    sync(h)
elif command[0] not in {"config", "plugins", "skills"}:
    run_plugin_command(h, command)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(values))
""".replace("PYTHON", sys.executable)
PSTACK_ALLOWED = ["in-your-own-words", "why", "how", "interrogate", "statechart", "technical-writing", "unslop"]
CC_DESCRIPTION = "Skills that only work in Claude Code."
SUPPORT_DIRS = {"references", "scripts", "templates", "assets"}
OTHER_AGENT = {"id": "claude-local", "displayName": "Claude (ACP)", "command": "/opt/claude-acp", "args": []}


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


def config(home):
    path = home / "fake-config.json"
    return json.loads(path.read_text()) if path.exists() else {}


def runtime_skills(home):
    """Skill name -> directories a Hermes session in this home loads: skills/ and skills.external_dirs
    without hidden and support directories, plus each enabled plugin's hermes/skills under its name."""
    found = {}
    for root in [home / "skills", *map(Path, config(home).get("skills.external_dirs", []))]:
        for skill_md in root.rglob("SKILL.md"):
            parts = skill_md.relative_to(root).parts[:-1]
            if SUPPORT_DIRS.isdisjoint(parts) and not any(part.startswith(".") for part in parts):
                found.setdefault(skill_md.parent.name, []).append(skill_md.parent)
    for plugin in config(home).get("plugins.enabled", []):
        for skill_md in (home / "plugins" / plugin / "hermes/skills").glob("*/SKILL.md"):
            found.setdefault(f"{plugin}:{skill_md.parent.name}", []).append(skill_md.parent)
    return found


def bb_catalog(user_home):
    """Skill names bb lists for acp-hermes-agent. The shipped resolver reads the default home's
    skills/ and skills.external_dirs. A customAgents entry with id hermes-agent adds its user roots,
    resolved from the user's home, with an optional name prefix."""
    def scan(root, prefix="", recursive=True):
        found = root.rglob("SKILL.md") if recursive else root.glob("*/SKILL.md")
        return {prefix + md.parent.name for md in found} if root.is_dir() else set()

    base = user_home / ".hermes"
    names = scan(base / "skills")
    for extra in config(base).get("skills.external_dirs", []):
        names |= scan(Path(extra))
    settings = user_home / "bb-provider-acp.json"
    agents = json.loads(json.loads(settings.read_text())["customAgents"] or "[]") if settings.exists() else []
    for agent in agents:
        if agent["id"] == "hermes-agent":
            for root in agent.get("nativeSkillRoots", {}).get("user", []):
                root = {"path": root} if isinstance(root, str) else root
                names |= scan(user_home / root["path"], root.get("namePrefix", ""), root.get("recursive", False))
    return names


class OperatorProfileSetupTests(unittest.TestCase):
    """Runs the real setup script from a fixture checkout against a fake hermes and bb."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name).resolve()
        self.home = self.tmp / "home"
        self.state = self.tmp / "state"
        self.repo = self.tmp / "skills"
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, script in {"hermes": FAKE_HERMES, "bb": FAKE_BB}.items():
            (bin_dir / name).write_text(script)
            (bin_dir / name).chmod(0o755)
        bundled = self.tmp / "bundled"
        write_tree(bundled, {**under("research", skill("arxiv")), **under("apple", skill("apple-notes")),
                             **under("autonomous-ai-agents", skill("hermes-agent"))})
        self.env = {"HOME": str(self.home), "XDG_STATE_HOME": str(self.state), "FAKE_BUNDLED": str(bundled),
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
        self.default.mkdir(parents=True)
        self.hermes("profile", "create", "default")
        (self.home / "bb-provider-acp.json").write_text(json.dumps({"customAgents": json.dumps([OTHER_AGENT])}))

    def pinned(self, repo, files):
        """A third-party source fetched by agents:sync at its approved commit."""
        upstream = self.tmp / "upstream" / repo
        sha = commit_repo(upstream, files)
        target = self.state / "ramtoshiya-agents/sources" / repo / sha
        target.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "-q", str(upstream), str(target), cwd=self.tmp)
        return sha

    def hermes(self, *args):
        subprocess.run([str(self.tmp / "bin/hermes"), *args], env=self.env, check=True)

    def setup_profile(self):
        result = subprocess.run([sys.executable, str(self.repo / "setup/hermes/operator_profile.py"),
                                 "--pstack", str(self.pstack)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def start_hermes(self):
        """What the first chat or gateway start, and every `hermes update`, do to each home."""
        for profile in ("operator", "default"):
            self.hermes("-p", profile, "sync")

    def expected(self):
        return {"read-x", "self-compact", "grilling", "operator-handoff", *PSTACK_ALLOWED, "korean-pack:korean"}

    def test_operator_knows_every_repository_skill_without_bundled_ones(self):
        self.setup_profile()
        self.start_hermes()

        skills = runtime_skills(self.operator)
        self.assertEqual(set(skills), self.expected())
        self.assertTrue((skills["self-compact"][0] / "scripts/compact.mjs").is_file())
        self.assertTrue((skills["grilling"][0] / "references/rounds.md").is_file())
        self.assertTrue((self.operator / "plugins/korean-pack/scripts/check.py").is_file())
        settings = config(self.operator)
        self.assertEqual(settings["skills.auto_load"], ["operator-handoff"])
        self.assertEqual(settings["agent.disabled_toolsets"], ["file", "code_execution", "delegation"])
        self.assertFalse(settings["memory.write_approval"])
        handoff = (skills["operator-handoff"][0] / "SKILL.md").read_text()
        self.assertIn(CC_DESCRIPTION, handoff)
        self.assertIn("`self-compact`", handoff)
        self.assertIn("`korean-pack:korean`", handoff)

    def test_installed_handoff_archives_finished_children(self):
        self.setup_profile()
        self.start_hermes()

        def results(text):
            return text.split("## Results {:#results}", 1)[1].split("\n## ", 1)[0]

        source = (ROOT / "setup/hermes/skills/operator-handoff/SKILL.md").read_text()
        installed = (runtime_skills(self.operator)["operator-handoff"][0] / "SKILL.md").read_text()
        self.assertEqual(results(installed), results(source))
        self.assertIn("bb thread archive <threadId>", results(installed))

    def test_bb_lists_what_the_operator_loads(self):
        self.setup_profile()
        self.start_hermes()

        self.assertEqual(bb_catalog(self.home), set(runtime_skills(self.operator)))
        self.assertEqual(set(runtime_skills(self.default)), set())
        self.assertNotIn("skills.external_dirs", config(self.default))
        agents = json.loads(json.loads((self.home / "bb-provider-acp.json").read_text())["customAgents"])
        self.assertEqual(agents[0], OTHER_AGENT)
        self.assertEqual([a["args"] for a in agents if a["id"] == "hermes-agent"], [["-p", "operator", "acp"]])

    def test_pstack_skills_stay_where_and_what_they_were(self):
        native = self.operator / "plugins/pstack-mode/plugin.yaml"
        write_tree(native.parent, {"plugin.yaml": "name: pstack-mode\n", "__init__.py": "\n"})
        self.setup_profile()

        for name in PSTACK_ALLOWED:
            installed = self.operator / "skills" / name / "SKILL.md"
            self.assertEqual(installed.read_text(),
                             (self.pstack / "plugins/pstack-mode/skills" / name / "SKILL.md").read_text())
        self.assertFalse((self.operator / "skills/tdd").exists())
        self.assertEqual(native.read_text(), "name: pstack-mode\n")

    def test_rerun_converges_on_the_marketplace_selection(self):
        self.setup_profile()
        self.start_hermes()
        self.setup_profile()
        self.start_hermes()

        skills = runtime_skills(self.operator)
        self.assertEqual(set(skills), self.expected())
        self.assertEqual([name for name, dirs in skills.items() if len(dirs) > 1], [])
        self.assertEqual(bb_catalog(self.home), self.expected())
        agents = json.loads(json.loads((self.home / "bb-provider-acp.json").read_text())["customAgents"])
        self.assertEqual([a["id"] for a in agents], ["claude-local", "hermes-agent"])

        self.marketplace["plugins"] = [p for p in self.marketplace["plugins"] if p["name"] not in {"grill-pack", "korean-pack"}]
        commit_repo(self.repo, {".claude-plugin/marketplace.json": json.dumps(self.marketplace)})
        self.setup_profile()

        expected = self.expected() - {"grilling", "korean-pack:korean"}
        self.assertEqual(set(runtime_skills(self.operator)), expected)
        self.assertEqual(bb_catalog(self.home), expected)

    def test_running_gateway_gets_changed_plugin_code(self):
        self.setup_profile()
        (self.operator / "gateway-running").touch()
        hook = "setup/hermes/plugins/skill-drafts/__init__.py"
        commit_repo(self.repo, {hook: (self.repo / hook).read_text() + "\n# changed\n"})

        output = self.setup_profile()

        loaded = json.loads((self.operator / "gateway-plugins.json").read_text())
        installed = (self.operator / "plugins/skill-drafts/__init__.py").read_bytes()
        self.assertTrue(installed.endswith(b"# changed\n"))
        self.assertEqual(loaded["skill-drafts"], hashlib.sha256(installed).hexdigest())
        self.assertIn("reloaded", output)

    def test_gateway_that_refuses_the_reload_fails_setup(self):
        self.setup_profile()
        (self.operator / "gateway-running").write_text("refuse")

        result = subprocess.run([sys.executable, str(self.repo / "setup/hermes/operator_profile.py"),
                                 "--pstack", str(self.pstack)], env=self.env, capture_output=True, text=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reload refused", result.stderr)

    def test_plugin_package_named_differently_from_its_entry_stops_setup(self):
        self.marketplace["plugins"][3]["name"] = "korean"
        commit_repo(self.repo, {".claude-plugin/marketplace.json": json.dumps(self.marketplace)})

        result = subprocess.run([sys.executable, str(self.repo / "setup/hermes/operator_profile.py"),
                                 "--pstack", str(self.pstack)], env=self.env, capture_output=True, text=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("korean-pack", result.stderr)

    def test_skill_change_draft_names_the_owning_source(self):
        self.setup_profile()
        sources = self.operator / "plugins/skill-drafts/sources.json"
        capture = self.tmp / "capture.json"
        hook = load("skill_drafts_installed", self.operator / "plugins/skill-drafts/__init__.py")
        self.enterContext(mock.patch.object(hook, "SOURCES", sources))
        self.enterContext(mock.patch.dict(os.environ, {
            "BB_CLI": str(self.tmp / "bin/bb"), "REPO": str(self.repo), "CAPTURE": str(capture)}))
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

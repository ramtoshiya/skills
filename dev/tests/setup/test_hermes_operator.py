import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "setup/hermes/plugins/skill-drafts/__init__.py"
SETUP = ROOT / "setup/hermes/operator_profile.py"
THREAD_ENV = ROOT / "setup/hermes/plugins/bb-thread-env/__init__.py"
TITLE_INPUT = ROOT / "setup/hermes/plugins/bb-title-input/__init__.py"
FAKE_BB = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
stdin = sys.stdin.read() if "-" in args else None
if os.environ.get("CALLS"):
    with open(os.environ["CALLS"], "a") as log:
        log.write(json.dumps({{"args": args, "stdin": stdin}}) + "\\n")
if args[:3] == ["plugin", "config", "provider-acp"]:
    store = Path(os.environ["HOME"]) / "bb-provider-acp.json"
    values = json.loads(store.read_text()) if store.exists() else {{"customAgents": ""}}
    if args[3:4] == ["set"]:
        # Like bb, refuse a skill root that is not relative to the user's home.
        for agent in (json.loads(args[5]) if args[4] == "customAgents" else []):
            for root in agent.get("nativeSkillRoots", {{}}).get("user", []):
                path = root if isinstance(root, str) else root["path"]
                if path.startswith("/") or ".." in path.split("/"):
                    sys.exit("Roots must be relative paths without dot segments")
        values[args[4]] = args[5]
        store.write_text(json.dumps(values))
    else:
        print(json.dumps({{"ok": True, "values": values}}))
elif args[:3] == ["provider", "models", "claude-code"]:
    efforts = [{{"reasoningEffort": e}} for e in ("low", "high")]
    print(json.dumps([{{"id": i, "supportedReasoningEfforts": efforts}} for i in (
        "claude-sonnet-5-5", "claude-opus-4-8", "claude-opus-5-5", "claude-opus-5", "claude-opus-5-5[1m]",
        "claude-opus-4-1-20250805")]))
elif args[:2] == ["plugin", "list"]:
    store = Path(os.environ["HOME"]) / "bb-plugins.json"
    print(json.dumps({{"plugins": json.loads(store.read_text()) if store.exists() else []}}))
elif args[:2] == ["plugin", "install"]:
    store = Path(os.environ["HOME"]) / "bb-plugins.json"
    path = args[2].removeprefix("path:")
    plugins = json.loads(store.read_text()) if store.exists() else []
    previous = next((p for p in plugins if p["id"] == Path(path).name), {{}})
    plugins = [p for p in plugins if p["id"] != Path(path).name]
    store.write_text(json.dumps([*plugins, {{**previous, "id": Path(path).name, "source": "path:" + path}}]))
elif args[:2] == ["thread", "list"]:
    store = Path(os.environ["HOME"]) / "bb-threads.json"
    print(store.read_text() if store.exists() else "[]")
elif args[:2] == ["thread", "spawn"]:
    if os.environ.get("FAIL_SPAWN"):
        sys.exit("HTTP 500: server down")
    print(json.dumps({{"id": "thr_analyst", "status": "pending"}}))
elif args[:2] == ["thread", "tell"]:
    print("queued")
else:
    print(json.dumps({{"ok": False, "error": {{"code": "unknown_command", "message": "unknown command"}}}}))
    sys.exit(1)
"""
FAKE_EXPORT = f"""#!{sys.executable}
import sys
open(sys.argv[-1], "w").write('{{"role": "user", "content": "keep it short"}}\\n')
"""


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def option(args, name):
    return args[args.index(name) + 1]


def hermes_runtime(origin, resolve):
    tools, approval = types.ModuleType("tools"), types.ModuleType("tools.write_approval")
    approval.current_origin = origin
    cli, session_env = types.ModuleType("hermes_cli"), types.ModuleType("hermes_cli.plugins_session_env")
    session_env.resolve_session_env = resolve
    return {"tools": tools, "tools.write_approval": approval,
            "hermes_cli": cli, "hermes_cli.plugins_session_env": session_env}


def reply(content, tools=0):
    calls = [types.SimpleNamespace(function=types.SimpleNamespace(name="skill_manage", arguments="{}"))] * tools
    return types.SimpleNamespace(content=content, tool_calls=calls)


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
            "profile": "operator", "modePath": "/pstack/mode.md",
            "researchProject": "proj_personal", "skillsDir": str(root / "profile/skills"),
            "sourcesPath": str(sources),
            "skills": {"unslop": {"repo": str(self.repo), "path": "skills/unslop", "installed": str(installed)}},
        }))
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, script in {"bb": FAKE_BB, "hermes": FAKE_EXPORT}.items():
            (bin_dir / name).write_text(script)
            (bin_dir / name).chmod(0o755)
        self.calls = root / "calls.jsonl"
        self.state = root / "profile/skill-drafts"
        self.origin = "background_review"
        self.threads = {"sess_1": "thr_op"}
        self.hook = load("skill_drafts_under_test", PLUGIN)
        self.now = 1_000_000.0
        self.proposals = self.hook.Proposals(self.state, sources, clock=lambda: self.now)
        self.proposals.poke = lambda: None
        self.enterContext(mock.patch.object(self.hook, "PROPOSALS", self.proposals))
        self.enterContext(mock.patch.dict(sys.modules, hermes_runtime(
            lambda: self.origin, lambda sid: {"BB_THREAD_ID": self.threads.get(sid)})))
        self.enterContext(mock.patch.dict(os.environ, {
            "BB_CLI": str(bin_dir / "bb"), "CALLS": str(self.calls),
            "PATH": os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])}))

    def call(self, args, turn="sess_1:task:t1", session="sess_1"):
        return self.hook.on_pre_tool_call(tool_name="skill_manage", args=args, session_id=session, turn_id=turn,
                                          tool_call_id="call_1")

    def respond(self, content, tools=0, turn="sess_1:task:t1", session="sess_1"):
        self.hook.on_post_api_request(session_id=session, turn_id=turn, assistant_message=reply(content, tools),
                                      assistant_tool_call_count=tools)

    def bb_calls(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def spawns(self):
        return [call for call in self.bb_calls() if call["args"][:2] == ["thread", "spawn"]]

    def evidence(self):
        return next(self.state.glob("proposals/*/evidence.md")).read_text()

    def review(self, args, turn="sess_1:task:t1", summary="The user asked twice for shorter replies."):
        self.respond("Checking unslop against this session.", tools=1, turn=turn)
        self.call(args, turn=turn)
        self.respond(summary, turn=turn)
        return self.proposals.flush_due()

    PATCH = {"action": "patch", "name": "unslop", "old_string": "Cut filler.", "new_string": "Cut all filler."}

    def test_other_tools_pass_through(self):
        self.assertIsNone(self.hook.on_pre_tool_call(tool_name="terminal", args={"command": "ls"}))

    def test_operator_call_is_sent_back_to_the_handoff(self):
        self.origin = "assistant_tool"

        result = self.call(self.PATCH)

        self.assertEqual(result["action"], "block")
        self.assertIn("operator-handoff", result["message"])
        self.assertEqual(self.proposals.flush_due(everything=True), [])
        self.assertEqual(self.bb_calls(), [])

    def test_review_becomes_one_analyst_under_the_operator_thread(self):
        self.respond("Checking unslop against this session.", tools=1)
        first = self.call({"operations": [self.PATCH]})
        second = self.call({"action": "create", "name": "fresh", "content": "---\nname: fresh\n---\n"})
        self.respond("The user asked twice for shorter replies.")

        self.assertEqual({first["action"], second["action"]}, {"block"})
        self.assertIn("separate agent", first["message"])
        self.assertEqual(self.bb_calls(), [])

        [outcome] = self.proposals.flush_due()
        self.assertRegex(outcome, r"^spawned \w+: thr_analyst$")
        [spawn] = self.spawns()
        args = spawn["args"]
        self.assertEqual(option(args, "--parent-thread"), "thr_op")
        self.assertEqual(option(args, "--project"), "proj_personal")
        self.assertEqual(option(args, "--new-environment"), "personal")
        self.assertEqual(option(args, "--provider"), "claude-code")
        self.assertEqual(option(args, "--model"), "claude-opus-5-5")
        self.assertEqual(option(args, "--reasoning-level"), "high")
        self.assertIn("Skill proposal: fresh, unslop", option(args, "--title"))
        brief = spawn["stdin"]
        self.assertTrue(brief.startswith("Read /pstack/mode.md and follow it"))
        self.assertIn("--parent-thread thr_op", brief)
        self.assertIn("`bb plugin config held-drafts --json`", brief)
        evidence = self.evidence()
        self.assertIn("-Cut filler.\n+Cut all filler.", evidence)
        self.assertIn("+name: fresh", evidence)
        self.assertIn("- `fresh`: not an installed skill from `sources.json`", evidence)
        self.assertLess(evidence.index("Checking unslop"), evidence.index("asked twice for shorter"))
        self.assertIn("keep it short", next(self.state.glob("proposals/*/session.jsonl")).read_text())
        self.assertEqual(self.skill_md.read_text(), "# Unslop\n\nCut filler.\n")

    def test_review_without_final_response_goes_out_after_ten_quiet_minutes(self):
        self.call(self.PATCH)

        self.now += 9 * 60
        self.assertEqual(self.proposals.flush_due(), [])
        self.now += 2 * 60
        self.assertEqual(len(self.proposals.flush_due()), 1)
        self.assertIn("closing summary is missing", self.evidence())

    def test_review_that_proposes_nothing_starts_no_analyst(self):
        self.respond("Nothing to change.")

        self.assertEqual(self.proposals.flush_due(), [])
        self.assertEqual(self.proposals.turns, {})
        self.assertEqual(self.bb_calls(), [])

    def test_repeated_proposal_goes_to_no_second_analyst_until_the_skill_changes(self):
        self.review(self.PATCH)
        repeat = self.review(self.PATCH, turn="sess_1:task:t2")

        self.assertTrue(repeat[0].startswith("duplicate"), repeat)
        self.assertIn("thr_analyst", repeat[0])
        self.assertEqual(len(self.spawns()), 1)

        self.skill_md.write_text("# Unslop\n\nCut filler.\nKeep examples.\n")
        self.review(self.PATCH, turn="sess_1:task:t3")
        self.assertEqual(len(self.spawns()), 2)

    def test_concurrent_flushes_send_a_repeated_proposal_to_one_analyst(self):
        second_reached_dispatch = threading.Event()
        first_spawning = threading.Event()
        gate_timed_out = []
        lock, run = self.proposals.dispatching, self.hook.run

        def note_second():
            if threading.current_thread().name == "second flush":
                second_reached_dispatch.set()

        class WatchedLock:
            def __enter__(self):
                note_second()
                return lock.__enter__()

            def __exit__(self, *exc):
                return lock.__exit__(*exc)

        def gated_run(command, stdin=None):
            if command[1:3] == ["thread", "spawn"]:
                note_second()
                if threading.current_thread().name == "first flush":
                    first_spawning.set()
                    if not second_reached_dispatch.wait(10):
                        gate_timed_out.append(True)
            return run(command, stdin)

        self.enterContext(mock.patch.object(self.proposals, "dispatching", WatchedLock()))
        self.enterContext(mock.patch.object(self.hook, "run", gated_run))
        outcomes = {}

        def flush(name):
            thread = threading.Thread(name=name, target=lambda: outcomes.update({name: self.proposals.flush_due()}))
            thread.start()
            return thread

        def record(turn):
            self.respond("Checking unslop against this session.", tools=1, turn=turn)
            self.call(self.PATCH, turn=turn)
            self.respond("Done.", turn=turn)

        record("sess_1:task:t1")
        first = flush("first flush")
        self.assertTrue(first_spawning.wait(10))
        record("sess_1:task:t2")
        second = flush("second flush")
        first.join(10)
        second.join(10)

        self.assertEqual(gate_timed_out, [])
        self.assertTrue(outcomes["first flush"][0].startswith("spawned"), outcomes)
        self.assertTrue(outcomes["second flush"][0].startswith("duplicate"), outcomes)
        self.assertEqual(len(self.spawns()), 1)

    def test_partial_repeat_names_the_earlier_analyst(self):
        self.review(self.PATCH)
        other = {"action": "patch", "name": "unslop", "old_string": "# Unslop", "new_string": "# Unslop it"}
        self.review({"operations": [self.PATCH, other]}, turn="sess_1:task:t2")

        self.assertEqual(len(self.spawns()), 2)
        [evidence] = [p.read_text() for p in self.state.glob("proposals/*/evidence.md") if "Unslop it" in p.read_text()]
        self.assertIn("already received", evidence)
        self.assertIn("@thread:thr_analyst", evidence)

    def test_spawn_failure_tells_the_operator_and_a_later_review_retries(self):
        with mock.patch.dict(os.environ, {"FAIL_SPAWN": "1"}):
            outcome = self.review(self.PATCH)

        self.assertTrue(outcome[0].startswith("failed"), outcome)
        [tell] = [c for c in self.bb_calls() if c["args"][:2] == ["thread", "tell"]]
        self.assertEqual(tell["args"][2], "thr_op")
        self.assertIn("[skill-drafts plugin]", tell["stdin"])
        self.assertIn("server down", tell["stdin"])

        self.review(self.PATCH, turn="sess_1:task:t2")
        self.assertEqual(len(self.spawns()), 2)

    def test_session_without_operator_thread_gets_a_top_level_analyst(self):
        self.threads = {}
        self.review(self.PATCH)

        [spawn] = self.spawns()
        self.assertNotIn("--parent-thread", spawn["args"])
        self.assertIn("leave the draft top-level", spawn["stdin"])
        self.assertIn("No bb thread shows this Hermes session", self.evidence())

    def test_failing_resolver_and_missing_bb_still_block(self):
        self.enterContext(mock.patch.dict(sys.modules, hermes_runtime(lambda: self.origin, mock.Mock(
            side_effect=RuntimeError("gateway gone")))))
        self.enterContext(mock.patch.dict(os.environ, {"BB_CLI": "", "PATH": "/nonexistent"}))

        self.assertEqual(self.call(self.PATCH)["action"], "block")
        self.respond("Done.")
        [outcome] = self.proposals.flush_due()

        self.assertTrue(outcome.startswith("failed"), outcome)
        self.assertIn("bb CLI is not on the gateway's PATH", outcome)
        self.assertIn("Exporting the stored conversation failed", self.evidence())

    def test_recording_failure_still_blocks(self):
        self.proposals.record_call = mock.Mock(side_effect=OSError("disk full"))

        result = self.call(self.PATCH)

        self.assertEqual(result["action"], "block")
        self.assertIn("disk full", result["message"])

    def test_unload_hands_over_a_review_in_progress(self):
        self.call(self.PATCH)

        self.proposals.stop()
        self.proposals.serve()

        self.assertEqual(len(self.spawns()), 1)
        self.assertIn("closing summary is missing", self.evidence())


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


INSTALLED_HERMES_PROBE = """
import importlib.util, json, sys, types
from gateway import run_api
from gateway.session_local_mcp import attach_editor_mcp, fingerprint, session_scope
spec = importlib.util.spec_from_file_location("bb_thread_env_probe", sys.argv[2])
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
bridge = {"name": "bb-bridge", "command": "node", "args": [], "env": [
    {"name": "BB_ACP_DYNAMIC_TOOL_TOKEN", "value": "secret-token"},
    {"name": "BB_ACP_DYNAMIC_TOOL_THREAD_ID", "value": "thr_installed"}]}
authority = types.SimpleNamespace(profile_id="operator")
run_api._ACTIVE_RUNNER = types.SimpleNamespace(session_authority=authority)
servers = [bridge]
data = {"scope": session_scope(authority, "local-bridge"), "fingerprint": fingerprint(servers)}
attach_editor_mcp(authority, types.SimpleNamespace(editor_mcp_json=json.dumps(data)), servers)
print(json.dumps({sid: plugin.resolve(sid) for sid in ("local-bridge", "local-other")}))
"""


@unittest.skipUnless(shutil.which("hermes"), "Hermes is not installed")
class BbThreadEnvInstalledHermesTests(unittest.TestCase):
    def test_bridge_session_gets_its_thread_in_installed_hermes(self):
        argv = json.loads(subprocess.run(["hermes", "--print-runtime-command"], capture_output=True,
                                         text=True, check=True).stdout)
        code = argv[-1]
        code = code[:code.rindex("runpy.run_module(")] + "runpy.run_path(sys.argv[1], run_name='__main__')"
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp, "probe.py")
            probe.write_text(INSTALLED_HERMES_PROBE)
            result = subprocess.run([*argv[:-1], code, str(probe), str(THREAD_ENV)], cwd=tmp,
                                    capture_output=True, text=True)

        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        resolved = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(resolved["local-bridge"]["BB_THREAD_ID"], "thr_installed")
        self.assertIsNone(resolved["local-other"]["BB_THREAD_ID"])
        self.assertNotIn("secret-token", json.dumps(resolved))


TITLE_PROBE = """
import importlib.util, json, sys, types
from agent import title_generator as tg
spec = importlib.util.spec_from_file_location("bb_title_input_probe", sys.argv[2])
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
block = "<system_instructions>\\nUse the bb CLI.\\n- skill: does things\\n</system_instructions>\\n"
messages = [block + "Fix the flaky login test", block + "로그인 테스트가 가끔 실패합니다 고쳐주세요", block]
def titles():
    return [[tg.derive_title(m), tg.build_title_input(m), tg.is_titleable_user_message(m)] for m in messages]
before = titles()
ctx = types.SimpleNamespace()
plugin.register(ctx)
plugin.register(ctx)
print(json.dumps({"before": before, "after": titles(), "wrappers": len(tg._CONTROL_WRAPPERS)}))
"""


@unittest.skipUnless(shutil.which("hermes"), "Hermes is not installed")
class BbTitleInputInstalledHermesTests(unittest.TestCase):
    """Hermes's own titler, as installed, reads bb's first message that starts with a <system_instructions> block."""

    def probe(self):
        argv = json.loads(subprocess.run(["hermes", "--print-runtime-command"], capture_output=True,
                                         text=True, check=True).stdout)
        code = argv[-1]
        code = code[:code.rindex("runpy.run_module(")] + "runpy.run_path(sys.argv[1], run_name='__main__')"
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp, "probe.py")
            script.write_text(TITLE_PROBE)
            result = subprocess.run([*argv[:-1], code, str(script), str(TITLE_INPUT)], cwd=tmp,
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return json.loads(result.stdout.splitlines()[-1])

    def test_titles_name_the_users_text_and_not_the_bb_block(self):
        result = self.probe()

        self.assertEqual(result["before"][0][0], "<system_instructions>")
        self.assertEqual([row[0] for row in result["after"]],
                         ["Fix the flaky login test", "로그인 테스트가 가끔 실패합니다 고쳐주세요", "Use the bb CLI."])
        self.assertEqual([row[1] for row in result["after"][:2]],
                         ["Fix the flaky login test", "로그인 테스트가 가끔 실패합니다 고쳐주세요"])

    def test_registering_twice_adds_the_wrapper_once(self):
        wrappers = self.probe()["wrappers"]

        self.assertEqual(wrappers, 11)


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
    sys.modules["agent"] = types.ModuleType("agent")
    sys.modules["agent"].title_generator = sys.modules["agent.title_generator"] = types.ModuleType("agent.title_generator")
    sys.modules["agent.title_generator"]._CONTROL_WRAPPERS = ()
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
elif command[:2] == ["sessions", "refresh-prompts"]:
    if os.environ.get("FAIL_REFRESH"):
        sys.exit("prompt refresh refused")
    print("Requested a system prompt refresh for every session in this profile.")
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
            **under("plugins/ramtoshiya/skills", {**skill("read-x"), **skill("self-compact"),
                                                   "self-compact/scripts/bb-compact.mjs": "//\n"}),
            **under("plugins/ramtoshiya-cc/skills", skill("claude-design-direct")),
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
        return {"read-x", "self-compact", "claude-design-direct", "grilling", "operator-handoff", *PSTACK_ALLOWED, "korean-pack:korean"}

    def test_operator_knows_every_repository_skill_without_bundled_ones(self):
        self.setup_profile()
        self.start_hermes()

        skills = runtime_skills(self.operator)
        self.assertEqual(set(skills), self.expected())
        self.assertTrue((skills["self-compact"][0] / "scripts/bb-compact.mjs").is_file())
        self.assertTrue((skills["grilling"][0] / "references/rounds.md").is_file())
        self.assertTrue((self.operator / "plugins/korean-pack/scripts/check.py").is_file())
        settings = config(self.operator)
        self.assertEqual(settings["skills.auto_load"], ["operator-handoff"])
        self.assertEqual(settings["agent.disabled_toolsets"], ["file", "code_execution", "delegation"])
        self.assertFalse(settings["memory.write_approval"])
        self.assertEqual(settings["compression.threshold_tokens"], 300000)
        self.assertEqual(settings["hooks.output_spill.max_chars"], 32000)
        self.assertEqual(settings["plugins.enabled"], ["skill-drafts", "bb-thread-env", "bb-title-input", "self-compact", "korean-pack"])
        self.assertTrue((self.operator / "plugins/self-compact/plugin.yaml").is_file())
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

    def test_installed_handoff_routes_every_worker_it_starts(self):
        self.setup_profile()
        self.start_hermes()

        installed = "".join(page.read_text() for page in
                            sorted(runtime_skills(self.operator)["operator-handoff"][0].rglob("*.md")))
        commands = [block.split("\n```", 1)[0].replace("\\\n", " ")
                    for block in installed.split("```sh\n")[1:]]
        starts = [c for c in commands if "bb draft create" in c or "bb nest spawn" in c]
        self.assertEqual(len(starts), 3)
        for command in starts:
            for flag in ("--provider <provider>", "--model <model-id>", "--reasoning-level <effort>"):
                self.assertIn(flag, command)
        workers = [c for c in starts if "bb nest spawn" in c and "--new-environment worktree" in c]
        self.assertEqual(len(workers), 1)
        self.assertIn("read -r -d '' brief <<'EOF'", workers[0])
        self.assertIn('--prompt "$brief"', workers[0])

    def test_bb_lists_what_the_operator_loads(self):
        self.setup_profile()
        self.start_hermes()

        self.assertEqual(bb_catalog(self.home), set(runtime_skills(self.operator)))
        self.assertEqual(set(runtime_skills(self.default)), set())
        self.assertNotIn("skills.external_dirs", config(self.default))
        agents = json.loads(json.loads((self.home / "bb-provider-acp.json").read_text())["customAgents"])
        self.assertEqual(agents[0], OTHER_AGENT)
        self.assertEqual([a["args"] for a in agents if a["id"] == "hermes-agent"], [["-p", "operator", "acp"]])
        self.assertEqual([a["supportsManualCompaction"] for a in agents if a["id"] == "hermes-agent"], [True])

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

    def test_trusted_repository_skills_load_from_its_main_checkout(self):
        project = self.home / "workspaces/contest"
        commit_repo(project, under(".hermes/skills", skill("planning")))
        worktree = self.tmp / "worktrees/thr_1/contest"
        git("worktree", "add", "-q", "-b", "thread", str(worktree), cwd=project)
        commit_repo(project, {".hermes/skills/planning/SKILL.md": "---\nname: planning\ndescription: current\n---\n"})
        self.setup_profile()
        self.hermes("-p", "operator", "config", "set", "skills.trusted_project_dirs", json.dumps([str(project)]))

        self.setup_profile()

        skills = runtime_skills(self.operator)
        self.assertEqual(skills["planning"], [project / ".hermes/skills/planning"])
        self.assertIn("description: current", (skills["planning"][0] / "SKILL.md").read_text())
        self.assertEqual(bb_catalog(self.home), set(skills))

        self.hermes("-p", "operator", "config", "set", "skills.trusted_project_dirs", "[]")
        self.setup_profile()

        self.assertEqual(set(runtime_skills(self.operator)), self.expected())
        self.assertEqual(bb_catalog(self.home), self.expected())

    def test_install_requests_prompt_refresh_for_continuing_sessions(self):
        output = self.setup_profile()

        calls = [json.loads(line) for line in (self.home / "hermes-calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls[-1], ["-p", "operator", "sessions", "refresh-prompts"])
        self.assertIn("Requested a system prompt refresh", output)

    def test_unchanged_install_leaves_sessions_and_gateway_alone(self):
        self.setup_profile()
        (self.operator / "gateway-running").touch()
        log = self.home / "hermes-calls.jsonl"
        log.unlink()

        output = self.setup_profile()

        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        self.assertIn("left alone", output)
        self.assertNotIn(["-p", "operator", "sessions", "refresh-prompts"], calls)
        self.assertFalse((self.operator / "gateway-plugins.json").exists())

    def test_changed_soul_refreshes_sessions(self):
        self.setup_profile()
        soul = self.operator / "SOUL.md"
        soul.write_text(soul.read_text() + "\nA preference added by agents:sync.\n")

        output = self.setup_profile()

        calls = [json.loads(line) for line in (self.home / "hermes-calls.jsonl").read_text().splitlines()]
        self.assertEqual(calls[-1], ["-p", "operator", "sessions", "refresh-prompts"])
        self.assertIn("Requested a system prompt refresh", output)

    def test_prompt_refresh_failure_fails_install(self):
        self.env["FAIL_REFRESH"] = "1"

        result = subprocess.run([sys.executable, str(self.repo / "setup/hermes/operator_profile.py"),
                                 "--pstack", str(self.pstack)], env=self.env, capture_output=True, text=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("prompt refresh refused", result.stderr)

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
        hook = "setup/hermes/plugins/skill-drafts/__init__.py"
        commit_repo(self.repo, {hook: (self.repo / hook).read_text() + "\n# changed\n"})

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

    def test_installed_plugin_gives_the_analyst_each_owning_source(self):
        self.setup_profile()
        sources = self.operator / "plugins/skill-drafts/sources.json"
        calls = self.tmp / "calls.jsonl"
        hook = load("skill_drafts_installed", self.operator / "plugins/skill-drafts/__init__.py")
        proposals = hook.Proposals(self.tmp / "drafts-state", sources)
        proposals.poke = lambda: None
        self.enterContext(mock.patch.object(hook, "PROPOSALS", proposals))
        self.enterContext(mock.patch.dict(sys.modules, hermes_runtime(
            lambda: "background_review", lambda sid: {"BB_THREAD_ID": "thr_op"})))
        self.enterContext(mock.patch.dict(os.environ, {"BB_CLI": str(self.tmp / "bin/bb"), "CALLS": str(calls)}))
        grill_sha = self.marketplace["plugins"][2]["source"]["sha"]

        for name in ("grilling", "read-x"):
            hook.on_pre_tool_call(tool_name="skill_manage", session_id="sess_1", turn_id="sess_1:t:1", args={
                "action": "patch", "name": name, "old_string": f"# {name}", "new_string": f"# {name.title()}"})
        hook.on_post_api_request(session_id="sess_1", turn_id="sess_1:t:1", assistant_message=reply("Done."),
                                 assistant_tool_call_count=0)
        [outcome] = proposals.flush_due()

        self.assertRegex(outcome, r"^spawned \w+: thr_analyst$")
        evidence = next((self.tmp / "drafts-state").glob("proposals/*/evidence.md")).read_text()
        self.assertIn("`skills/productivity/grilling` in https://github.com/fork/grill-skills", evidence)
        self.assertIn(grill_sha, evidence)
        self.assertIn("-# grilling\n+# Grilling", evidence)
        self.assertIn(f"`plugins/ramtoshiya/skills/read-x` in `{self.repo.resolve()}`", evidence)
        [spawn] = [json.loads(line) for line in calls.read_text().splitlines()
                   if json.loads(line)["args"][:2] == ["thread", "spawn"]]
        self.assertEqual(option(spawn["args"], "--project"), "proj_personal")
        handoff = self.operator / "skills/operator-handoff/SKILL.md"
        drafts = handoff.parent / "references/held-drafts.md"
        self.assertIn(f"`{handoff}`", spawn["stdin"])
        self.assertIn(f"`{drafts}`", spawn["stdin"])
        self.assertIn("## Create the draft", drafts.read_text())
        self.assertIn("--project proj_personal --new-environment personal", handoff.read_text())
        self.assertIn(f"`{self.repo.resolve()}/tools/claudex/README.md`",
                      (handoff.parent / "references/replay.md").read_text())
        for page in handoff.parent.rglob("*.md"):
            self.assertNotIn("{{", page.read_text(), page)


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

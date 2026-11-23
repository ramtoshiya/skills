import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_hermes_operator import FAKE_BB, OTHER_AGENT, load

ROOT = Path(__file__).resolve().parents[3]
PROVIDER = ROOT / "setup/hermes/plugins/claude-code-runtime/__init__.py"
COMMANDS = ROOT / "setup/hermes/plugins/claude-code-commands/__init__.py"
SETUP = ROOT / "setup/hermes/coder_profile.py"

FAKE_CLAUDE = f"""#!{sys.executable}
import json, os, sys, uuid
from pathlib import Path
args = sys.argv[1:]
prompt = sys.stdin.read()
work = Path(os.environ["FAKE_WORK"])
replies = json.loads((work / "replies.json").read_text())
reply = replies.pop(0)
(work / "replies.json").write_text(json.dumps(replies))
with open(work / "calls.jsonl", "a") as log:
    log.write(json.dumps({{"command": Path(sys.argv[0]).name, "args": args, "prompt": prompt, "env": {{
        name: os.environ.get(name) for name in
        ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "ANTHROPIC_CUSTOM_HEADERS", "HERMES_HOME")}}}}) + "\\n")
session = args[args.index("--session-id") + 1] if "--session-id" in args else str(uuid.uuid4())
if "--resume" in args and "--fork-session" not in args:
    session = args[args.index("--resume") + 1]
transcript = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "work" / f"{{session}}.jsonl"
transcript.parent.mkdir(parents=True, exist_ok=True)
transcript.touch()
events = [{{"type": "system", "subtype": "init", "session_id": session}}]
if reply.get("tool"):
    events += [
        {{"type": "assistant", "message": {{"id": "m1", "content": [
            {{"type": "tool_use", "id": "t1", "name": "Bash", "input": {{"command": "pwd"}}}}]}}}},
        {{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "t1", "content": "/work"}}]}}}}]
events.append({{"type": "result", "subtype": "success", "is_error": False, "result": reply["text"],
                "session_id": session,
                "usage": {{"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 100,
                          "output_tokens": 7}},
                "modelUsage": {{"any": {{"inputTokens": 90000, "cacheCreationInputTokens": 90000,
                                        "cacheReadInputTokens": 900000, "outputTokens": 9000}}}}}})
print("\\n".join(json.dumps(event) for event in events))
"""

PROBE = """
import importlib.util, json, os, sys
# The runtime starts only from an installed Hermes home, so the scratch home applies from here on.
os.environ["HERMES_HOME"] = os.environ["FAKE_HERMES_HOME"]
spec = importlib.util.spec_from_file_location("claude_code_runtime_probe", sys.argv[2])
runtime = sys.modules[spec.name] = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
from providers import get_provider_profile
profile = get_provider_profile("claude-code-runtime")
client = profile.create_client()
tools = [{"type": "function", "function": {"name": "skill_manage", "description": "Save a skill",
          "parameters": {"type": "object", "properties": {"name": {"type": "string"}}}}}]
system = {"role": "system", "content": "You are Hermes."}
out = {}

def extras(session, scope):
    return profile.build_api_kwargs_extras(reasoning_config={"enabled": True, "effort": "high"},
                                           session_id=session, cache_scope_id=scope)[0]

def summary(answer):
    message = answer.choices[0].message
    return {"text": message.content, "calls": [c.function.name for c in message.tool_calls or []],
            "steps": getattr(answer, "hermes_provider_tool_iterations", None)}

user = {"role": "user", "content": "list the files"}
out["turn1"] = summary(client.chat.completions.create(model="haiku", messages=[system, user], tools=tools,
                                                      extra_body=extras("sess-1", "gwk_first")))
out["turn2"] = summary(client.chat.completions.create(model="haiku", messages=[system, user], tools=tools,
                                                      extra_body=extras("sess-1", "gwk_second")))
review = {"role": "user", "content": runtime.REVIEW_PROMPTS[1]}
out["review"] = summary(client.chat.completions.create(model="haiku", messages=[system, user, review], tools=tools,
                                                       extra_body=extras("sess-1", "gwk_second")))
out["gpt_turn"] = summary(client.chat.completions.create(model="gpt-6-luna", messages=[system, user], tools=tools,
                                                         extra_body=extras("sess-2", None)))
out["gpt_review"] = summary(client.chat.completions.create(model="gpt-6-luna", messages=[system, user, review],
                                                           tools=tools, extra_body=extras("sess-2", None)))
out["settings"] = runtime.REVIEW_SETTINGS
out["review_prompt"] = runtime.REVIEW_PROMPTS[1]
print(json.dumps(out))
"""

VALID_CALL = ('<tool_call>{"id": "c1", "type": "function", "function": {"name": "skill_manage", '
              '"arguments": "{\\"name\\": \\"x\\"}"}}</tool_call>')
INVALID_CALL = ('<tool_call>{"id": "c1", "type": "function", "function": {"name": "skill_manage", '
                '"arguments": "{}"}]}</tool_call>')


def option(args, name):
    return args[args.index(name) + 1] if name in args else None


@unittest.skipUnless(shutil.which("hermes"), "Hermes is not installed")
class ClaudeCodeRuntimeInstalledHermesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        for name in ("claude", "claudex"):
            (bin_dir / name).write_text(FAKE_CLAUDE)
            (bin_dir / name).chmod(0o755)
        (tmp / "replies.json").write_text(json.dumps([
            {"text": "done", "tool": True}, {"text": "still done", "tool": True},
            {"text": INVALID_CALL}, {"text": VALID_CALL},
            {"text": "gpt done"}, {"text": VALID_CALL}]))
        (tmp / "home").mkdir()
        (tmp / "probe.py").write_text(PROBE)
        argv = json.loads(subprocess.run(["hermes", "--print-runtime-command"], capture_output=True,
                                         text=True, check=True).stdout)
        code = argv[-1]
        code = code[:code.rindex("runpy.run_module(")] + "runpy.run_path(sys.argv[1], run_name='__main__')"
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_HERMES_HOME": str(tmp / "home"),
               "HERMES_DISABLE_LAZY_INSTALLS": "1", "CLAUDE_CONFIG_DIR": str(tmp / "claude"),
               "FAKE_WORK": str(tmp)}
        env.pop("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", None)
        result = subprocess.run([*argv[:-1], code, str(tmp / "probe.py"), str(PROVIDER)], cwd=tmp, env=env,
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(result.stderr[-3000:])
        cls.out = json.loads(result.stdout.splitlines()[-1])
        cls.calls = [json.loads(line) for line in (tmp / "calls.jsonl").read_text().splitlines()]
        cls.usage = [json.loads(line) for line in (tmp / "home/claude-code-runtime/usage.jsonl").read_text().splitlines()]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_second_turn_resumes_the_first_turns_session_when_the_cache_scope_changes(self):
        first, second = self.calls[0]["args"], self.calls[1]["args"]
        self.assertIsNotNone(option(first, "--session-id"))
        self.assertEqual(option(second, "--resume"), option(first, "--session-id"))
        self.assertEqual(self.calls[1]["prompt"], "list the files")

    def test_coding_turn_returns_claude_codes_tool_steps(self):
        self.assertEqual(self.out["turn1"], {"text": "done", "calls": [], "steps": 1})

    def test_review_forks_the_coding_session_with_the_same_prefix_flags_and_environment(self):
        coding, fork = self.calls[1], self.calls[2]
        self.assertEqual(option(fork["args"], "--resume"), option(coding["args"], "--resume"))
        self.assertIn("--fork-session", fork["args"])
        for flag in ("--model", "--effort", "--append-system-prompt-file", "--plugin-dir"):
            self.assertEqual(option(fork["args"], flag), option(coding["args"], flag), flag)
        self.assertEqual(fork["env"], coding["env"])
        self.assertTrue(fork["prompt"].startswith(self.out["review_prompt"]))
        self.assertIn("skill_manage", fork["prompt"])

    def test_claude_code_tools_are_refused_inside_the_review(self):
        hook = json.loads(self.out["settings"])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        result = subprocess.run(["sh", "-c", hook], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("<tool_call>", result.stderr)
        self.assertEqual(option(self.calls[2]["args"], "--settings"), self.out["settings"])

    def test_unparsable_tool_call_is_asked_again_once_in_the_same_fork(self):
        retry = self.calls[3]
        self.assertEqual(option(retry["args"], "--resume"), self.usage[2]["claude_session"])
        self.assertNotIn("--fork-session", retry["args"])
        self.assertIn("not valid JSON", retry["prompt"])
        self.assertEqual(self.out["review"]["calls"], ["skill_manage"])

    def test_usage_rows_count_this_run_only_and_sum_a_retry(self):
        self.assertEqual([(row["purpose"], row["model"]) for row in self.usage], [
            ("coding", "haiku"), ("coding", "haiku"), ("review", "haiku"),
            ("coding", "gpt-6-luna"), ("review", "gpt-6-luna")])
        self.assertEqual({k: self.usage[1][k] for k in ("fresh_input", "cache_read", "output")},
                         {"fresh_input": 15, "cache_read": 100, "output": 7})
        self.assertEqual({k: self.usage[2][k] for k in ("fresh_input", "cache_read", "output")},
                         {"fresh_input": 30, "cache_read": 200, "output": 14})
        self.assertEqual(self.usage[0]["conversation"], "sess-1")

    def test_gpt_models_run_through_claudex_and_the_fork_names_the_coding_session(self):
        gpt_turn, gpt_fork = self.calls[4], self.calls[5]
        self.assertEqual([call["command"] for call in self.calls],
                         ["claude", "claude", "claude", "claude", "claudex", "claudex"])
        self.assertEqual(option(gpt_turn["args"], "--model"), "gpt-6-luna")
        self.assertEqual(gpt_fork["env"]["ANTHROPIC_CUSTOM_HEADERS"],
                         f"X-Claude-Code-Session-Id: {option(gpt_turn['args'], '--session-id')}")
        self.assertIsNone(gpt_turn["env"]["ANTHROPIC_CUSTOM_HEADERS"])
        self.assertIsNone(gpt_turn["env"]["HERMES_HOME"])


class UsageSummaryTests(unittest.TestCase):
    def test_a_is_review_cost_over_coding_cost_with_cache_reads_at_a_tenth(self):
        commands = load("claude_code_commands", COMMANDS)
        rows = [
            {"ts": 1, "conversation": "s1", "purpose": "coding", "model": "sonnet",
             "fresh_input": 1000, "cache_read": 10000, "output": 50},
            {"ts": 2, "conversation": "s1", "purpose": "review", "model": "sonnet",
             "fresh_input": 100, "cache_read": 20000, "output": 30},
            {"ts": 3, "conversation": "", "purpose": "title", "model": "sonnet",
             "fresh_input": 500, "cache_read": 0, "output": 10},
        ]
        summary = {entry["conversation"]: entry for entry in commands.summarize(rows)}
        self.assertEqual(summary["s1"]["coding"]["cost"], 2000)
        self.assertEqual(summary["s1"]["review"]["cost"], 2100)
        self.assertEqual(summary["s1"]["a"], 1.05)
        self.assertIsNone(summary[""]["a"])
        self.assertIn("(no session)", commands.table(commands.summarize(rows)))


FAKE_HERMES = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
home = Path(os.environ["HOME"])
with open(home / "hermes-calls.jsonl", "a") as log:
    log.write(json.dumps(args) + "\\n")
profile = home / ".hermes/profiles/coder"
store = home / "coder-config.json"
config = json.loads(store.read_text()) if store.exists() else {{}}
if args[:3] == ["profile", "show", "coder"]:
    sys.exit(0 if profile.is_dir() else 1)
elif args[:3] == ["profile", "create", "coder"]:
    profile.mkdir(parents=True)
elif args[:4] == ["-p", "coder", "config", "get"]:
    if args[4] not in config:
        sys.exit("Config key not set: " + args[4])
    print(json.dumps(config[args[4]]))
elif args[:4] == ["-p", "coder", "config", "set"]:
    config[args[4]] = args[5]
    store.write_text(json.dumps(config))
elif args[:4] == ["-p", "coder", "plugins", "enable"]:
    pass
elif args[:4] == ["-p", "coder", "claude-code", "reload"]:
    print(json.dumps({{"reloaded": True}}))
else:
    sys.exit("unexpected hermes call: " + " ".join(args))
"""


class CoderInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        for name, script in {"hermes": FAKE_HERMES, "bb": FAKE_BB}.items():
            (bin_dir / name).write_text(script)
            (bin_dir / name).chmod(0o755)
        (self.home / "bb-provider-acp.json").write_text(json.dumps({"customAgents": json.dumps([OTHER_AGENT])}))
        self.env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(self.home),
                    "XDG_STATE_HOME": str(self.home / "state"), "BB_CLI": str(bin_dir / "bb")}

    def install(self, *args):
        return subprocess.run([sys.executable, "-I", str(SETUP), *args], env=self.env, capture_output=True, text=True)

    def config(self):
        return json.loads((self.home / "coder-config.json").read_text())

    def test_install_creates_the_profile_without_logins_and_keeps_a_model_the_user_picked(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in (self.home / "hermes-calls.jsonl").read_text().splitlines()]
        create = next(call for call in calls if call[:2] == ["profile", "create"])
        self.assertIn("--no-credentials", create)
        self.assertFalse([call for call in calls if call[:2] == ["profile", "use"]])
        self.assertEqual(self.config()["model.default"], "sonnet")
        self.assertEqual(self.config()["model.provider"], "claude-code-runtime")
        self.assertTrue((self.home / ".hermes/profiles/coder/plugins/model-providers/claude-code-runtime/plugin.yaml")
                        .is_file())
        agents = json.loads(json.loads((self.home / "bb-provider-acp.json").read_text())["customAgents"])
        self.assertEqual([agent["id"] for agent in agents], [OTHER_AGENT["id"], "hermes-coder"])
        self.assertEqual(agents[1]["args"], ["-p", "coder", "acp"])

        config = self.config() | {"model.default": "gpt-6-luna"}
        (self.home / "coder-config.json").write_text(json.dumps(config))
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.config()["model.default"], "gpt-6-luna")

    def test_check_reports_an_installed_plugin_file_that_changed(self):
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.install("--check").returncode, 0)

        installed = self.home / ".hermes/profiles/coder/plugins/claude-code-commands/__init__.py"
        installed.write_text(installed.read_text() + "\n# edited\n")
        result = self.install("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("plugin files changed", result.stderr)


if __name__ == "__main__":
    unittest.main()

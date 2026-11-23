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
LAUNCHER = ROOT / "setup/hermes/coder_acp.py"

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
model = reply.get("model_id") or args[args.index("--model") + 1]
events = [{{"type": "system", "subtype": "init", "session_id": session, "model": model}}]
if reply.get("tool"):
    events += [
        {{"type": "assistant", "message": {{"id": "m1", "content": [
            *([{{"type": "text", "text": reply["narration"]}}] if reply.get("narration") else []),
            {{"type": "tool_use", "id": "t1", "name": "Bash", "input": {{"command": reply.get("command", "pwd")}}}}]}}}},
        {{"type": "user", "message": {{"content": [
            {{"type": "tool_result", "tool_use_id": "t1", "content": reply.get("output", "/work")}}]}}}}]
events += [{{"type": "assistant", "message": {{"id": f"u{{index}}", "content": [{{"type": "text", "text": "..."}}],
                                            "usage": usage}}}} for index, usage in enumerate(reply.get("call_usage", []))]
events.append({{"type": "result", "subtype": "success", "is_error": False, "result": reply["text"],
                "session_id": session,
                "usage": reply.get("usage", {{"input_tokens": 10, "cache_creation_input_tokens": 5,
                                              "cache_read_input_tokens": 100, "output_tokens": 7}}),
                "modelUsage": {{model: {{"inputTokens": 90000, "cacheCreationInputTokens": 90000,
                                        "cacheReadInputTokens": 900000, "outputTokens": 9000,
                                        "contextWindow": reply.get("window", 1000000)}}}}}})
print("\\n".join(json.dumps(event) for event in events))
"""

PROBE = """
import importlib.util, json, os, sys
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
first = client.chat.completions.create(model="haiku", messages=[system, user], tools=tools,
                                      extra_body=extras("sess-1", "gwk_first"))
out["turn1"] = summary(first)
out["turn1_usage"] = {name: getattr(first.usage, name, None)
                      for name in ("prompt_tokens", "initial_prompt_tokens", "initial_cached_tokens")}
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
out["windows"] = {model: profile.get_model_context_length(model) for model in ("haiku", "opus", "gpt-6-luna")}
print(json.dumps(out))
"""

FAKE_TELL = f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
with open(Path(os.environ["FAKE_WORK"]) / "bb.jsonl", "a") as log:
    log.write(json.dumps({{"args": sys.argv[1:], "BB_THREAD_ID": os.environ.get("BB_THREAD_ID")}}) + "\\n")
"""

REFINE_PROBE = PROBE.split("user = {")[0] + """
from hermes_cli.plugins_session_env import register_session_env
from hermes_constants import hermes_home_key
register_session_env(hermes_home_key(), ["BB_THREAD_ID"], lambda session: {"BB_THREAD_ID": "thr_parent"})
user = {"role": "user", "content": "run the child"}
for session in ("plain", "proposals", "unrelated"):
    client.chat.completions.create(model="haiku", messages=[system, user], tools=tools,
                                   extra_body=extras(session, None))
print(json.dumps(out))
"""

CHILD_PROBE = PROBE.split("user = {")[0] + """
def attempt(**request):
    try:
        return summary(client.chat.completions.create(**request))
    except Exception as error:
        return {"error": str(error)}

user = {"role": "user", "content": "find the build command"}
out["turn"] = attempt(model="haiku", messages=[system, user], tools=tools, extra_body=extras("child-1", None))
review = {"role": "user", "content": runtime.REVIEW_PROMPTS[0]}
out["review"] = attempt(model="haiku", messages=[system, user, review], tools=tools, extra_body=extras("child-1", None))
out["astra"] = attempt(model="gpt-6.2-astra", messages=[system, user], tools=tools, extra_body=extras("child-2", None))
out["window"] = profile.get_model_context_length("haiku")
print(json.dumps(out))
"""

LIVE_PROBE = PROBE.split("user = {")[0] + """
import gateway.run_api
seen = []

class Agent:
    session_id = "live-1"
    def __getattr__(self, name):
        if name.endswith("callback") or name == "_emit_interim_assistant_message":
            return lambda *args, **kwargs: seen.append([name, *args])
        raise AttributeError(name)

class Runner:
    def _snapshot_running_agents(self):
        return {"route": Agent()}

gateway.run_api._ACTIVE_RUNNER = Runner()
user = {"role": "user", "content": "list the files"}
out["turn"] = summary(client.chat.completions.create(model="haiku", messages=[system, user], tools=tools,
                                                     extra_body=extras("live-1", None)))
out["other"] = summary(client.chat.completions.create(model="haiku", messages=[system, user], tools=tools,
                                                      extra_body=extras("other-1", None)))
out["seen"] = seen
print(json.dumps(out))
"""

VALID_CALL = ('<tool_call>{"id": "c1", "type": "function", "function": {"name": "skill_manage", '
              '"arguments": "{\\"name\\": \\"x\\"}"}}</tool_call>')
INVALID_CALL = ('<tool_call>{"id": "c1", "type": "function", "function": {"name": "skill_manage", '
                '"arguments": "{}"}]}</tool_call>')


REPLAY_RUN = {"input_tokens": 26, "cache_creation_input_tokens": 53775, "cache_read_input_tokens": 945051,
              "output_tokens": 3000}
REPLAY_CALLS = [{"input_tokens": 2, "cache_creation_input_tokens": 681, "cache_read_input_tokens": 56520, "output_tokens": 90},
                {"input_tokens": 2, "cache_creation_input_tokens": 1593, "cache_read_input_tokens": 70147,
                 "output_tokens": 120}]


def option(args, name):
    return args[args.index(name) + 1] if name in args else None


def guard(args: list[str], event: dict) -> subprocess.CompletedProcess:
    hook = json.loads(option(args, "--settings"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    return subprocess.run(["sh", "-c", hook], input=json.dumps(event), capture_output=True, text=True)


PSTACK_ROOT = "/opt/pstack-mode/plugins/pstack-mode"
MODE_POINTER = f"Read `{PSTACK_ROOT}/mode.md` and `{PSTACK_ROOT}/HOSTS.md` before work"


def turn_context(args: list[str]) -> str:
    hooks = json.loads(option(args, "--settings"))["hooks"].get("UserPromptSubmit", [])
    return "".join(subprocess.run(["sh", "-c", hook["command"]], input="{}", capture_output=True, text=True,
                                  check=True).stdout for entry in hooks for hook in entry["hooks"])


def probe(tmp: Path, script: str, replies: list[dict], config: str) -> tuple[dict, list[dict], Path]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    for name, fake in (("claude", FAKE_CLAUDE), ("claudex", FAKE_CLAUDE), ("bb", FAKE_TELL)):
        (bin_dir / name).write_text(fake)
        (bin_dir / name).chmod(0o755)
    (tmp / "replies.json").write_text(json.dumps(replies))
    (tmp / "home").mkdir()
    (tmp / "home/config.yaml").write_text(config)
    (tmp / "probe.py").write_text(script)
    argv = json.loads(subprocess.run(["hermes", "--print-runtime-command"], capture_output=True,
                                     text=True, check=True).stdout)
    code = argv[-1]
    code = code[:code.rindex("runpy.run_module(")] + "runpy.run_path(sys.argv[1], run_name='__main__')"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_HERMES_HOME": str(tmp / "home"),
           "HERMES_DISABLE_LAZY_INSTALLS": "1", "CLAUDE_CONFIG_DIR": str(tmp / "claude"),
           "FAKE_WORK": str(tmp)}
    env.pop("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", None)
    env.pop("BB_CLI", None)
    result = subprocess.run([*argv[:-1], code, str(tmp / "probe.py"), str(PROVIDER)], cwd=tmp, env=env,
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(result.stderr[-3000:])
    calls = tmp / "calls.jsonl"
    return (json.loads(result.stdout.splitlines()[-1]),
            [json.loads(line) for line in calls.read_text().splitlines()] if calls.is_file() else [],
            tmp / "home/claude-code-runtime")


def rows(runtime: Path) -> list[dict]:
    path = runtime / "usage.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


@unittest.skipUnless(shutil.which("hermes"), "Hermes is not installed")
class ClaudeCodeRuntimeInstalledHermesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out, cls.calls, runtime = probe(Path(cls.tmp.name), PROBE, [
            {"text": "done", "tool": True, "call_usage": REPLAY_CALLS, "usage": REPLAY_RUN},
            {"text": "still done", "tool": True},
            {"text": INVALID_CALL}, {"text": VALID_CALL},
            {"text": "gpt done", "window": 872000}, {"text": VALID_CALL, "window": 872000}],
            f"claude_code_runtime:\n  subagent_provider: acp-child-coders\n  pstack_root: {PSTACK_ROOT}\n")
        cls.usage = rows(runtime)

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
        for flag in ("--model", "--effort", "--append-system-prompt-file", "--plugin-dir", "--disallowedTools"):
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

    def test_coding_sessions_start_subagents_as_child_coder_threads_instead_of_the_agent_tool(self):
        coding = self.calls[0]["args"]
        self.assertEqual(option(coding, "--disallowedTools"), "Agent")
        context = Path(option(coding, "--append-system-prompt-file")).read_text()
        self.assertIn("bb nest spawn --provider acp-child-coders", context)
        self.assertIn("`--provider acp-child-coders` replaces the provider that ramtoshiya:worker-routing", context)
        self.assertNotIn("Learning proposals", context)

    def test_coding_session_hook_refuses_a_subagent_spawn_that_can_wake_this_session(self):
        for command, code in {
            "bb nest spawn --provider acp-child-coders --model claude-code-runtime:haiku": 2,
            "bb nest spawn --provider acp-child-coders --parent-notifications stuck --title t": 2,
            'bb thread spawn --parent-self --provider acp-child-coders --prompt "go"': 2,
            "bb nest spawn --provider acp-child-coders --parent-notifications off --title t": 0,
            '"$BB_CLI" nest spawn --parent-notifications=off --provider claude-code': 0,
            "bb thread wait thr_1 --timeout 600 && bb thread output thr_1": 0,
        }.items():
            result = guard(self.calls[0]["args"], {"tool_name": "Bash", "tool_input": {"command": command}})
            self.assertEqual(result.returncode, code, f"{command}: {result.stderr}")
            if code:
                self.assertIn("--parent-notifications off", result.stderr, command)

    def test_review_keeps_only_child_proposals_it_can_confirm(self):
        self.assertIn("proposal you cannot confirm", self.calls[2]["prompt"])

    def test_coding_sessions_follow_the_pstack_mode_and_check_it_every_turn(self):
        for coding in (self.calls[0], self.calls[1], self.calls[4]):
            context = Path(option(coding["args"], "--append-system-prompt-file")).read_text()
            self.assertIn(MODE_POINTER, context)
            check = turn_context(coding["args"])
            self.assertIn("[pstack-mode turn check]", check)
            self.assertIn(f"{PSTACK_ROOT}/mode.md", check)

    def test_hermes_meters_the_last_api_calls_prompt_and_counts_the_whole_run(self):
        self.assertEqual(self.out["turn1_usage"], {"prompt_tokens": 998_852, "initial_prompt_tokens": 71_742,
                                                   "initial_cached_tokens": 70_147})

    def test_hermes_knows_the_context_window_claude_code_runs_with(self):
        self.assertEqual(self.out["windows"], {"haiku": 1_000_000, "opus": 1_000_000, "gpt-6-luna": 872_000})

    def test_the_review_fork_runs_no_turn_check(self):
        self.assertEqual(turn_context(self.calls[2]["args"]), "")


CHILD_ANSWER = "Ran 18 tests, OK.\n\n## Learning proposals\n- Run one setup file with -p 'test_x.py'."


@unittest.skipUnless(shutil.which("hermes"), "Hermes is not installed")
class ChildProposalReviewTests(unittest.TestCase):
    def test_a_turn_that_reads_child_proposals_queues_refine_on_its_own_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe(Path(tmp), REFINE_PROBE, [
                {"text": "listed", "tool": True},
                {"text": "child done", "tool": True, "output": CHILD_ANSWER,
                 "command": "bb thread wait thr_c --timeout 600 && bb thread output thr_c"},
                {"text": "read docs", "tool": True, "output": CHILD_ANSWER, "command": "grep -n proposals docs/setup.md"}],
                "claude_code_runtime:\n  subagent_provider: acp-child-coders\n")
            tells = [json.loads(line) for line in (Path(tmp) / "bb.jsonl").read_text().splitlines()]
        self.assertEqual(len(tells), 1)
        self.assertEqual(tells[0]["args"][:4], ["thread", "tell", "thr_parent", "--mode"])
        self.assertEqual(tells[0]["args"][4], "queue")
        self.assertTrue(tells[0]["args"][5].startswith("/refine [Automatic, sent by Hermes Coder"))
        self.assertIsNone(tells[0]["BB_THREAD_ID"])


GUARD_EVENTS = {
    "write a learned skill": ({"tool_name": "Write", "tool_input": {"file_path": "{learner}/skills/x/SKILL.md"}}, 2),
    "edit memory": ({"tool_name": "Edit", "tool_input": {"file_path": "{learner}/memories/MEMORY.md"}}, 2),
    "append memory from the shell": ({"tool_name": "Bash", "tool_input": {
        "command": "echo note >> {learner}/memories/MEMORY.md"}}, 2),
    "start a learner thread": ({"tool_name": "Bash", "tool_input": {
        "command": "bb nest spawn --provider acp-learner --parent-notifications off --model claude-code-runtime:haiku"}}, 2),
    "start a claude-code worker": ({"tool_name": "Bash", "tool_input": {
        "command": "bb nest spawn --provider claude-code --parent-notifications off --model haiku"}}, 2),
    "start a child coder that can wake this session": ({"tool_name": "Bash", "tool_input": {
        "command": "bb nest spawn --provider acp-child-coders --model claude-code-runtime:haiku"}}, 2),
    "start a child coder": ({"tool_name": "Bash", "tool_input": {
        "command": "bb nest spawn --provider acp-child-coders --parent-notifications off --model claude-code-runtime:haiku"}}, 0),
    "read memory": ({"tool_name": "Read", "tool_input": {"file_path": "{learner}/memories/MEMORY.md"}}, 0),
    "write project code": ({"tool_name": "Write", "tool_input": {"file_path": "{work}/src/app.py"}}, 0),
}


@unittest.skipUnless(shutil.which("hermes"), "Hermes is not installed")
@unittest.skipUnless(shutil.which("hermes"), "Hermes is not installed")
class LiveProgressTests(unittest.TestCase):
    def test_the_running_sessions_viewers_see_claude_codes_steps_before_the_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, _, _ = probe(Path(tmp), LIVE_PROBE, [
                {"text": "done", "tool": True, "narration": "Checking the files.", "output": "a.txt"},
                {"text": "other done", "tool": True}], "")
        self.assertEqual(out["turn"], {"text": "done", "calls": [], "steps": 1})
        self.assertEqual([event[0] for event in out["seen"]], [
            "_emit_interim_assistant_message", "tool_progress_callback", "tool_start_callback",
            "tool_progress_callback", "tool_complete_callback"])
        self.assertEqual(out["seen"][0][1], {"role": "assistant", "content": "Checking the files."})
        self.assertEqual(out["seen"][2][1:], ["t1", "Bash", {"command": "pwd"}])
        self.assertEqual(out["seen"][4][1:], ["t1", "Bash", {"command": "pwd"}, "a.txt"])


class ChildCoderProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.learner = tmp / "learner"
        (cls.learner / "memories").mkdir(parents=True)
        (cls.learner / "memories/MEMORY.md").write_text("The build command is make kestrel.")
        (cls.learner / "skills/repo-build").mkdir(parents=True)
        (cls.learner / "skills/repo-build/SKILL.md").write_text("---\nname: repo-build\n---\nRun make.\n")
        config = ("claude_code_runtime:\n"
                  f"  learner_home: {cls.learner}\n"
                  "  subagent_provider: acp-child-coders\n"
                  f"  pstack_root: {PSTACK_ROOT}\n"
                  "auxiliary:\n  background_review:\n    enabled: false\n")
        cls.out, cls.calls, cls.runtime = probe(tmp, CHILD_PROBE, [{"text": "found it", "tool": True, "window": 990000}],
                                                config)
        cls.work = tmp

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_child_session_reads_the_learner_profiles_memory_and_skills(self):
        coding = self.calls[0]["args"]
        context = Path(option(coding, "--append-system-prompt-file")).read_text()
        self.assertIn("make kestrel", context)
        self.assertIn("Learning proposals", context)
        skills = Path(option(coding, "--plugin-dir")) / "skills"
        self.assertEqual(sorted(path.name for path in skills.iterdir()), ["repo-build"])
        self.assertEqual(option(coding, "--disallowedTools"), "Agent")

    def test_child_session_follows_the_pstack_mode_and_checks_it_every_turn(self):
        coding = self.calls[0]["args"]
        self.assertIn(MODE_POINTER, Path(option(coding, "--append-system-prompt-file")).read_text())
        self.assertIn("[pstack-mode turn check]", turn_context(coding))

    def test_child_profile_knows_the_context_window_its_runs_report(self):
        self.assertEqual(self.out["window"], 990000)

    def test_child_session_runs_no_review(self):
        self.assertIn("runs no review", self.out["review"]["error"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([row["purpose"] for row in rows(self.runtime)], ["coding"])

    def test_child_session_never_runs_astra(self):
        self.assertIn("Astra", self.out["astra"]["error"])

    def test_child_session_hook_refuses_profile_writes_and_learner_threads(self):
        for name, (event, code) in GUARD_EVENTS.items():
            text = json.dumps(event).replace("{learner}", str(self.learner)).replace("{work}", str(self.work))
            result = guard(self.calls[0]["args"], json.loads(text))
            self.assertEqual(result.returncode, code, f"{name}: {result.stderr}")
            if code:
                self.assertIn("Refused in a coder session", result.stderr, name)


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
name = args[2] if args[:1] == ["profile"] else args[1]
profile = home / ".hermes/profiles" / name
store = home / f"{{name}}-config.json"
config = json.loads(store.read_text()) if store.exists() else {{}}
if args[:2] == ["profile", "show"]:
    sys.exit(0 if profile.is_dir() else 1)
elif args[:2] == ["profile", "create"]:
    profile.mkdir(parents=True)
elif args[2:4] == ["config", "get"]:
    if args[4] not in config:
        sys.exit("Config key not set: " + args[4])
    print(json.dumps(config[args[4]]))
elif args[2:4] == ["config", "set"]:
    config[args[4]] = args[5]
    store.write_text(json.dumps(config))
elif args[2:4] == ["plugins", "enable"]:
    pass
elif args[2:4] == ["claude-code", "reload"]:
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
        retired = {"id": "hermes-coder-child", "displayName": "Hermes Coder (child)", "command": "hermes", "args": []}
        (self.home / "bb-provider-acp.json").write_text(json.dumps({"customAgents": json.dumps([OTHER_AGENT, retired])}))
        self.env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(self.home),
                    "XDG_STATE_HOME": str(self.home / "state"), "BB_CLI": str(bin_dir / "bb")}
        self.pstack = self.home / "workspaces/pstack-mode"
        (self.pstack / "plugins/pstack-mode").mkdir(parents=True)
        (self.pstack / "plugins/pstack-mode/mode.md").write_text("# Pstack session mode\n")
        subprocess.run(["git", "init", "-q", str(self.pstack)], check=True)

    def install(self, *args):
        return subprocess.run([sys.executable, "-I", str(SETUP), *args], env=self.env, capture_output=True, text=True)

    def config(self, profile="coder"):
        return json.loads((self.home / f"{profile}-config.json").read_text())

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
        launcher = self.home / ".hermes/profiles/coder/coder_acp.py"
        self.assertEqual(agents[1]["command"], str(launcher))
        self.assertEqual(agents[1]["args"], ["acp-hermes-coder", "coder", "coder-child"])
        self.assertEqual(launcher.read_bytes(), LAUNCHER.read_bytes())
        self.assertTrue(os.access(launcher, os.X_OK))

        config = self.config() | {"model.default": "gpt-6-luna"}
        (self.home / "coder-config.json").write_text(json.dumps(config))
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.config()["model.default"], "gpt-6-luna")

    def test_child_profile_reads_coder_and_turns_review_off(self):
        self.assertEqual(self.install().returncode, 0)
        child, coder = self.config("coder-child"), self.config("coder")
        self.assertEqual(child["auxiliary.background_review.enabled"], "false")
        self.assertEqual(child["claude_code_runtime.learner_home"], str(self.home / ".hermes/profiles/coder"))
        self.assertEqual(child["model.default"], "sonnet")
        self.assertNotIn("claude_code_runtime.learner_home", coder)
        self.assertNotIn("auxiliary.background_review.enabled", coder)
        for config in (child, coder):
            self.assertEqual(config["claude_code_runtime.subagent_provider"], "acp-hermes-coder")
            self.assertEqual(config["claude_code_runtime.pstack_root"], str(self.pstack.resolve() / "plugins/pstack-mode"))

    def test_install_stops_without_a_pstack_mode_checkout(self):
        shutil.rmtree(self.pstack)
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / "hermes-calls.jsonl").exists())

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


FAKE_THREAD_BB = f"""#!{sys.executable}
import json, os, sys
threads = json.loads(os.environ["FAKE_THREADS"])
if sys.argv[1:3] != ["thread", "show"] or sys.argv[3] not in threads:
    sys.exit("no such thread")
print(json.dumps({{"thread": threads[sys.argv[3]]}}))
"""

FAKE_ACP_HERMES = f"""#!{sys.executable}
import json, sys
print(json.dumps(sys.argv[1:]))
"""


class CoderLauncherTests(unittest.TestCase):
    THREADS = {
        "thr_top": {"parentThreadId": None, "providerId": "acp-hermes-coder"},
        "thr_sub": {"parentThreadId": "thr_top", "providerId": "acp-hermes-coder"},
        "thr_worker": {"parentThreadId": "thr_operator", "providerId": "acp-hermes-coder"},
        "thr_operator": {"parentThreadId": None, "providerId": "acp-hermes-agent"},
        "thr_relay": {"parentThreadId": "thr_operator", "lifecycleOwnerThreadId": "thr_sub",
                      "providerId": "acp-hermes-coder"},
    }

    def launch(self, thread=None):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            for name, script in {"bb": FAKE_THREAD_BB, "hermes": FAKE_ACP_HERMES}.items():
                (bin_dir / name).write_text(script)
                (bin_dir / name).chmod(0o755)
            env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_THREADS": json.dumps(self.THREADS)}
            if thread:
                env["BB_THREAD_ID"] = thread
            return subprocess.run([sys.executable, "-I", str(LAUNCHER), "acp-hermes-coder", "coder", "coder-child"],
                                  env=env, capture_output=True, text=True)

    def profile(self, thread=None):
        result = self.launch(thread)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(result.stdout)
        self.assertEqual(args[0], "-p")
        self.assertEqual(args[2:], ["acp"])
        return args[1]

    def test_a_thread_that_a_coder_thread_started_runs_the_child_profile(self):
        self.assertEqual(self.profile("thr_sub"), "coder-child")

    def test_a_relay_worker_that_a_coder_thread_started_runs_the_child_profile(self):
        self.assertEqual(self.profile("thr_relay"), "coder-child")

    def test_a_top_level_thread_or_another_agents_worker_runs_the_learner_profile(self):
        self.assertEqual(self.profile("thr_top"), "coder")
        self.assertEqual(self.profile("thr_worker"), "coder")

    def test_a_session_without_a_thread_lists_models_on_the_learner_profile(self):
        self.assertEqual(self.profile(), "coder")

    def test_a_thread_bb_cannot_read_does_not_start(self):
        result = self.launch("thr_missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("profile is unknown", result.stderr)

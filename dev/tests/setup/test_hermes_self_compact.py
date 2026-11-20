import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "setup/hermes/plugins/self-compact/__init__.py"
CLAUDE_HOOK = ROOT / "plugins/ramtoshiya-cc/hooks/context-budget.py"
WINDOW = 300_000
FAKE_HELPER = r"""
import fs from 'node:fs';
import path from 'node:path';
const [action, note, ...rest] = process.argv.slice(2);
if (action === 'prepare') {
  if (fs.existsSync(path.join(process.cwd(), '..', 'refuse-prepare'))) {
    process.stderr.write('New work or a different turn appeared before compaction.');
    process.exit(1);
  }
  process.stdout.write(JSON.stringify({ launchSeq: 7, turnId: 'turn_caller' }));
  process.exit(0);
}
const dir = process.cwd();
fs.writeFileSync(path.join(dir, 'args.json'), JSON.stringify({ action, note, rest,
  thread: process.env.BB_THREAD_ID, project: process.env.BB_PROJECT_ID ?? null }));
const finish = () => {
  if (fs.existsSync(path.join(dir, 'hold'))) return setTimeout(finish, 20);
  const outcome = path.join(dir, '..', 'outcome.json');
  const answer = fs.existsSync(outcome) ? JSON.parse(fs.readFileSync(outcome, 'utf8'))
    : { stdout: { compacted: true, resumeSent: true }, code: 0 };
  process.stdout.write(JSON.stringify(answer.stdout));
  if (answer.stderr) process.stderr.write(answer.stderr);
  process.exitCode = answer.code;
};
finish();
"""


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakePluginContext:
    def __init__(self, data_dir):
        self.state = types.SimpleNamespace(data_dir=data_dir)
        self.tools, self.hooks = {}, {}

    def register_tool(self, name, toolset, schema, handler, **_):
        self.tools[name] = (toolset, schema, handler)

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_middleware(self, kind, callback):
        self.hooks[kind] = callback


class FakeSessionDB:
    def __init__(self):
        self.rows, self.parents = {}, {}

    def get_messages(self, session_id, include_compacted=False, include_ancestors=False, limit=None):
        lineage = [session_id]
        while include_ancestors and lineage[0] in self.parents:
            lineage.insert(0, self.parents[lineage[0]])
        rows = [row for session in lineage for row in self.rows.get(session, [])
                if include_compacted or row.get("active", True)]
        return rows[:limit]


class SelfCompactPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.home = self.temp / "profiles/operator"
        self.threads = {"sess_a": "thr_a", "sess_b": "thr_b"}
        self.config = {"compression": {"threshold_tokens": WINDOW}}
        self.store = FakeSessionDB()
        modules = {
            "hermes_state_registry": types.SimpleNamespace(
                acquire=lambda path: self.store if path == self.home / "state.db" else None, release=lambda db: None),
            "hermes_cli": types.ModuleType("hermes_cli"),
            "hermes_cli.plugins_session_env": types.SimpleNamespace(
                resolve_session_env=lambda session: {"BB_THREAD_ID": self.threads.get(session)}),
            "hermes_cli.config": types.SimpleNamespace(load_config_readonly=lambda: self.config),
            "hermes_constants": types.SimpleNamespace(get_hermes_home=lambda: self.home),
        }
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.plugin = load("self_compact_plugin", PLUGIN)
        self.ctx = FakePluginContext(self.home / "plugin-data/self-compact")
        self.plugin.register(self.ctx)
        self.data = self.home / "plugin-data/self-compact"
        helper = self.home / "skills/self-compact/scripts/bb-compact.mjs"
        helper.parent.mkdir(parents=True)
        helper.write_text(FAKE_HELPER)

    def request(self, session, tokens, turn=""):
        self.ctx.hooks["post_api_request"](session_id=session, usage={"total_tokens": tokens}, turn_id=turn)

    def turn_start(self, session, turn=""):
        answer = self.ctx.hooks["pre_llm_call"](session_id=session, turn_id=turn)
        return answer["context"] if answer else None

    def tool_result(self, session, tool, result="output", turn=""):
        return self.ctx.hooks["transform_tool_result"](tool_name=tool, result=result, session_id=session, turn_id=turn)

    def llm_request(self, session, request, turn=""):
        answer = self.ctx.hooks["llm_request"](request=request, original_request=request, session_id=session,
                                               turn_id=turn, api_request_id="req")
        return answer["request"] if answer else None

    def compaction(self, session, kind="summarize", reason="manual", old=""):
        self.ctx.hooks["post_compaction"](session_id=session, old_session_id=old, kind=kind, reason=reason,
                                          before_tokens=250_000, after_tokens=20_000, messages_removed=40)

    def tool(self, session, **args):
        return json.loads(self.ctx.tools["self_compact"][2](args, session_id=session, conversation_id="conv",
                                                            task_id="task"))

    def launch(self, thread="thr_a"):
        return self.data / "launches" / thread

    def wait_for_exit(self, thread="thr_a"):
        deadline = time.time() + 10
        while not (self.launch(thread) / "exit").exists():
            self.assertLess(time.time(), deadline, "the helper did not finish")
            time.sleep(0.02)

    def test_bands_start_at_75_percent_and_step_by_five_points(self):
        cases = {224_999: None, 225_000: 75, 239_999: 75, 240_000: 80, 254_999: 80, 255_000: 85,
                 281_000: 90, 299_999: 95, 300_000: 100, 330_000: 110}
        for tokens, expected in cases.items():
            self.assertEqual(self.plugin.band(tokens, WINDOW), expected, tokens)

    def test_rising_usage_gets_the_same_reminders_as_the_claude_hook(self):
        claude = load("claude_context_budget", CLAUDE_HOOK)
        sweep = sorted({*range(200_000, 320_001, 2_500), 224_999, 225_000, 239_999, 240_000, 281_000})
        config = self.temp / "claude"
        config.mkdir()
        (config / "settings.json").write_text(json.dumps({"autoCompactWindow": WINDOW}))
        transcript = self.temp / "transcript.jsonl"
        env = {"CLAUDE_CONFIG_DIR": str(config), "XDG_STATE_HOME": str(self.temp / "state")}
        claude_notices, hermes_notices = [], []
        with mock.patch.dict(os.environ, env):
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            for tokens in sweep:
                transcript.write_text(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": tokens}}}))
                text = claude.suggestion({"session_id": "s", "transcript_path": str(transcript), "cwd": ""})
                if text:
                    claude_notices.append((tokens, text.split(" of the ")[0]))
                self.request("sess_a", tokens)
                if text := self.turn_start("sess_a"):
                    hermes_notices.append((tokens, text.removeprefix(self.plugin.PREFIX).split(" of the ")[0]))
        self.assertEqual(hermes_notices, claude_notices)
        self.assertEqual([tokens for tokens, _ in hermes_notices], [225_000, 240_000, 255_000, 270_000, 285_000, 300_000, 315_000])
        self.assertEqual(hermes_notices[0][1], "Context budget: about 75%")

    def test_one_reminder_per_band_until_a_summarizing_compaction(self):
        self.request("sess_a", 230_000)
        self.assertIn("about 76%", self.turn_start("sess_a"))
        self.request("sess_a", 236_000)
        self.request("sess_a", 200_000)
        self.request("sess_a", 231_000)
        self.assertIsNone(self.turn_start("sess_a"))
        self.compaction("sess_a", kind="prune_tool_results", reason="pre_api")
        self.request("sess_a", 232_000)
        self.assertIsNone(self.turn_start("sess_a"), "pruning keeps the band")
        self.compaction("sess_a")
        self.request("sess_a", 228_000)
        self.assertIn("about 76%", self.turn_start("sess_a"))

    def test_an_over_budget_session_gets_one_reminder_for_its_current_band(self):
        self.request("sess_a", 281_000)
        text = self.turn_start("sess_a")
        self.assertIn("about 93%", text)
        self.assertEqual(text.count("Context budget"), 1)
        self.assertEqual(json.loads((self.data / "sessions/sess_a.json").read_text())["band"], 90)

    def test_no_window_means_no_reminder(self):
        self.config = {"compression": {"threshold_tokens": None}}
        self.request("sess_a", 290_000)
        self.assertIsNone(self.turn_start("sess_a"))

    def test_reminders_ride_only_on_trusted_tool_results_and_stay_separate_per_session(self):
        self.request("sess_a", 250_000)
        for untrusted in ("mcp_bb_bridge_thread_show", "web_search", "browser_click", "unknown_tool"):
            self.assertIsNone(self.tool_result("sess_a", untrusted))
        self.assertIsNone(self.tool_result("sess_b", "terminal"))
        carried = self.tool_result("sess_a", "terminal", "ls output")
        self.assertTrue(carried.startswith(self.plugin.PREFIX + "Context budget: about 83%"))
        self.assertTrue(carried.endswith("\n\nls output"))
        self.assertIsNone(self.tool_result("sess_a", "terminal"))
        self.assertIsNone(self.turn_start("sess_a"))

    def test_an_external_only_loop_sees_the_reminder_on_each_request_until_a_turn_stores_it(self):
        wrapped = '<untrusted_tool_result source="web_search">\nresults\n</untrusted_tool_result>'
        request = {"model": "m", "input": [{"type": "message", "role": "user", "content": "task"},
                                           {"type": "function_call", "call_id": "c1", "name": "web_search", "arguments": "{}"},
                                           {"type": "function_call_output", "call_id": "c1", "output": wrapped}]}
        self.assertIsNone(self.turn_start("sess_a", turn="t1"))
        self.assertIsNone(self.llm_request("sess_a", request, turn="t1"))
        self.request("sess_a", 250_000, turn="t1")
        self.assertIsNone(self.tool_result("sess_a", "web_search", wrapped, turn="t1"))
        for _ in range(2):
            sent = self.llm_request("sess_a", request, turn="t1")
            self.assertEqual(sent["input"][:3], request["input"], "the tool result and its wrapper stay as they were")
            self.assertEqual(sent["input"][3]["role"], "user")
            self.assertTrue(sent["input"][3]["content"][0]["text"].startswith(self.plugin.PREFIX + "Context budget: about 83%"))
        self.assertIsNone(self.llm_request("sess_a", request, turn="fork"))
        self.assertIn("about 83%", self.turn_start("sess_a", turn="t2"))
        self.assertIsNone(self.llm_request("sess_a", request, turn="t2"))
        self.request("sess_a", 256_000, turn="t2")
        self.assertIn("about 85%", self.tool_result("sess_a", "terminal", turn="t2"))
        self.assertIsNone(self.llm_request("sess_a", request, turn="t2"))

    def test_the_reminder_follows_the_last_message_of_chat_and_anthropic_requests(self):
        self.request("sess_a", 250_000)
        chat = {"messages": [{"role": "user", "content": "task"}, {"role": "tool", "tool_call_id": "c1", "content": "x"}]}
        sent = self.llm_request("sess_a", chat)
        self.assertEqual(sent["messages"][:2], chat["messages"])
        self.assertEqual(sent["messages"][2]["role"], "user")
        self.assertIn("about 83%", sent["messages"][2]["content"])
        block = {"type": "tool_result", "tool_use_id": "c1", "content": "x"}
        anthropic = {"messages": [{"role": "user", "content": [block]}]}
        sent = self.llm_request("sess_a", anthropic)
        self.assertEqual(sent["messages"][0]["content"][0], block)
        self.assertEqual(sent["messages"][0]["content"][1]["type"], "text")
        self.assertIsNone(self.llm_request("sess_a", {"contents": []}))

    def test_a_review_fork_sharing_the_session_neither_raises_the_band_nor_takes_notices(self):
        self.assertIsNone(self.turn_start("sess_a", turn="t1"))
        self.request("sess_a", 230_000, turn="t1")
        self.assertIn("about 76%", self.tool_result("sess_a", "terminal", turn="t1"))
        self.request("sess_a", 239_000, turn="t1")
        # Hermes's background review fork reuses the session id, skips pre_llm_call, and has its own turn id.
        self.request("sess_a", 242_000, turn="fork")
        self.assertIsNone(self.tool_result("sess_a", "skill_view", turn="fork"))
        self.assertIsNone(self.turn_start("sess_a", turn="t2"))
        self.request("sess_a", 243_000, turn="t2")
        self.assertIn("about 81%", self.tool_result("sess_a", "terminal", turn="t2"))

    def test_compact_saves_the_note_and_runs_the_helper_for_the_calling_thread(self):
        self.request("sess_a", 250_000)
        with mock.patch.dict(os.environ, {"BB_THREAD_ID": "thr_gateway", "BB_PROJECT_ID": "proj_other"}):
            answer = self.tool("sess_a", action="compact", note="# Handoff\nNext: step 3.")
        self.assertEqual(answer["status"], "scheduled", answer)
        self.assertTrue(answer["resume"])
        note = Path(answer["note"])
        self.assertEqual(note, self.data / "notes/thr_a.md")
        self.assertEqual(note.read_text(), "# Handoff\nNext: step 3.")
        self.assertEqual(note.stat().st_mode & 0o777, 0o600)
        self.wait_for_exit()
        args = json.loads((self.launch() / "args.json").read_text())
        self.assertEqual(args, {"action": "run", "note": str(note), "thread": "thr_a", "project": None, "rest": [
            "--launch-seq", "7", "--turn-id", "turn_caller", "--compaction-ledger", str(self.launch() / "ledger.jsonl")]})
        self.assertEqual(self.plugin.launch_result(self.launch())["state"], "succeeded")
        self.assertIsNone(self.turn_start("sess_a"), "scheduling drops the pending reminder")

    def test_no_resume_reaches_the_helper(self):
        self.assertEqual(self.tool("sess_a", action="compact", note="n", resume=False)["status"], "scheduled")
        self.wait_for_exit()
        self.assertEqual(json.loads((self.launch() / "args.json").read_text())["rest"][-1], "--no-resume")

    def test_a_running_helper_gets_the_ledger_and_blocks_a_second_launch_and_clear(self):
        (self.data / "launches/thr_a").mkdir(parents=True)
        (self.launch() / "hold").touch()
        self.assertEqual(self.tool("sess_a", action="compact", note="first")["status"], "scheduled")
        second = self.tool("sess_a", action="compact", note="second")
        self.assertEqual(second["status"], "error")
        self.assertIn("already scheduled", second["error"])
        self.assertIn("in progress", self.tool("sess_a", action="clear")["error"])
        self.assertEqual((self.data / "notes/thr_a.md").read_text(), "first")
        self.compaction("sess_b")
        self.compaction("sess_a2", old="sess_a")
        self.assertIsNone(self.turn_start("sess_a2"), "the helper's resume points to the note")
        (self.launch() / "hold").unlink()
        self.wait_for_exit()
        lines = (self.launch() / "ledger.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual((entry["sessionId"], entry["oldSessionId"], entry["kind"], entry["reason"]),
                         ("sess_a2", "sess_a", "summarize", "manual"))
        self.compaction("sess_a2")
        self.assertEqual(len((self.launch() / "ledger.jsonl").read_text().splitlines()), 1)
        self.assertIn("handoff note exists", self.turn_start("sess_a2"), "a later compaction has no resume")

    def test_a_failure_the_helper_did_not_report_reaches_the_agent_once(self):
        (self.data / "launches").mkdir(parents=True)
        (self.data / "launches/outcome.json").write_text(json.dumps({"code": 1, "stdout": {
            "compacted": "unknown", "phase": "compact-requested", "failureNoticeSent": False,
            "error": "BB reported compaction, but Hermes committed none."}}))
        self.tool("sess_a", action="compact", note="keep me", resume=False)
        self.wait_for_exit()
        text = self.turn_start("sess_a")
        self.assertIn("Self-compaction did not complete: BB reported compaction, but Hermes committed none.", text)
        self.assertIn("handoff note is kept", text)
        self.assertIsNone(self.turn_start("sess_a"))
        self.assertEqual(self.tool("sess_a", action="read")["text"], "keep me")

    def test_a_failure_the_helper_reported_is_not_repeated(self):
        (self.data / "launches").mkdir(parents=True)
        (self.data / "launches/outcome.json").write_text(json.dumps({"code": 1, "stdout": {
            "compacted": False, "failureNoticeSent": True, "error": "The caller turn failed."}}))
        self.tool("sess_a", action="compact", note="n")
        self.wait_for_exit()
        self.assertIsNone(self.tool_result("sess_a", "terminal"))
        self.assertEqual(self.tool("sess_a", action="read")["helper"]["state"], "failed")

    def test_a_lost_helper_blocks_compaction_until_clear(self):
        directory = self.launch()
        directory.mkdir(parents=True)
        (directory / "claim.json").write_text(json.dumps({"sessionId": "sess_a", "resume": True}))
        dead = subprocess.Popen(["true"])
        dead.wait()
        (directory / "pid").write_text(str(dead.pid))
        refused = self.tool("sess_a", action="compact", note="n")
        self.assertIn("unknown", refused["error"])
        self.assertIn("compact is refused until you call the clear action", self.turn_start("sess_a"))
        self.assertEqual(self.tool("sess_a", action="clear"), {"status": "cleared"})
        self.assertEqual(self.tool("sess_a", action="compact", note="n")["status"], "scheduled")
        self.wait_for_exit()

    def test_a_refused_preparation_keeps_the_note_and_no_launch(self):
        (self.data / "launches").mkdir(parents=True)
        (self.data / "launches/refuse-prepare").touch()
        answer = self.tool("sess_a", action="compact", note="still here")
        self.assertEqual(answer["status"], "error")
        self.assertIn("New work or a different turn appeared", answer["error"])
        self.assertIn("note is saved", answer["next"])
        self.assertEqual((self.data / "notes/thr_a.md").read_text(), "still here")
        self.assertFalse(self.launch().exists())

    def test_a_session_without_a_thread_cannot_compact(self):
        answer = self.tool("sess_cli", action="compact", note="n")
        self.assertIn("No bb thread", answer["error"])
        self.assertFalse((self.data / "notes").exists())

    def test_notes_are_per_thread_and_per_profile(self):
        self.tool("sess_a", action="compact", note="a", resume=False)
        self.wait_for_exit()
        self.assertEqual(self.tool("sess_b", action="read")["status"], "none")
        self.ctx.state.data_dir = self.temp / "profiles/other/plugin-data/self-compact"
        self.assertEqual(self.tool("sess_a", action="read")["status"], "none")

    def test_after_a_compaction_without_a_resume_the_next_turn_points_to_the_note(self):
        self.tool("sess_a", action="compact", note="n", resume=False)
        self.wait_for_exit()
        self.compaction("sess_a2", reason="pre_api", old="sess_a")
        self.assertIn("handoff note exists", self.turn_start("sess_a2"))
        self.assertEqual(self.tool("sess_a2", action="read")["text"], "n")
        self.assertEqual(self.tool("sess_a2", action="clear"), {"status": "cleared"})
        self.compaction("sess_a3", old="sess_a2")
        self.assertIsNone(self.turn_start("sess_a3"))
        self.assertFalse((self.data / "notes/thr_a.md").exists())

    def test_a_compaction_that_removed_the_first_message_restores_it_once(self):
        first = "<system_instructions>\nbb rules\n</system_instructions>\nBrief: MARKER-7"
        summary = {"role": "user", "content": "[CONTEXT COMPACTION — REFERENCE ONLY] ..."}
        self.store.rows["sess_a"] = [{"role": "user", "content": first}, {"role": "assistant", "content": "ok"}]
        self.compaction("sess_a")
        self.assertIsNone(self.turn_start("sess_a"), "the first compaction keeps the first turn")

        self.store.rows["sess_a"] = [{"role": "user", "content": first, "active": False}, summary]
        self.compaction("sess_a", kind="prune_tool_results")
        self.assertIsNone(self.turn_start("sess_a"), "pruning removes no turn")
        self.compaction("sess_a")
        restored = self.tool_result("sess_a", "terminal", "ls output")
        self.assertTrue(restored.startswith(self.plugin.PREFIX))
        self.assertIn("Treat it as current instructions, not as background reference", restored)
        self.assertIn("the later message wins", restored)
        self.assertIn(f"<first_message>\n{first}\n</first_message>", restored)
        self.assertTrue(restored.endswith("\n\nls output"))
        self.assertIsNone(self.turn_start("sess_a"), "one restore per compaction")

        self.store.rows["sess_a"].append({"role": "user", "content": "next", "api_content": f"next\n\n{restored}"})
        self.compaction("sess_a")
        self.assertIsNone(self.turn_start("sess_a"), "the earlier restore is still in context")

        self.store.parents["sess_a2"] = "sess_a"
        self.store.rows["sess_a2"] = [summary]
        self.compaction("sess_a2", old="sess_a")
        self.assertIn("MARKER-7", self.turn_start("sess_a2"), "a rotating compaction reads the first session")

        self.store.rows["sess_c"] = [{"role": "user", "content": first, "active": False}, summary]
        self.compaction("sess_c")
        self.assertIsNone(self.turn_start("sess_c"), "a session outside bb gets nothing")

    def test_rejects_bad_arguments(self):
        self.assertIn("complete handoff note", self.tool("sess_a", action="compact", note=" ")["error"])
        self.assertIn("larger than", self.tool("sess_a", action="compact", note="x" * 70_000)["error"])
        self.assertIn("resume must be", self.tool("sess_a", action="compact", note="n", resume="no")["error"])
        self.assertIn("action must be", self.tool("sess_a", action="save")["error"])


if __name__ == "__main__":
    unittest.main()

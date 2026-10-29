import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "setup/agents/claudex-lean/skill/scripts/agent_deck.py"

# Controlled CLI responses exercise the adapter process, not a live Agent Deck.
FAKE = r'''#!INTERPRETER
import json, os, pathlib, shlex, subprocess, sys, time
p = pathlib.Path(os.environ["XDG_STATE_HOME"])
a = sys.argv[1:]
with (p / "calls").open("a") as f: f.write(json.dumps(a[:3]) + "\n")
mode = (p / "mode").read_text()
repo = (p / "repo").read_text()
if a[0] == "add":
    worker = str(p / "worker")
    branch = a[a.index("--worktree") + 1]
    subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", worker, branch], capture_output=True, check=True)
    (p / "title").write_text(a[a.index("-t") + 1])
    (p / "received").write_text(json.dumps({"command":shlex.split(a[a.index("-c") + 1]), "trust":"--trust-folder" in a,
        "env":{k:os.environ.get(k) for k in ("MULTICA_TASK_TOKEN", "CLAUDE_CODE_MESSAGING_TOKEN", "ANTHROPIC_API_KEY")}}))
    if mode == "slow-add":
        (p / "add-ready").touch()
        time.sleep(1)
    print(json.dumps({"success":True,"id":"owned","path":worker}))
elif a[:2] == ["session", "start"]:
    (p / "stopped-owned").unlink(missing_ok=True)
    print("started")
elif a[:2] == ["session", "switch-settle"]:
    print(json.dumps({"success":True,"settle":{"ready":mode != "startup-blocked"}}))
elif a[:2] == ["session", "show"]:
    print(json.dumps({"id":"owned","title":(p / "title").read_text(),"path":str(p / "worker"),"claude_session_id":"conversation-1" if mode != "identity-change" else "other"}))
elif a[:2] == ["session", "send"]:
    if "--wait" not in a:
        print(json.dumps({"success":True,"session_id":"owned","verdict":"queued"}))
        sys.exit(0)
    if mode == "slow-send": time.sleep(6)
    if mode == "budget-reply":
        budget = float(a[a.index("--timeout") + 1].removesuffix("s"))
        time.sleep(min(4.5, budget))
        if budget < 4.5: sys.exit(7)
    if mode == "timeout": time.sleep(10)
    if mode == "dirty": (p / "worker" / "change").write_text("dirty")
    if mode == "new-commit": subprocess.run(["git","-C",str(p / "worker"),"-c","user.name=Test","-c","user.email=test@example.invalid","commit","--allow-empty","-qm","change"],check=True)
    counter = p / "turn-count"
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    turn = "turn-1" if mode == "stale-turn" else "turn-" + str(count)
    data = {"success":True,"session_id":"owned","completion":"complete","content":"Work unit finished.","claude_session_id":"conversation-1","claude_turn_uuid":turn}
    if mode == "queued": data = {"success":True,"session_id":"owned","verdict":"queued"}
    if mode == "busy": data.update(verified=False,wait_outcome="unverified_busy_target")
    if mode == "uncorrelated": data.update(verified=False,wait_outcome="observed_not_correlated")
    if mode == "stale": data["session_id"] = "other"
    if mode == "no-turn": data.pop("claude_turn_uuid")
    if mode == "long-reply": data["content"] = "x" * 20000
    if mode == "partial": print("Warning: response may be incomplete",file=sys.stderr)
    print(json.dumps(data))
elif a[0] == "list":
    rows = [{"id":"owned","title":(p / "title").read_text() if (p / "title").exists() else "none"},{"id":"child","parent_session_id":"owned"},{"id":"unrelated"}]
    if (p / "late-child").exists(): rows.append({"id":"late","parent_session_id":"owned"})
    print(json.dumps(rows))
elif a[:3] == ["session", "ownership", "inspect"]:
    stopped = (p / ("stopped-" + a[3])).exists()
    print(json.dumps({"leader":{} if stopped else {"pid":os.getppid() if mode == "daemon-collision" else 900000001},"members":[],"survivors":[],"pane_attached":not stopped}))
elif a[:2] == ["session", "stop"]:
    if mode == "stop-fails": sys.exit(7)
    (p / ("stopped-" + a[2])).touch()
    if mode == "late-child" and a[2] == "owned": (p / "late-child").touch()
    print("stopped")
else: sys.exit(8)
'''


class AdapterBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "base"], check=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        deck = self.bin / "agent-deck"
        deck.write_text(FAKE.replace("INTERPRETER", sys.executable))
        deck.chmod(0o700)
        tmux = self.bin / "tmux"
        tmux.write_text("#!/bin/sh\nexit 0\n")
        tmux.chmod(0o700)
        multica = self.bin / "multica"
        multica.write_text(f"#!{sys.executable}\nimport os,json\nprint(json.dumps({{'pid':os.getppid()}}))\n")
        multica.chmod(0o700)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        (self.state / "repo").write_text(str(self.repo))
        self.records = self.root / "run with spaces"
        self.records.mkdir(mode=0o700)
        self.prompt = self.root / "prompt"
        self.prompt.write_text("Inspect the scoped fixture.")
        self.config = self.root / "config.json"
        value = {"agent_deck":str(deck), "profile":"test", "worker_command":["worker-cli", "--add-dir", "{run_dir}/results folder"], "tmux_path":str(self.bin), "tmux_socket":"test-socket"}
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMUX_TMPDIR"):
            value[key] = str(self.state)
        self.config.write_text(json.dumps(value))
        self.config.chmod(0o600)
        self.common = [sys.executable, "-I", str(SCRIPT), "--config", str(self.config), "--run-dir", str(self.records)]
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"], MULTICA_TASK_TOKEN="fixture", CLAUDE_CODE_MESSAGING_TOKEN="fixture", ANTHROPIC_API_KEY="provider-fixture")

    def call(self, mode, *args):
        (self.state / "mode").write_text(mode)
        return subprocess.run(self.common + list(args), env=self.env, capture_output=True, text=True, timeout=25)

    def fresh(self, mode="complete", extra=()):
        return self.call(mode, "--repo", str(self.repo), "--prompt", str(self.prompt), "--max-seconds", "5", *extra)

    def calls(self):
        return [json.loads(row) for row in (self.state / "calls").read_text().splitlines()]

    def test_correlated_reply_and_owned_cleanup(self):
        result = self.fresh()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads((self.records / "run.json").read_text())
        self.assertEqual(record["outcome"], "replied")
        self.assertEqual(record["reply"], "Work unit finished.")
        self.assertEqual(record["cleanup"], "stopped")
        self.assertEqual([row[2] for row in self.calls() if row[:2] == ["session", "stop"]], ["child", "owned"])
        received = json.loads((self.state / "received").read_text())
        self.assertEqual(received["command"], ["worker-cli", "--add-dir", str(self.records / "results folder")])
        self.assertFalse(received["trust"])
        self.assertEqual(received["env"], {"MULTICA_TASK_TOKEN":None,"CLAUDE_CODE_MESSAGING_TOKEN":None,"ANTHROPIC_API_KEY":"provider-fixture"})

    def test_incomplete_or_uncorrelated_replies_do_not_count_as_completion(self):
        for mode in ("queued", "busy", "uncorrelated", "stale", "no-turn", "partial"):
            with self.subTest(mode=mode):
                self.setUp()
                result = self.fresh(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotEqual(json.loads((self.records / "run.json").read_text())["outcome"], "replied")

    def test_resume_reuses_session_and_worktree(self):
        first = self.fresh("dirty")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = self.calls()
        self.prompt.write_text("Continue the existing work without repeating the first task.")
        result = self.call("complete", "--resume", "--prompt", str(self.prompt), "--max-seconds", "5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        later = self.calls()[len(before):]
        self.assertFalse(any(row[0] == "add" for row in later))
        self.assertTrue(any(row[:2] == ["session", "start"] for row in later))
        self.assertEqual(json.loads((self.records / "run.json").read_text())["worktree"], str(self.state / "worker"))
        self.assertEqual((self.state / "worker" / "change").read_text(), "dirty")
        self.assertTrue(json.loads((self.records / "run.json").read_text())["git"]["dirty"])

    def test_ambiguous_send_cannot_resume_without_explicit_reconciliation(self):
        first = self.fresh("busy")
        self.assertNotEqual(first.returncode, 0)
        before = self.calls()
        result = self.call("complete", "--resume", "--prompt", str(self.prompt), "--max-seconds", "5")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(row[:2] == ["session", "send"] for row in self.calls()[len(before):]))
        self.prompt.write_text("Prior send was reconciled. Continue with the next step only.")
        result = self.call("complete", "--resume", "--ack-ambiguous", "--prompt", str(self.prompt), "--max-seconds", "5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(row[0] == "add" for row in self.calls()[len(before):]))

    def test_candidate_pin_rejects_dirty_and_changed_review(self):
        base = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        result = self.fresh("new-commit", ("--candidate", base))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate", json.loads((self.records / "run.json").read_text())["error"])

    def test_long_native_reply_is_bounded_without_discarding_the_turn(self):
        result = self.fresh("long-reply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = json.loads((self.records / "run.json").read_text())
        self.assertEqual(record["outcome"], "replied")
        self.assertTrue(record["reply_truncated"])
        self.assertLess(len(record["reply"].encode()), 17000)
        self.assertEqual(record["last_turn_id"], "turn-1")

    def test_candidate_pin_survives_resume(self):
        base = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(self.fresh(extra=("--candidate", base)).returncode, 0)
        self.prompt.write_text("Continue the read-only review at the same pinned candidate.")
        result = self.call("new-commit", "--resume", "--prompt", str(self.prompt), "--max-seconds", "5")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("candidate", json.loads((self.records / "run.json").read_text())["error"])

    def test_native_reply_can_use_the_remaining_unit_budget(self):
        result = self.call("budget-reply", "--repo", str(self.repo), "--prompt", str(self.prompt), "--max-seconds", "8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((self.records / "run.json").read_text())["outcome"], "replied")

    def test_resume_rejects_a_stale_prior_turn(self):
        self.assertEqual(self.fresh().returncode, 0)
        self.prompt.write_text("A new continuation, not the first request.")
        result = self.call("stale-turn", "--resume", "--prompt", str(self.prompt), "--max-seconds", "5")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("previous turn", json.loads((self.records / "run.json").read_text())["error"])

    def test_resume_rejects_changed_native_conversation(self):
        self.assertEqual(self.fresh().returncode, 0)
        self.prompt.write_text("Continue with the next scoped step.")
        before = len(self.calls())
        result = self.call("identity-change", "--resume", "--prompt", str(self.prompt), "--max-seconds", "5")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity changed", result.stderr)
        self.assertFalse(any(row[:2] == ["session", "start"] for row in self.calls()[before:]))

    def test_timeout_preserves_work_and_requires_reconciliation(self):
        result = self.fresh("timeout")
        self.assertNotEqual(result.returncode, 0)
        record = json.loads((self.records / "run.json").read_text())
        self.assertEqual(record["send_state"], "ambiguous")
        self.assertEqual(record["cleanup"], "stopped")
        self.assertTrue((self.state / "worker").exists())

    def test_candidate_pin_rejects_dirty_review(self):
        base = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        result = self.fresh("dirty", ("--candidate", base))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate", json.loads((self.records / "run.json").read_text())["error"])
        self.assertTrue((self.state / "worker" / "change").exists())

    def test_linked_source_uses_its_candidate_not_main_head(self):
        linked = self.root / "linked"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-b", "feature", str(linked)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(linked), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "feature candidate"], check=True)
        expected = subprocess.check_output(["git", "-C", str(linked), "rev-parse", "HEAD"], text=True).strip()
        result = self.call("complete", "--repo", str(linked), "--prompt", str(self.prompt), "--max-seconds", "5")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((self.records / "run.json").read_text())["git"]["head"], expected)
        self.assertNotEqual(subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip(), expected)

    def test_dirty_source_is_preserved_without_blocking_a_separate_worktree(self):
        original = self.repo / "existing-user-file"
        original.write_text("preserve")
        result = self.fresh()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(original.read_text(), "preserve")
        self.assertFalse(json.loads((self.records / "run.json").read_text())["git"]["dirty"])

    def test_unrecognized_startup_never_sends_work(self):
        config = json.loads(self.config.read_text())
        config["trust_folder"] = True
        self.config.write_text(json.dumps(config))
        result = self.fresh("startup-blocked")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(row[:2] == ["session", "send"] for row in self.calls()))
        self.assertEqual(json.loads((self.records / "run.json").read_text())["cleanup"], "stopped")

    def test_late_child_and_cleanup_recovery(self):
        result = self.fresh("late-child")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.state / "stopped-late").exists())

    def test_daemon_collision_never_stops_session(self):
        result = self.fresh("daemon-collision")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Multica daemon", json.loads((self.records / "run.json").read_text())["cleanup"])
        self.assertFalse(any(row[:2] == ["session", "stop"] for row in self.calls()))

    def test_cleanup_only_does_not_relaunch(self):
        self.assertNotEqual(self.fresh("stop-fails").returncode, 0)
        before = len(self.calls())
        result = self.call("complete", "--cleanup-only")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(any(row[0] == "add" or row[:2] == ["session", "start"] for row in self.calls()[before:]))
        self.prompt.write_text("Cleanup is now reconciled. Continue the preserved implementation.")
        resumed = self.call("complete", "--resume", "--prompt", str(self.prompt), "--max-seconds", "5")
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertFalse(any(row[0] == "add" for row in self.calls()[before:]))

    def test_cancel_during_send_marks_ambiguous_and_stops_worker(self):
        elapsed = self.cancel_when("slow-send", ["session", "send"])
        self.assertLess(elapsed, 5, "cancellation waited for the native reply timeout")
        state = json.loads((self.records / "run.json").read_text())
        self.assertEqual(state["send_state"], "ambiguous")
        self.assertEqual(state["cleanup"], "stopped")

    def test_cancel_during_add_never_starts_worker(self):
        self.cancel_when("slow-add", ["add"])
        self.assertFalse(any(row[:2] == ["session", "start"] for row in self.calls()))

    def cancel_when(self, mode, prefix):
        (self.state / "mode").write_text(mode)
        command = self.common + ["--repo", str(self.repo), "--prompt", str(self.prompt), "--max-seconds", "20"]
        process = subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            # Finish the fixture's Git child before interrupting the delayed add response.
            while time.monotonic() < deadline:
                ready = mode != "slow-add" or (self.state / "add-ready").exists()
                if ready and (self.state / "calls").exists() and any(row[:len(prefix)] == prefix for row in self.calls()): break
                time.sleep(0.02)
            else: self.fail("add did not start")
            started = time.monotonic()
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=15)
            self.assertNotEqual(process.returncode, 0)
            return time.monotonic() - started
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


if __name__ == "__main__":
    unittest.main()

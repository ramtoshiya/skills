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

# This executable supplies transport outcomes, not an Agent Deck implementation.
FAKE_DECK = r'''#!INTERPRETER
import json, os, pathlib, re, shlex, subprocess, sys, time
p = pathlib.Path(os.environ["XDG_STATE_HOME"])
a = sys.argv[1:]
with (p / "calls").open("a") as f: f.write(json.dumps(a[:3]) + "\n")
mode = (p / "mode").read_text()
repo = (p / "repo").read_text()
if a[0] == "add":
    worktree = str(p / "worker")
    branch = a[a.index("--worktree") + 1]
    if "-b" in a: subprocess.run(["git", "-C", repo, "branch", branch, "HEAD"], capture_output=True, check=True)
    subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", worktree, branch], capture_output=True, check=True)
    (p / "title").write_text(a[a.index("-t") + 1])
    (p / "received").write_text(json.dumps({"command": shlex.split(a[a.index("-c") + 1]), "trust": "--trust-folder" in a,
        "env": {key: os.environ.get(key) for key in ("MULTICA_TASK_TOKEN", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ID", "ANTHROPIC_API_KEY")}}))
    if mode == "slow-add": time.sleep(1)
    print(json.dumps({"success": True, "id": "owned", "path": worktree}))
elif a[:2] == ["session", "start"]:
    print("started")
elif a[:2] == ["session", "switch-settle"]:
    print(json.dumps({"success": True, "settle": {"ready": mode != "startup-blocked"}}))
elif a[:2] == ["session", "send"]:
    if "--defer-if-busy" not in a or "--defer-timeout" not in a: sys.exit(9)
    if mode != "missing":
        path = re.search(r"object to (.*?) with exactly", a[3]).group(1)
        worker = str(p / "worker")
        if mode == "dirty": pathlib.Path(worker, "uncommitted.txt").write_text("change")
        if mode == "new-commit":
            subprocess.run(["git", "-C", worker, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "worker"], check=True)
        candidate = subprocess.check_output(["git", "-C", worker, "rev-parse", "HEAD"], text=True).strip()
        if mode == "bad-candidate": candidate = "0" * 40
        if mode in ("no-candidate", "blocked"): candidate = None
        pathlib.Path(path).write_text(json.dumps({"status":"blocked" if mode == "blocked" else "completed", "summary":"Worker finished.", "candidate":candidate, "worktree":worker}))
    print(json.dumps({"state":"queued", "send_id":"send-1"}))
elif a[0] == "list":
    rows = [{"id":"owned", "title":(p / "title").read_text() if (p / "title").exists() else "none"}, {"id":"child", "parent_session_id":"owned"}, {"id":"unrelated"}]
    if (p / "late-child").exists(): rows.append({"id":"late", "parent_session_id":"owned"})
    print(json.dumps(rows))
elif a[:3] == ["session", "ownership", "inspect"]:
    stopped = (p / ("stopped-" + a[3])).exists()
    print(json.dumps({"leader":{} if stopped else {"pid":os.getppid() if mode == "daemon-collision" else 900000001}, "members":[], "survivors":[], "pane_attached":not stopped}))
elif a[:2] == ["session", "stop"]:
    if mode == "stop-fails": sys.exit(7)
    (p / ("stopped-" + a[2])).touch()
    if mode == "late-child" and a[2] == "owned": (p / "late-child").touch()
    if mode == "late-dirty" and a[2] == "owned": pathlib.Path(p / "worker" / "late.txt").write_text("late")
    print("stopped")
else:
    sys.exit(8)
'''


class AdapterBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "base"], check=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        deck = self.bin / "agent-deck"
        deck.write_text(FAKE_DECK.replace("INTERPRETER", sys.executable))
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
        prompt = self.root / "prompt"
        prompt.write_text("Inspect the scoped fixture.")
        self.config = self.root / "config.json"
        value = {"agent_deck": str(deck), "profile": "test", "worker_command": ["worker-cli", "--add-dir", "{run_dir}/results folder"],
                 "tmux_path": str(self.bin), "tmux_socket": "test-socket"}
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMUX_TMPDIR"):
            value[key] = str(self.state)
        self.config.write_text(json.dumps(value))
        self.config.chmod(0o600)
        self.command = [sys.executable, "-I", str(SCRIPT), "--config", str(self.config), "--repo", str(self.repo),
                        "--prompt", str(prompt), "--run-dir", str(self.records), "--role", "builder", "--max-seconds", "5"]
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        MULTICA_TASK_TOKEN="fixture", CLAUDE_CODE_MESSAGING_TOKEN="fixture",
                        CLAUDE_CODE_SESSION_ID="fixture", ANTHROPIC_API_KEY="fixture-provider")

    def invoke(self, mode):
        (self.state / "mode").write_text(mode)
        return subprocess.run(self.command, env=self.env, capture_output=True, text=True, timeout=15)

    def calls(self):
        return [json.loads(line) for line in (self.state / "calls").read_text().splitlines()]

    def test_completion_requires_artifact_and_stops_only_owned_tree(self):
        result = self.invoke("completed")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads((self.records / "run.json").read_text())
        self.assertEqual(state["outcome"], "completed")
        self.assertEqual(state["candidate"], subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip())
        stops = [call[2] for call in self.calls() if call[:2] == ["session", "stop"]]
        self.assertEqual(stops, ["child", "owned"])
        received = json.loads((self.state / "received").read_text())
        self.assertEqual(received["command"], ["worker-cli", "--add-dir", str(self.records / "results folder")])
        self.assertFalse(received["trust"])
        self.assertEqual(received["env"], {"MULTICA_TASK_TOKEN": None, "CLAUDE_CODE_MESSAGING_TOKEN": None,
                                            "CLAUDE_CODE_SESSION_ID": None, "ANTHROPIC_API_KEY": "fixture-provider"})

    def test_queued_send_without_completion_times_out_and_cleans_up(self):
        result = self.invoke("missing")
        self.assertEqual(result.returncode, 1, result.stderr)
        state = json.loads((self.records / "run.json").read_text())
        self.assertEqual(state["outcome"], "timeout")
        self.assertEqual(state["cleanup"], "stopped")

    def test_invalid_candidate_and_cleanup_failure_are_not_success(self):
        result = self.invoke("bad-candidate")
        self.assertEqual(result.returncode, 1, result.stderr)
        state = json.loads((self.records / "run.json").read_text())
        self.assertIn("candidate does not match", state["error"])
        self.assertEqual(state["cleanup"], "stopped")

    def test_cleanup_failure_is_exposed(self):
        result = self.invoke("stop-fails")
        self.assertEqual(result.returncode, 1, result.stderr)
        state = json.loads((self.records / "run.json").read_text())
        self.assertIn("unresolved", state["cleanup"])

    def test_daemon_identity_collision_never_stops_session(self):
        result = self.invoke("daemon-collision")
        self.assertEqual(result.returncode, 1)
        state = json.loads((self.records / "run.json").read_text())
        self.assertIn("Multica daemon", state["cleanup"])
        self.assertFalse(any(call[:2] == ["session", "stop"] for call in self.calls()))

    def test_cleanup_only_recovers_without_starting_new_work(self):
        first = self.invoke("stop-fails")
        self.assertEqual(first.returncode, 1)
        (self.state / "mode").write_text("completed")
        before = len(self.calls())
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--config", str(self.config),
                                 "--run-dir", str(self.records), "--cleanup-only"],
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()[before:]
        self.assertFalse(any(call[0] == "add" or call[:2] == ["session", "start"] for call in calls))
        self.assertEqual([call[2] for call in calls if call[:2] == ["session", "stop"]], ["child", "owned"])
        self.assertEqual(json.loads((self.records / "run.json").read_text())["cleanup"], "stopped")

    def test_completed_builder_requires_candidate_and_clean_worktree(self):
        result = self.invoke("dirty")
        self.assertEqual(result.returncode, 1)
        self.assertIn("uncommitted", json.loads((self.records / "run.json").read_text())["error"])
        self.assertTrue((self.state / "worker" / "uncommitted.txt").exists())

    def test_completion_rechecked_after_worker_stop(self):
        result = self.invoke("late-dirty")
        self.assertEqual(result.returncode, 1)
        state = json.loads((self.records / "run.json").read_text())
        self.assertIn("changed after", state["error"])
        self.assertTrue((self.state / "worker" / "late.txt").exists())

    def test_completed_builder_requires_candidate(self):
        result = self.invoke("no-candidate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires a committed candidate", json.loads((self.records / "run.json").read_text())["error"])

    def test_blocked_result_can_omit_candidate(self):
        result = self.invoke("blocked")
        self.assertEqual(result.returncode, 1)
        state = json.loads((self.records / "run.json").read_text())
        self.assertEqual(state["outcome"], "blocked")
        self.assertIsNone(state["candidate"])

    def test_reviewer_accepts_only_unchanged_input_candidate(self):
        base = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.command[self.command.index("builder")] = "reviewer"
        self.command.extend(["--candidate", base])
        result = self.invoke("completed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.records / "run.json").read_text())["candidate"], base)

    def test_reviewer_rejects_modified_candidate(self):
        base = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.command[self.command.index("builder")] = "reviewer"
        self.command.extend(["--candidate", base])
        result = self.invoke("new-commit")
        self.assertEqual(result.returncode, 1)
        self.assertIn("reviewer changed", json.loads((self.records / "run.json").read_text())["error"])

    def test_dirty_source_does_not_block_clean_worker(self):
        (self.repo / "existing-user-file").write_text("preserve")
        result = self.invoke("completed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.repo / "existing-user-file").read_text(), "preserve")

    def test_linked_source_uses_its_candidate_not_main_head(self):
        linked = self.root / "linked"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-b", "feature", str(linked)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(linked), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "feature candidate"], check=True)
        expected = subprocess.check_output(["git", "-C", str(linked), "rev-parse", "HEAD"], text=True).strip()
        self.command[self.command.index("--repo") + 1] = str(linked)
        result = self.invoke("completed")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads((self.records / "run.json").read_text())["candidate"], expected)
        self.assertNotEqual(subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip(), expected)

    def test_unrecognized_startup_never_receives_product_work(self):
        value = json.loads(self.config.read_text())
        value["trust_folder"] = True
        self.config.write_text(json.dumps(value))
        result = self.invoke("startup-blocked")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(any(call[:2] == ["session", "send"] for call in self.calls()))
        self.assertEqual(json.loads((self.records / "run.json").read_text())["cleanup"], "stopped")

    def test_trust_folder_requires_explicit_opt_in(self):
        value = json.loads(self.config.read_text())
        value["trust_folder"] = True
        self.config.write_text(json.dumps(value))
        result = self.invoke("completed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads((self.state / "received").read_text())["trust"])

    def test_cleanup_collects_child_created_after_initial_snapshot(self):
        result = self.invoke("late-child")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.state / "stopped-late").exists())
        self.assertEqual(json.loads((self.records / "run.json").read_text())["cleanup"], "stopped")

    def test_cancellation_stops_owned_sessions(self):
        self.cancel_when(["session", "send"], "missing")

    def test_cancellation_during_add_never_starts_worker(self):
        self.cancel_when(["add"], "slow-add")
        self.assertFalse(any(call[:2] == ["session", "start"] for call in self.calls()))
        self.assertFalse(any(call[:2] == ["session", "send"] for call in self.calls()))

    def cancel_when(self, prefix, mode):
        (self.state / "mode").write_text(mode)
        command = self.command[:-1] + ["20"]
        process = subprocess.Popen(command, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if (self.state / "calls").exists() and any(call[:len(prefix)] == prefix for call in self.calls()):
                    break
                time.sleep(0.02)
            else:
                self.fail("send did not start")
            process.send_signal(signal.SIGTERM)
            _, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 1, stderr)
            state = json.loads((self.records / "run.json").read_text())
            self.assertEqual(state["outcome"], "cancelled")
            self.assertEqual(state["cleanup"], "stopped")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_missing_runtime_refuses_before_launch(self):
        self.config.unlink()
        result = self.invoke("missing")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.state / "calls").exists())


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "setup/agents/claudex-lean/skill/scripts/report.py"
spec = importlib.util.spec_from_file_location("lean_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class Mailbox:
    def __init__(self):
        self.rows = []
        self.sends = 0
        self.fail = None
        self.lookup_fails = False

    def send(self, issue, parent, body, directory):
        self.sends += 1
        if self.fail == "before":
            self.fail = None
            raise OSError("connection refused")
        row = {"id": str(uuid.uuid4()), "parent_id": parent, "content": body}
        self.rows.append(row)
        if self.fail == "after":
            self.fail = None
            raise subprocess.TimeoutExpired("multica", 20)
        return row["id"]

    def find(self, issue, parent, pending):
        if self.lookup_fails:
            raise OSError("lookup unavailable")
        return next((row["id"] for row in self.rows
                     if row["parent_id"] == parent and pending["marker"] in row["content"]), None)


class ReportingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.issue, self.parent = str(uuid.uuid4()), str(uuid.uuid4())
        self.status = self.root / "status.json"
        self.status.write_text(json.dumps({
            "observed_at": report.timestamp(0), "completed": "Fixture prepared.",
            "current": "Worker running.", "next": "Collect independent verification.", "blocker": "None.",
        }))
        self.journal = self.root / "report.json"
        binary = self.root / "bin"
        binary.mkdir()
        fake = binary / "multica"
        fake.write_text(f"#!{sys.executable}\n" + '''import json,os,pathlib,sys,uuid
args=sys.argv[1:]
if args[:2]==['daemon','status']:
    counter=pathlib.Path(os.environ['FAKE_DAEMON_COUNT'])
    count=int(counter.read_text())+1 if counter.exists() else 1
    counter.write_text(str(count))
    if count>int(os.environ.get('FAIL_DAEMON_AFTER','999')):
        raise SystemExit(1)
    print(json.dumps({'pid':os.getppid()}))
else:
    rows=pathlib.Path(os.environ['FAKE_ROWS'])
    values=json.loads(rows.read_text())
    if args[:3]==['issue','comment','list']:
        print(json.dumps(values))
    else:
        body=pathlib.Path(args[args.index('--content-file')+1]).read_text()
        row={'id':str(uuid.uuid4()),'parent_id':args[args.index('--parent')+1],'content':body}
        values.append(row)
        rows.write_text(json.dumps(values))
        print(json.dumps(row))
''')
        fake.chmod(0o700)
        self.rows = self.root / "rows.json"
        self.rows.write_text("[]")
        self.environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                                FAKE_ROWS=str(self.rows), FAKE_DAEMON_COUNT=str(self.root / "daemon-count"))
        self.mail = Mailbox()
        with patch.object(report.time, "time", return_value=0):
            self.reporter = report.Reporter(self.issue, self.parent, self.status, self.journal, self.mail)

    def tick(self, now):
        with patch.object(report.time, "time", return_value=now):
            self.reporter.tick()

    def test_due_time_and_status_updates_do_not_post_early_or_reset_clock(self):
        with patch.object(report.time, "time", return_value=100):
            self.reporter = report.Reporter(self.issue, self.parent, self.status, self.root / "late-start.json",
                                            self.mail, last_visible_at=report.timestamp(0))
        for now, expected in ((599, 0), (600, 1), (1199, 1), (1200, 2)):
            value = json.loads(self.status.read_text())
            value["observed_at"] = report.timestamp(now)
            self.status.write_text(json.dumps(value))
            self.tick(now)
            self.assertEqual(len(self.mail.rows), expected)
        self.assertEqual(self.reporter.state["delivered"], [row["id"] for row in self.mail.rows])

    def test_stale_and_missing_status_are_reported_without_claiming_success(self):
        self.tick(601)
        self.assertIn("Status stale since", self.mail.rows[0]["content"])
        self.status.unlink()
        self.tick(1201)
        body = self.mail.rows[1]["content"]
        self.assertIn("Current worker status is unavailable", body)
        self.assertIn("No new completion verified", body)

    def test_bracketed_status_progress_is_preserved_in_worklog(self):
        value = json.loads(self.status.read_text())
        value["observed_at"] = report.timestamp(600)
        value["current"] = "CTest [3/4] running"
        self.status.write_text(json.dumps(value))
        self.tick(600)
        body = self.mail.rows[0]["content"]
        self.assertIn(f"- Current activity: Observed at {value['observed_at']}. CTest [3/4] running", body)
        self.assertNotIn("Current worker status is unavailable", body)

    def test_status_cannot_enqueue_agents_through_a_mention(self):
        for index, scheme in enumerate(("mention://", "MeNtIoN://", "MENTION://"), start=1):
            with self.subTest(scheme=scheme):
                value = json.loads(self.status.read_text())
                value["observed_at"] = report.timestamp(600 * index)
                value["current"] = f"Ask [worker]({scheme}agent/{uuid.uuid4()}) to run."
                self.status.write_text(json.dumps(value))
                self.tick(600 * index)
                body = self.mail.rows[-1]["content"]
                self.assertNotIn("mention://", body.lower())
                self.assertIn("Current worker status is unavailable", body)

    def test_lost_send_response_is_reconciled_across_restart_without_duplicate(self):
        self.mail.fail = "after"
        self.tick(600)
        self.assertEqual(len(self.mail.rows), 1)
        self.assertEqual(self.reporter.state["last_success_at"], 0)
        self.assertIsNotNone(self.reporter.state["pending"])
        self.reporter = report.Reporter(self.issue, self.parent, self.status, self.journal, self.mail)
        self.tick(630)
        self.assertEqual(self.mail.sends, 1)
        self.assertEqual(self.reporter.state["delivered"], [self.mail.rows[0]["id"]])
        self.assertIsNone(self.reporter.state["pending"])

    def test_explicit_failure_retries_only_after_reconciliation_and_budget(self):
        self.mail.fail = "before"
        self.tick(600)
        self.tick(629)
        self.assertEqual(self.mail.sends, 1)
        self.tick(630)
        self.assertEqual(self.mail.sends, 2)
        self.assertEqual(len(self.mail.rows), 1)

    def test_failed_reconciliation_never_blindly_resends(self):
        self.mail.fail = "after"
        self.tick(600)
        self.mail.lookup_fails = True
        self.tick(630)
        self.tick(660)
        self.assertEqual(self.mail.sends, 1)
        state = json.loads(self.journal.read_text())
        self.assertEqual(state["last_success_at"], 0)
        self.assertIsNotNone(state["pending"])
        self.assertEqual(state["last_error"], "OSError")

    def test_journal_cannot_be_reused_for_another_thread(self):
        with self.assertRaisesRegex(ValueError, "another issue or thread"):
            report.Reporter(self.issue, str(uuid.uuid4()), self.status, self.journal, self.mail)

    def test_transport_requires_real_comment_id_and_scopes_reconciliation(self):
        client = report.Multica()
        pending = {"attempted_at": 600, "marker": "unique-marker"}
        identifier = str(uuid.uuid4())
        rows = [{"id": str(uuid.uuid4()), "parent_id": "other", "content": "unique-marker"},
                {"id": identifier, "parent_id": self.parent, "content": "unique-marker"}]
        with patch.object(client, "call", return_value=rows):
            self.assertEqual(client.find(self.issue, self.parent, pending), identifier)
        with patch.object(client, "call", return_value={"success": True}):
            with self.assertRaises(KeyError):
                client.send(self.issue, self.parent, "safe body", self.root)

    def command(self, records, *command, budget="10"):
        return [sys.executable, "-I", str(SCRIPT), "--issue", self.issue,
                "--parent", self.parent, "--status", str(self.status),
                "--records", str(records), "--last-visible-at", report.timestamp(time.time()),
                "--max-seconds", budget, "--", *command]

    def test_command_success_failure_and_no_worklog_after_short_completion(self):
        for exit_code in (0, 7):
            records = self.root / f"run-{exit_code}"
            result = subprocess.run(self.command(records, sys.executable, "-I", "-c", f"raise SystemExit({exit_code})"),
                                    capture_output=True, text=True, timeout=15, env=self.environment)
            self.assertEqual(result.returncode, exit_code, result.stderr)
            evidence = json.loads((records / "result.json").read_text())
            self.assertEqual(evidence["exit_code"], exit_code)
            self.assertEqual(evidence["comment_ids"], [])
            self.assertFalse(evidence["reporting_unresolved"])

    def test_timeout_and_cancel_reap_owned_child_without_killing_unrelated_process(self):
        environment = self.environment
        unrelated = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"], start_new_session=True)
        def cleanup_unrelated():
            if unrelated.poll() is None:
                unrelated.terminate()
            unrelated.wait(timeout=5)

        self.addCleanup(cleanup_unrelated)
        for cancelled in (False, True):
            records = self.root / f"stop-{cancelled}"
            process = subprocess.Popen(self.command(records, sys.executable, "-I", "-c", "import time; time.sleep(30)",
                                                    budget="10" if cancelled else "0.1"),
                                       env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if cancelled:
                deadline = time.monotonic() + 5
                while not (records / "process.json").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 1, stderr)
            outcome = json.loads((records / "result.json").read_text())
            self.assertEqual(outcome["reason"], "cancelled" if cancelled else "timeout")
            pid = json.loads((records / "process.json").read_text())["pid"]
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
            self.assertIsNone(unrelated.poll())
        unrelated.terminate()
        unrelated.wait(timeout=5)

    def test_unresolved_terminal_delivery_recovers_without_starting_work(self):
        self.mail.fail = "after"
        self.tick(600)
        self.rows.write_text(json.dumps(self.mail.rows))
        command_marker = self.root / "command-started"
        command = self.command(self.root, sys.executable, "-I", "-c",
                               f"from pathlib import Path; Path({str(command_marker)!r}).touch()")
        refused = subprocess.run(command, env=self.environment, capture_output=True, text=True, timeout=5)
        self.assertEqual(refused.returncode, 2)
        self.assertFalse(command_marker.exists())
        recover = [sys.executable, "-I", str(SCRIPT), "--issue", self.issue, "--parent", self.parent,
                   "--records", str(self.root), "--reconcile-only"]
        result = subprocess.run(recover, env=self.environment, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(self.journal.read_text())
        self.assertEqual(state["delivered"], [self.mail.rows[0]["id"]])
        self.assertIsNone(state["pending"])
        self.assertEqual(len(json.loads(self.rows.read_text())), 1)
        self.assertFalse((self.root / "process.json").exists())

    def test_daemon_lookup_failure_cannot_launch_or_orphan_command(self):
        for fail_after in (0, 1):
            records = self.root / f"daemon-failure-{fail_after}"
            environment = dict(self.environment, FAIL_DAEMON_AFTER=str(fail_after),
                               FAKE_DAEMON_COUNT=str(self.root / f"count-{fail_after}"))
            result = subprocess.run(self.command(records, sys.executable, "-I", "-c", "import time; time.sleep(30)", budget="0.1"),
                                    env=environment, capture_output=True, text=True, timeout=10)
            if fail_after == 0:
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse((records / "process.json").exists())
            else:
                self.assertEqual(result.returncode, 1, result.stderr)
                pid = json.loads((records / "process.json").read_text())["pid"]
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
                outcome = json.loads((records / "result.json").read_text())
                self.assertIn("used launch-time identity", outcome["cleanup_warning"])

    def test_concurrent_supervisor_cannot_claim_the_same_records(self):
        records = self.root / "claimed"
        records.mkdir(mode=0o700)
        with (records / "owner.lock").open("w") as lock:
            report.fcntl.flock(lock, report.fcntl.LOCK_EX | report.fcntl.LOCK_NB)
            result = subprocess.run(self.command(records, "/usr/bin/true"), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((records / "process.json").exists())


if __name__ == "__main__":
    unittest.main()

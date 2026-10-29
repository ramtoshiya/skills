"""Supervise an approved command and post timed, bounded Multica worklogs."""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

INTERVAL = 600
RETRY = 30


def timestamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def comment_id(value):
    identifier = value["id"]
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError("invalid comment ID")
    return identifier


class Multica:
    def call(self, *arguments):
        result = subprocess.run(
            ["multica", *arguments, "--output", "json"], capture_output=True,
            text=True, check=True, timeout=20,
        )
        return json.loads(result.stdout)

    def send(self, issue, parent, body, directory):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", dir=directory) as stream:
            stream.write(body)
            stream.flush()
            return comment_id(self.call(
                "issue", "comment", "add", issue, "--parent", parent,
                "--content-file", stream.name,
            ))

    def find(self, issue, parent, pending):
        rows = self.call(
            "issue", "comment", "list", issue, "--since",
            timestamp(pending["attempted_at"] - 1), "--compact",
        )
        matches = [row for row in rows if row.get("parent_id") == parent
                   and pending["marker"] in row.get("content", "")]
        if len(matches) > 1:
            raise ValueError("multiple comments match the pending worklog")
        return comment_id(matches[0]) if matches else None


def status_body(path, now):
    try:
        if path.stat().st_size > 8192:
            raise ValueError("status exceeds 8 KiB")
        value = json.loads(path.read_text())
        observed = datetime.fromisoformat(value["observed_at"])
        if observed.tzinfo is None:
            raise ValueError("status timestamp needs a timezone")
        age = now - observed.timestamp()
        if age < -60:
            raise ValueError("status timestamp is in the future")
        fields = {}
        for key in ("completed", "current", "next", "blocker"):
            text = value[key]
            if (not isinstance(text, str) or not text.strip() or len(text) > 500
                    or any(character in text for character in "<>") or "mention://" in text.lower()):
                raise ValueError("status needs four short plain-text fields without mention links")
            fields[key] = " ".join(text.split())
        if age > INTERVAL:
            fields["current"] = f"Status stale since {value['observed_at']}. {fields['current']}"
        else:
            fields["current"] = f"Observed at {value['observed_at']}. {fields['current']}"
    except (OSError, ValueError, KeyError, TypeError):
        fields = {
            "completed": "No new completion verified.",
            "current": "Current worker status is unavailable. Command completion is not yet observed.",
            "next": "Collect a fresh worker status and terminal result.",
            "blocker": "Unknown. Missing status is not evidence of success or a product blocker.",
        }
    return "\n".join(f"- {label}: {fields[key]}" for label, key in (
        ("Completed work", "completed"), ("Current activity", "current"),
        ("Next step", "next"), ("Blocker", "blocker"),
    ))


class Reporter:
    def __init__(self, issue, parent, status, journal, client=None, last_visible_at=None):
        self.issue, self.parent = str(uuid.UUID(issue)), str(uuid.UUID(parent))
        self.status, self.journal = Path(status), Path(journal)
        self.client = client or Multica()
        if self.journal.exists():
            self.state = json.loads(self.journal.read_text())
            if (self.state["issue"], self.state["parent"]) != (self.issue, self.parent):
                raise ValueError("journal belongs to another issue or thread")
        else:
            visible = time.time()
            if last_visible_at is not None:
                parsed = datetime.fromisoformat(last_visible_at)
                if parsed.tzinfo is None or parsed.timestamp() > visible:
                    raise ValueError("last visible response needs a non-future timezone-aware timestamp")
                visible = parsed.timestamp()
            self.state = {
                "issue": self.issue, "parent": self.parent, "run": str(uuid.uuid4()),
                "last_success_at": visible, "pending": None, "delivered": [],
                "last_error": None,
            }
            self.save()

    def save(self):
        atomic_json(self.journal, self.state)

    def reconcile_pending(self):
        if self.state["pending"] is not None:
            self.state["pending"]["retry_at"] = time.time()
            self.tick()

    def tick(self):
        now = time.time()
        pending = self.state["pending"]
        if pending and now < pending["retry_at"]:
            return
        if not pending:
            if now - self.state["last_success_at"] < INTERVAL:
                return
            marker = f"<!-- claudex-lean:{self.state['run']}:{len(self.state['delivered'])} -->"
            pending = {
                "marker": marker, "body": status_body(self.status, now) + "\n\n" + marker,
                "attempted_at": now, "retry_at": now, "attempts": 0,
            }
            self.state["pending"] = pending
        # Persist the attempt before sending so a lost response is reconciled first.
        previous_attempt = pending["attempts"] > 0
        pending["attempts"] += 1
        pending["retry_at"] = now + RETRY
        self.save()
        try:
            identifier = self.client.find(self.issue, self.parent, pending) if previous_attempt else None
            if identifier is None:
                identifier = self.client.send(self.issue, self.parent, pending["body"], Path.cwd())
            self.state["delivered"].append(identifier)
            self.state["pending"] = None
            self.state["last_error"] = None
            self.state["last_success_at"] = time.time()
            print(json.dumps({"comment_id": identifier, "confirmed_at": timestamp(time.time())}), flush=True)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            # Keep transport error details private, outside the posted worklog.
            self.state["last_error"] = type(error).__name__
            print(f"worklog delivery unresolved: {type(error).__name__}", file=sys.stderr, flush=True)
        self.save()


def daemon_identity():
    daemon_pid = int(Multica().call("daemon", "status")["pid"])
    return daemon_pid, os.getpgid(daemon_pid)


def terminate_group(process, initial_daemon):
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        process.wait()
        return None
    identities = [initial_daemon]
    warning = None
    try:
        identities.append(daemon_identity())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        warning = f"daemon refresh failed ({type(error).__name__}), used launch-time identity"
        print(warning, file=sys.stderr, flush=True)
    if any(process.pid in identity for identity in identities):
        raise RuntimeError("refusing to terminate the Multica daemon process group")
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    # The leader can exit before its descendants. Reap the owned group as well.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return warning


def supervise(arguments):
    records = arguments.records.resolve()
    records.mkdir(parents=True, exist_ok=True, mode=0o700)
    if records.stat().st_mode & 0o077:
        raise ValueError("records directory must be private (mode 0700)")
    with (records / "owner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = records / "report.json"
        if arguments.reconcile_only and not journal.exists():
            raise ValueError("no delivery journal to reconcile")
        reporter = Reporter(arguments.issue, arguments.parent, arguments.status or records / "status.json", journal,
                            last_visible_at=arguments.last_visible_at)
        if arguments.reconcile_only:
            reporter.reconcile_pending()
            unresolved = reporter.state["pending"] is not None
            print(json.dumps({"reporting_unresolved": unresolved, "comment_ids": reporter.state["delivered"]}), flush=True)
            return 3 if unresolved else 0
        if reporter.state["pending"] is not None:
            raise ValueError("resolve pending delivery with --reconcile-only before starting another command")
        # No command starts unless the daemon identity can be checked first.
        initial_daemon = daemon_identity()
        stopped = False

        def stop(signum, frame):
            nonlocal stopped
            stopped = True

        old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        process = None
        started = time.monotonic()
        reason = "completed"
        cleanup_warning = None
        try:
            with (records / "command.stdout").open("ab") as stdout, (records / "command.stderr").open("ab") as stderr:
                process = subprocess.Popen(arguments.command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
                atomic_json(records / "process.json", {"pid": process.pid, "started_at": timestamp(time.time())})
                while process.poll() is None:
                    if stopped or time.monotonic() - started >= arguments.max_seconds:
                        reason = "cancelled" if stopped else "timeout"
                        break
                    reporter.tick()
                    time.sleep(0.5)
        finally:
            try:
                if process is not None:
                    cleanup_warning = terminate_group(process, initial_daemon)
            finally:
                for sig, handler in old_handlers.items():
                    signal.signal(sig, handler)
        code = process.returncode
        unresolved = reporter.state["pending"] is not None
        result = {"reason": reason, "exit_code": code, "reporting_unresolved": unresolved,
                  "cleanup_warning": cleanup_warning, "comment_ids": reporter.state["delivered"]}
        atomic_json(records / "result.json", result)
        print(json.dumps(result), flush=True)
        return 3 if unresolved else (code if code and code > 0 else (0 if reason == "completed" and code == 0 else 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--last-visible-at")
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--reconcile-only", action="store_true")
    parser.add_argument("--max-seconds", type=float, default=3600)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if arguments.command[:1] == ["--"]:
        arguments.command = arguments.command[1:]
    if arguments.reconcile_only and arguments.command:
        parser.error("reconciliation never starts a command")
    if not arguments.reconcile_only and (not arguments.command or arguments.status is None
                                         or arguments.last_visible_at is None or arguments.max_seconds <= 0):
        parser.error("provide status, last visible response time, a command and a positive lifetime budget")
    try:
        return supervise(arguments)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"report supervisor failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

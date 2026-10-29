"""Run one bounded Agent Deck work unit using an operator-provisioned profile."""

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import uuid


class AdapterError(Exception):
    pass


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        name = Path(stream.name)
        try:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            name.unlink(missing_ok=True)


def private(path, directory=False):
    if path.is_symlink() or not (path.is_dir() if directory else path.is_file()):
        raise AdapterError(f"missing private {'directory' if directory else 'file'}: {path}")
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise AdapterError(f"private path must be owned by the current user and not group/world accessible: {path}")


def read_json(path, limit):
    if path.is_symlink() or path.stat().st_size > limit:
        raise AdapterError(f"invalid or oversized JSON: {path}")
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise AdapterError("expected a JSON object")
    return value


class Deck:
    def __init__(self, config):
        private(config)
        value = read_json(config, 16384)
        self.binary = value["agent_deck"]
        self.profile = value["profile"]
        command = value["worker_command"]
        if (not isinstance(self.binary, str) or not Path(self.binary).is_absolute()
                or not os.access(self.binary, os.X_OK) or not isinstance(self.profile, str)
                or not self.profile or not isinstance(command, list) or not command
                or any(not isinstance(arg, str) or not arg for arg in command)):
            raise AdapterError("invalid Agent Deck executable, profile or worker command")
        self.command = command
        self.failure_path = None
        self.trust_folder = value.get("trust_folder", False)
        if not isinstance(self.trust_folder, bool):
            raise AdapterError("trust_folder must be a boolean")
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith(("AGENTDECK_", "MULTICA_", "CLAUDE_CODE_MESSAGING_",
                               "CLAUDE_CODE_SESSION_", "CLAUDE_CODE_CHILD_",
                               "CLAUDE_CODE_PARENT_", "CLAUDE_CODE_AGENT_")) or key in (
                    "TMUX", "TMUX_PANE", "CLAUDECODE", "CLAUDE_PID",
                    "CLAUDE_SESSION_ID", "CLAUDE_AGENT_ID"):
                self.env.pop(key, None)
        for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "TMUX_TMPDIR"):
            path = Path(value[key])
            if not path.is_absolute():
                raise AdapterError(f"{key} must be absolute")
            private(path, directory=True)
            self.env[key] = str(path)
        tmux_path = value["tmux_path"]
        if not isinstance(tmux_path, str) or not Path(tmux_path).is_absolute() or not os.access(Path(tmux_path) / "tmux", os.X_OK):
            raise AdapterError("tmux_path must contain an executable tmux")
        self.env.update(PATH=tmux_path + os.pathsep + os.environ.get("PATH", ""),
                        AGENTDECK_PROFILE=self.profile, AGENTDECK_SKIP_UPDATE_CHECK="1")
        self.socket = value["tmux_socket"]
        if not isinstance(self.socket, str) or not self.socket or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in self.socket):
            raise AdapterError("invalid isolated tmux socket name")

    def call(self, *args, timeout=30, json_output=True):
        command = [self.binary, *args]
        if json_output:
            command.append("--json")
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=timeout)
        self.last_stderr = result.stderr
        if result.returncode:
            if self.failure_path is not None:
                write_json(self.failure_path, {"operation": list(args[:3]),
                           "exit": result.returncode, "stdout": result.stdout[-8192:],
                           "stderr": result.stderr[-8192:]})
            raise AdapterError(f"Agent Deck {' '.join(args[:3])} failed (exit {result.returncode})")
        if json_output:
            return json.loads(result.stdout)
        return result.stdout

    def owned(self, root):
        rows = self.call("list")
        if not isinstance(rows, list):
            raise AdapterError("invalid Agent Deck session list")
        by_parent = {}
        for row in rows:
            parent = row.get("parent_session_id")
            if parent:
                by_parent.setdefault(parent, []).append(row["id"])
        result = []
        seen = set()

        def visit(identifier):
            if identifier in seen:
                raise AdapterError("cyclic Agent Deck ownership graph")
            seen.add(identifier)
            for child in by_parent.get(identifier, []):
                visit(child)
            result.append(identifier)
        visit(root)
        return result

    def stop_owned(self, root):
        for attempt in range(4):
            before = self.owned(root)
            for identifier in before:
                self.stop_one(identifier)
            after = self.owned(root)
            if set(after) <= set(before):
                for identifier in after:
                    info = self.call("session", "ownership", "inspect", identifier)
                    if (info.get("pane_attached") or info.get("survivors")
                            or (info.get("leader") or {}).get("pid") or info.get("members")):
                        raise AdapterError(f"owned session revived during cleanup: {identifier}")
                return
        raise AdapterError("owned session graph kept growing during cleanup")

    def stop_one(self, identifier):
        daemon = subprocess.run(["multica", "daemon", "status", "--output", "json"],
                                capture_output=True, text=True, check=True, timeout=20)
        daemon_pid = int(json.loads(daemon.stdout)["pid"])
        info = self.call("session", "ownership", "inspect", identifier)
        identities = [info.get("leader") or {}, *(info.get("members") or [])]
        if any(item.get("pid") == daemon_pid or item.get("pgid") == os.getpgid(daemon_pid) for item in identities):
            raise AdapterError("refusing to stop a session containing the Multica daemon")
        if (not info.get("pane_attached") and not info.get("survivors")
                and not any(item.get("pid") for item in identities)):
            return
        self.call("session", "stop", identifier, json_output=False)
        after = self.call("session", "ownership", "inspect", identifier)
        if after.get("pane_attached") or after.get("survivors"):
            raise AdapterError(f"owned session still has live processes: {identifier}")


def git_facts(repo):
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD^{commit}"],
                          capture_output=True, text=True, check=True, timeout=20).stdout.strip()
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                            capture_output=True, text=True, check=True, timeout=20).stdout
    return {"head": head, "dirty": bool(status), "status_digest": hashlib.sha256(status.encode()).hexdigest()}


def checked_worktree(record):
    worktree = Path(record["worktree"]).resolve(strict=True)
    facts = git_facts(worktree)
    subprocess.run(["git", "-C", str(worktree), "merge-base", "--is-ancestor", record["base"], facts["head"]],
                   capture_output=True, check=True, timeout=20)
    candidate = record.get("expected_candidate")
    if candidate and (facts["head"] != candidate or facts["dirty"]):
        raise AdapterError("candidate changed or worktree is dirty")
    return facts


def run(args):
    config = Path(args.config).absolute()
    prompt = Path(args.prompt).resolve(strict=True)
    records = Path(args.run_dir).absolute()
    private(records, directory=True)
    journal = records / "run.json"
    if not args.resume and journal.exists():
        raise AdapterError("run directory already contains a workstream")
    if args.resume and not journal.exists():
        raise AdapterError("no workstream to resume")
    if prompt.stat().st_size > 65536:
        raise AdapterError("prompt exceeds 64 KiB")
    text = prompt.read_text(encoding="utf-8")
    if not text.strip():
        raise AdapterError("prompt is empty")
    deck = Deck(config)
    deck.failure_path = records / "control-error.json"
    if args.resume:
        private(journal)
        record = read_json(journal, 32768)
        if (record.get("profile"), record.get("socket")) != (deck.profile, deck.socket):
            raise AdapterError("workstream belongs to another profile or socket")
        run_id = record["run"]
        if uuid.UUID(hex=run_id).hex != run_id or record.get("title") != "lean-" + run_id:
            raise AdapterError("invalid workstream identity")
        if record.get("cleanup") != "stopped":
            raise AdapterError("cleanup is unresolved; reconcile it before resuming")
        if record.get("send_state") != "replied" and not args.ack_ambiguous:
            raise AdapterError("previous send is unresolved; reconcile it before explicitly acknowledging ambiguity")
        if not record.get("native_session_id") or not record.get("session_id"):
            raise AdapterError("native conversation identity is unavailable")
        if record.get("prompt_digest") == hashlib.sha256(text.encode()).hexdigest():
            raise AdapterError("resume requires a new continuation prompt")
        repo = Path(record["worktree"]).resolve(strict=True)
        base = record["base"]
        title = record["title"]
        show = deck.call("session", "show", record["session_id"])
        if (show.get("id") != record["session_id"] or show.get("title") != title
                or Path(show.get("path", "")).resolve() != repo
                or show.get("claude_session_id") != record["native_session_id"]):
            raise AdapterError("native session, conversation, or worktree identity changed")
        current = checked_worktree(record)
        if current != record.get("git"):
            raise AdapterError("worktree Git state changed since the prior unit")
    else:
        repo = Path(args.repo).resolve(strict=True)
        base = git_facts(repo)["head"]
        if args.candidate and args.candidate != base:
            raise AdapterError("expected candidate must be the full input repository HEAD")
        run_id = uuid.uuid4().hex
        title = "lean-" + run_id
        record = {"run": run_id, "base": base, "expected_candidate": args.candidate, "session_id": None,
                  "title": title, "profile": deck.profile, "socket": deck.socket,
                  "worktree": None, "outcome": "starting", "cleanup": "pending",
                  "send_state": "not_sent", "native_session_id": None}
        write_json(journal, record)
    stopped = False
    cleaning = False

    def cancel(signum, frame):
        nonlocal stopped
        if not stopped:
            stopped = True
            if not cleaning:
                raise AdapterError("cancelled during native operation")

    handlers = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    deadline = time.monotonic() + args.max_seconds

    def active():
        if stopped or time.monotonic() >= deadline:
            raise AdapterError("cancelled or timed out before dispatch")

    try:
        active()
        if not args.resume:
            command = shlex.join([arg.replace("{run_dir}", str(records)) for arg in deck.command])
            # Pin linked checkouts before Agent Deck resolves the main repository.
            subprocess.run(["git", "-C", str(repo), "branch", title, base],
                           capture_output=True, text=True, check=True, timeout=20)
            active()
            options = ["add", str(repo), "-c", command, "-t", title, "--title-lock", "--no-parent",
                       "--tmux-socket", deck.socket, "--worktree", title]
            if deck.trust_folder:
                options.append("--trust-folder")
            created = deck.call(*options)
            if not isinstance(created, dict) or not created.get("success") or not created.get("id"):
                raise AdapterError("Agent Deck did not return a session ID")
            record["session_id"] = created["id"]
            record["worktree"] = created.get("path")
            write_json(journal, record)
            active()
            worktree = Path(record["worktree"]).resolve(strict=True)
            if git_facts(worktree)["head"] != base:
                raise AdapterError("created worktree does not start at input HEAD")
        else:
            worktree = repo
        active()
        record["cleanup"] = "pending"
        record["outcome"] = "starting"
        record.pop("error", None)
        record.pop("reply", None)
        record.pop("reply_truncated", None)
        write_json(journal, record)
        deck.call("session", "start", record["session_id"], json_output=False)
        active()
        if deck.trust_folder:
            settled = deck.call("session", "switch-settle", record["session_id"],
                                "--no-kick", "--timeout", "40s", timeout=50)
            if not settled.get("success") or not settled.get("settle", {}).get("ready"):
                raise AdapterError("worker startup did not become ready")
        active()
        show = deck.call("session", "show", record["session_id"])
        native_id = show.get("claude_session_id")
        if (show.get("id") != record["session_id"] or show.get("title") != title
                or Path(show.get("path", "")).resolve() != worktree or not native_id):
            raise AdapterError("native session or conversation identity is unavailable")
        if args.resume and native_id != record["native_session_id"]:
            raise AdapterError("restarted session changed its native conversation")
        record["native_session_id"] = native_id
        active()
        record["send_state"] = "ambiguous"
        record["prompt_digest"] = hashlib.sha256(text.encode()).hexdigest()
        record["outcome"] = "waiting"
        record.pop("reply", None)
        write_json(journal, record)
        remaining = max(1, math.ceil(deadline - time.monotonic()))
        result = deck.call("session", "send", record["session_id"], text, "--wait",
                           "--timeout", f"{remaining}s", "--defer-if-busy",
                           "--defer-timeout", f"{remaining}s", timeout=max(1, deadline - time.monotonic()))
        stderr = deck.last_stderr
        if not isinstance(result, dict):
            raise AdapterError("native response is not a JSON object")
        fields = ("success", "session_id", "completion", "content", "muted", "verified",
                  "wait_outcome", "claude_session_id", "claude_turn_uuid")
        saved = {key: (value[:16384] if isinstance(value, str) else value)
                 for key, value in result.items() if key in fields and isinstance(value, (str, bool))}
        write_json(records / "native-response.json", {"response": saved, "stderr": stderr[-8192:]})
        active()
        if (not isinstance(result, dict) or result.get("success") is not True
                or result.get("session_id") != record["session_id"]
                or result.get("completion") != "complete" or result.get("muted")
                or result.get("verified") is False or result.get("wait_outcome")
                or "response may be incomplete" in stderr.lower()):
            raise AdapterError("native response is incomplete or uncorrelated")
        reply = result.get("content")
        if not isinstance(reply, str) or not reply.strip():
            raise AdapterError("native reply is missing")
        if len(reply.encode()) > 16384:
            reply = reply.encode()[:16384].decode(errors="ignore") + "\n[Truncated. Inspect native session output for the full reply.]"
            record["reply_truncated"] = True
        native_id = result.get("claude_session_id")
        if not native_id or not result.get("claude_turn_uuid"):
            raise AdapterError("native Claude turn identity is missing")
        if native_id != record["native_session_id"]:
            raise AdapterError("native reply belongs to a different conversation")
        if result["claude_turn_uuid"] == record.get("last_turn_id"):
            raise AdapterError("native reply belongs to the previous turn")
        record["last_turn_id"] = result["claude_turn_uuid"]
        record["native_session_id"] = native_id
        record["send_state"] = "replied"
        record["outcome"] = "replied"
        record["reply"] = reply
    except (AdapterError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        record["outcome"] = "cancelled" if stopped else "timeout" if time.monotonic() >= deadline else "failed"
        record["error"] = str(error)
    finally:
        cleaning = True
        try:
            if not record["session_id"]:
                matches = [row for row in deck.call("list") if row.get("title") == title]
                if len(matches) > 1:
                    raise AdapterError("multiple sessions match this run title")
                if matches:
                    record["session_id"] = matches[0]["id"]
                    record["worktree"] = matches[0].get("path")
            if record["session_id"]:
                deck.stop_owned(record["session_id"])
                record["cleanup"] = "stopped"
            else:
                record["cleanup"] = "no session found"
        except (AdapterError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            record["cleanup"] = "unresolved: " + str(error)
        write_json(records / "run.json", record)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    if record.get("worktree") and record["cleanup"] == "stopped":
        try:
            record["git"] = checked_worktree(record)
        except (AdapterError, OSError, ValueError, subprocess.SubprocessError) as error:
            record["outcome"] = "failed"
            record["error"] = str(error)
        write_json(journal, record)
    print(json.dumps(record), flush=True)
    return 0 if record["outcome"] == "replied" and record["cleanup"] == "stopped" else 1


def cleanup(args):
    records = Path(args.run_dir).absolute()
    journal = records / "run.json"
    private(journal)
    record = read_json(journal, 32768)
    deck = Deck(Path(args.config).absolute())
    if (record.get("profile"), record.get("socket")) != (deck.profile, deck.socket):
        raise AdapterError("run belongs to a different Agent Deck profile or socket")
    run_id = record["run"]
    if uuid.UUID(hex=run_id).hex != run_id or record.get("title") != "lean-" + run_id:
        raise AdapterError("invalid recorded run identity")
    try:
        rows = deck.call("list")
        matches = [row for row in rows if row.get("title") == record["title"]]
        if len(matches) != 1 or (record.get("session_id") and matches[0].get("id") != record["session_id"]):
            raise AdapterError("recorded session identity is missing or ambiguous")
        record["session_id"] = matches[0]["id"]
        write_json(journal, record)
        deck.stop_owned(record["session_id"])
        record["cleanup"] = "stopped"
    except (AdapterError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        record["cleanup"] = "unresolved: " + str(error)
    if record.get("worktree") and record["cleanup"] == "stopped":
        try:
            record["git"] = checked_worktree(record)
        except (AdapterError, OSError, ValueError, subprocess.SubprocessError) as error:
            record["outcome"] = "failed"
            record["error"] = str(error)
    write_json(journal, record)
    print(json.dumps(record), flush=True)
    return 0 if record["cleanup"] == "stopped" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo")
    parser.add_argument("--prompt")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--candidate", help="expected unchanged full input HEAD")
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--ack-ambiguous", action="store_true",
                        help="continue only after manually reconciling an uncertain prior send")
    parser.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()
    if args.cleanup_only:
        if any((args.repo, args.prompt, args.resume, args.ack_ambiguous, args.candidate, args.max_seconds is not None)):
            parser.error("cleanup-only accepts only config and run-dir")
    elif (not args.prompt or args.max_seconds is None
          or not math.isfinite(args.max_seconds) or args.max_seconds <= 0
          or (args.resume and (args.repo or args.candidate)) or (not args.resume and (not args.repo or args.ack_ambiguous))):
        parser.error("provide prompt and finite lifetime, plus repo for a new workstream")
    try:
        records = Path(args.run_dir).absolute()
        private(records, directory=True)
        with (records / "owner.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return cleanup(args) if args.cleanup_only else run(args)
    except (AdapterError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"adapter failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

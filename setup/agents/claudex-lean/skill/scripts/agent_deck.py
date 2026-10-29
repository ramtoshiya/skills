"""Run one bounded Agent Deck work unit using an operator-provisioned profile."""

import argparse
import fcntl
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


def run(args):
    config = Path(args.config).absolute()
    repo = Path(args.repo).resolve(strict=True)
    prompt = Path(args.prompt).resolve(strict=True)
    records = Path(args.run_dir).absolute()
    private(records, directory=True)
    if (records / "run.json").exists() or (records / "completion.json").exists():
        raise AdapterError("run directory already contains a run or completion")
    if prompt.stat().st_size > 65536:
        raise AdapterError("prompt exceeds 64 KiB")
    text = prompt.read_text(encoding="utf-8")
    if not text.strip():
        raise AdapterError("prompt is empty")
    deck = Deck(config)
    deck.failure_path = records / "control-error.json"
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD^{commit}"],
                          capture_output=True, text=True, check=True, timeout=20).stdout.strip()
    if args.role == "reviewer" and args.candidate != base:
        raise AdapterError("reviewer candidate must be the full input repository HEAD")
    run_id = uuid.uuid4().hex
    title = "lean-" + run_id
    result_path = records / "completion.json"
    record = {"run": run_id, "role": args.role, "base": base, "session_id": None,
              "title": title, "profile": deck.profile, "socket": deck.socket,
              "worktree": None, "outcome": "starting", "cleanup": "pending"}
    write_json(records / "run.json", record)
    stopped = False

    def cancel(signum, frame):
        nonlocal stopped
        stopped = True

    handlers = {sig: signal.signal(sig, cancel) for sig in (signal.SIGTERM, signal.SIGINT)}
    deadline = time.monotonic() + args.max_seconds

    def active():
        if stopped or time.monotonic() >= deadline:
            raise AdapterError("cancelled or timed out before dispatch")

    try:
        active()
        command = shlex.join([arg.replace("{run_dir}", str(records)) for arg in deck.command])
        # Agent Deck resolves a linked checkout to its main repository. Pin the
        # new branch before adding its worktree so that main's HEAD cannot win.
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
        write_json(records / "run.json", record)
        active()
        worktree = Path(record["worktree"]).resolve(strict=True)
        initial_head = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--verify", "HEAD^{commit}"],
                                      capture_output=True, text=True, check=True, timeout=20).stdout.strip()
        if initial_head != base:
            raise AdapterError("created worktree does not start at input HEAD")
        active()
        deck.call("session", "start", record["session_id"], json_output=False)
        active()
        if deck.trust_folder:
            settled = deck.call("session", "switch-settle", record["session_id"],
                                "--no-kick", "--timeout", "40s", timeout=50)
            if not settled.get("success") or not settled.get("settle", {}).get("ready"):
                raise AdapterError("worker startup did not become ready")
        active()
        instruction = (f"Role: {args.role}. Work only within the provided scope. "
                       f"When finished, write a UTF-8 JSON object to {result_path} with exactly "
                       "status (completed, blocked, or failed), summary (short plain text), "
                       "candidate (full commit SHA or null), and worktree (absolute path). "
                       "Write it atomically only after the work and its checks finish. "
                       "A completed builder must commit its work and return its clean HEAD. "
                       "A completed reviewer must not change the worktree and must return the input HEAD. "
                       "For blocked or failed work, candidate may be null. "
                       "Do not report queued or delivered messages as completion. "
                       "Do not write Multica state or comments.\n\n" + text)
        deck.call("session", "send", record["session_id"], instruction, "--timeout", "20s",
                  "--defer-if-busy", "--defer-timeout", "20s", timeout=30)
        record["outcome"] = "waiting"
        write_json(records / "run.json", record)
        while not stopped and time.monotonic() < deadline:
            if result_path.exists():
                result = read_json(result_path, 16384)
                if set(result) != {"status", "summary", "candidate", "worktree"}:
                    raise AdapterError("completion artifact has invalid fields")
                if result["status"] not in ("completed", "blocked", "failed") or not isinstance(result["summary"], str) or not result["summary"].strip() or len(result["summary"]) > 2000:
                    raise AdapterError("invalid completion status or summary")
                worktree = Path(result["worktree"]).resolve(strict=True)
                if not record["worktree"] or worktree != Path(record["worktree"]).resolve(strict=True):
                    raise AdapterError("completion worktree differs from owned worktree")
                candidate = result["candidate"]
                if candidate is not None:
                    actual = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--verify", "HEAD^{commit}"],
                                            capture_output=True, text=True, check=True, timeout=20).stdout.strip()
                    if candidate != actual:
                        raise AdapterError("candidate does not match worktree HEAD")
                    subprocess.run(["git", "-C", str(worktree), "merge-base", "--is-ancestor", base, candidate],
                                   capture_output=True, check=True, timeout=20)
                status = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain"],
                                        capture_output=True, text=True, check=True, timeout=20)
                record["worktree_dirty"] = bool(status.stdout)
                if result["status"] == "completed":
                    if candidate is None:
                        raise AdapterError("completed work requires a committed candidate")
                    if record["worktree_dirty"]:
                        raise AdapterError("completed worktree contains uncommitted changes")
                    if args.role == "reviewer" and candidate != base:
                        raise AdapterError("reviewer changed the input candidate HEAD")
                record["outcome"] = result["status"]
                record["candidate"] = candidate
                record["summary"] = result["summary"]
                break
            time.sleep(0.5)
        else:
            record["outcome"] = "cancelled" if stopped else "timeout"
    except (AdapterError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        record["outcome"] = "cancelled" if stopped else "timeout" if time.monotonic() >= deadline else "failed"
        record["error"] = str(error)
    finally:
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
    if record["outcome"] == "completed" and record["cleanup"] == "stopped":
        try:
            worktree = Path(record["worktree"]).resolve(strict=True)
            head = subprocess.run(["git", "-C", str(worktree), "rev-parse", "--verify", "HEAD^{commit}"],
                                  capture_output=True, text=True, check=True, timeout=20).stdout.strip()
            status = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain"],
                                    capture_output=True, text=True, check=True, timeout=20)
            if head != record["candidate"] or status.stdout:
                raise AdapterError("worktree changed after the completion artifact")
        except (AdapterError, OSError, ValueError, subprocess.SubprocessError) as error:
            record["outcome"] = "failed"
            record["error"] = str(error)
            write_json(records / "run.json", record)
    print(json.dumps(record), flush=True)
    return 0 if record["outcome"] == "completed" and record["cleanup"] == "stopped" else 1


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
    write_json(journal, record)
    print(json.dumps(record), flush=True)
    return 0 if record["cleanup"] == "stopped" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--repo")
    parser.add_argument("--prompt")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--role", choices=("builder", "reviewer"))
    parser.add_argument("--candidate", help="reviewer's full input HEAD")
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()
    if args.cleanup_only:
        if any((args.repo, args.prompt, args.role, args.candidate, args.max_seconds is not None)):
            parser.error("cleanup-only accepts only config and run-dir")
    elif (not args.repo or not args.prompt or not args.role or args.max_seconds is None
          or not math.isfinite(args.max_seconds) or args.max_seconds <= 0
          or (args.role == "reviewer" and not args.candidate)
          or (args.role == "builder" and args.candidate)):
        parser.error("provide repo, prompt, role, finite positive max-seconds, and reviewer candidate")
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

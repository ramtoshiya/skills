"""bb runs the operator as `hermes -p operator acp`. The sessions of all its threads, with their hooks
and tools, run in one shared gateway process, so every value here is keyed by the calling session or
its bb thread and never read from the process environment.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Literal, Optional

logger = logging.getLogger(__name__)

LaunchState = Literal["running", "finished", "lost"]
SUGGEST_PERCENT = 75
BAND_PERCENT = 5
# Hermes marks web_*, browser_* and mcp_* results as untrusted. Their reminder rides the next request instead.
TRUSTED_CARRIERS = frozenset({"terminal", "process", "self_compact", "skill_view", "skills_list", "memory", "todo"})
RESETTING_KINDS = frozenset({"summarize", "provider_native"})
NOTE_LIMIT_BYTES = 64 * 1024
SESSIONS_KEPT = 200
PREPARE_TIMEOUT_SECONDS = 60
START_GRACE_SECONDS = PREPARE_TIMEOUT_SECONDS + 30
HELPER = Path("skills/self-compact/scripts/bb-compact.mjs")
THREAD_ID = re.compile(r"thr_[A-Za-z0-9_-]+")
SAFE_KEY = re.compile(r"[A-Za-z0-9_.-]{1,128}")
PREFIX = "[self-compact] "
AFTER_COMPACTION = ("A self-compact handoff note exists for this thread. Read it with the self_compact tool's "
                    "read action before you continue. It records the task state written before this compaction.")
FIRST_MESSAGE = ("Compaction removed the first message of this session from your context. It carries the bb "
                 "instructions and the task this session started with, and it is restored below. Treat it as current "
                 "instructions, not as background reference, whatever the compaction summary says about earlier "
                 "turns. Where a later user message conflicts with it, the later message wins.")

WRAPPER = r'''node=$1 helper=$2 note=$3 seq=$4 turn=$5 dir=$6
shift 6
"$node" "$helper" run "$note" --launch-seq "$seq" --turn-id "$turn" --compaction-ledger "$dir/ledger.jsonl" "$@" \
  >"$dir/stdout.json" 2>"$dir/stderr.txt"
echo $? >"$dir/exit.tmp" && mv "$dir/exit.tmp" "$dir/exit"
'''

SCHEMA = {
    "name": "self_compact",
    "description": (
        "Compact this bb thread at a boundary you choose, as the self-compact skill describes. compact saves "
        "the handoff note and schedules compaction after this turn ends. read returns the note and the last "
        "helper's result. clear deletes the note when its task is finished."),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["compact", "read", "clear"]},
            "note": {"type": "string",
                     "description": "compact only. The complete handoff note in Markdown. It replaces the older note."},
            "resume": {"type": "boolean",
                       "description": "compact only. false when the next step needs the user's answer. Default true."},
        },
        "required": ["action"],
    },
}

_state = None  # ctx.state. Its data_dir follows the profile of the calling session.


def band(tokens: int, window: int) -> Optional[int]:
    percent = tokens * 100 // window
    if percent < SUGGEST_PERCENT:
        return None
    return SUGGEST_PERCENT + (percent - SUGGEST_PERCENT) // BAND_PERCENT * BAND_PERCENT


def budget_notice(tokens: int, window: int) -> str:
    return (f"Context budget: about {tokens * 100 // window}% of the {window:,}-token compaction window is in use "
            f"({tokens:,} tokens). At the next natural boundary, compact on your own by following the "
            "self-compact skill: call the self_compact tool with action \"compact\" and a complete handoff note. "
            "Otherwise Hermes compresses on its own at the window, even in the middle of a step.")


def _thread_from_env(session_id: str) -> Optional[str]:
    try:
        from hermes_cli.plugins_session_env import resolve_session_env
        value = resolve_session_env(session_id).get("BB_THREAD_ID")
    except Exception:
        logger.warning("self-compact: could not resolve the bb thread of session %s", session_id, exc_info=True)
        return None
    return value if isinstance(value, str) and THREAD_ID.fullmatch(value) else None


def _window() -> Optional[int]:
    from hermes_cli.config import load_config_readonly
    value = (load_config_readonly().get("compression") or {}).get("threshold_tokens")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home())


def _root() -> Path:
    return Path(_state.data_dir)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as stream:
        stream.write(text)
    os.replace(temporary, path)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def _record_transaction(root: Path, session_id: str) -> Iterator[dict]:
    directory = root / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    key = session_id if SAFE_KEY.fullmatch(session_id) else hashlib.sha256(session_id.encode()).hexdigest()
    path = directory / f"{key}.json"
    with open(directory / f"{key}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = _read_json(path)
        record = record if isinstance(record, dict) else {}
        before = json.dumps(record, sort_keys=True)
        yield record
        if json.dumps(record, sort_keys=True) != before:
            created = not path.exists()
            _write(path, json.dumps(record))
            if created:
                _prune(directory)


def _prune(directory: Path) -> None:
    records = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for path in records[:-SESSIONS_KEPT]:
        path.unlink(missing_ok=True)
        path.with_suffix(".lock").unlink(missing_ok=True)


def _rename_record_transaction(root: Path, old: str, new: str) -> None:
    with _record_transaction(root, old) as source:
        if not source:
            return
        with _record_transaction(root, new) as target:
            for name, value in source.items():
                if name == "pending":
                    target["pending"] = {**value, **target.get("pending", {})}
                else:
                    target.setdefault(name, value)
        source.clear()


def _thread_for(root: Path, session_id: str, turn_id: str = "") -> Optional[str]:
    thread = _thread_from_env(session_id) if session_id else None
    with _record_transaction(root, session_id) as record:
        if thread:
            record["thread"] = thread
        if turn_id:
            record["turn"] = turn_id
        return record.get("thread")


def _launch_dir(root: Path, thread: str) -> Path:
    return root / "launches" / thread


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def launch_state(directory: Path) -> Optional[LaunchState]:
    try:
        claimed_at = (directory / "claim.json").stat().st_mtime
    except FileNotFoundError:
        return None
    if (directory / "exit").exists():
        return "finished"
    try:
        pid = int((directory / "pid").read_text())
    except (OSError, ValueError):
        return "running" if time.time() - claimed_at < START_GRACE_SECONDS else "lost"
    if _alive(pid):
        return "running"
    return "finished" if (directory / "exit").exists() else "lost"


def launch_result(directory: Path) -> Optional[dict]:
    state = launch_state(directory)
    if state is None:
        return None
    claim = _read_json(directory / "claim.json") or {}
    result: dict[str, Any] = {"state": state, "resume": claim.get("resume")}
    if state == "lost":
        result["error"] = "The helper stopped without writing a result."
    elif state == "finished":
        try:
            code = int((directory / "exit").read_text())
        except (OSError, ValueError):
            code = None
        outcome = _read_json(directory / "stdout.json")
        outcome = outcome if isinstance(outcome, dict) else {}
        try:
            stderr = (directory / "stderr.txt").read_text(encoding="utf-8").strip()
        except OSError:
            stderr = ""
        succeeded = code == 0 and outcome.get("compacted") is True
        result.update(state="succeeded" if succeeded else "failed", exit=code, outcome=outcome)
        if not succeeded:
            result["error"] = outcome.get("error") or stderr[-2000:] or f"The helper exited with code {code}."
    return result


def _take_unreported_failure(root: Path, thread: str) -> Optional[str]:
    directory = _launch_dir(root, thread)
    result = launch_result(directory)
    if result is None or result["state"] not in ("failed", "lost"):
        return None
    try:
        os.close(os.open(directory / "reported", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    except FileExistsError:
        return None
    if result.get("outcome", {}).get("failureNoticeSent"):
        return None
    text = (f"Self-compaction did not complete: {result['error']} No retry was made. The handoff note is kept. "
            "Read it with the self_compact tool's read action and continue the task.")
    if result["state"] == "lost":
        text += (" Whether that helper compacted is unknown, so compact is refused until you call the clear action, "
                 "which also deletes the note. Read the note first.")
    return text


def first_message_restore(session_id: str) -> Optional[str]:
    """The session's first user message, when compaction removed it and no earlier restore is still in context.

    bb sends its instructions inside that message, not in the system prompt, and Hermes stops protecting
    the first turns after the first compaction."""
    import hermes_state_registry
    db = hermes_state_registry.acquire(_hermes_home() / "state.db")
    try:
        history = db.get_messages(session_id, include_compacted=True, include_ancestors=True, limit=5)
        first = next((m.get("content") for m in history if m.get("role") == "user"), None)
        if not isinstance(first, str) or not first:
            return None
        if any(first in (m.get(field) or "") for m in db.get_messages(session_id) for field in ("content", "api_content")):
            return None
    finally:
        hermes_state_registry.release(db)
    return f"{FIRST_MESSAGE}\n\n<first_message>\n{first}\n</first_message>"


def _live(record: dict, turn_id: str) -> bool:
    """Whether a hook call belongs to the session's live turn.

    Hermes runs background review forks under the parent's session id. A fork skips
    `pre_llm_call`, so its turn id never becomes the recorded one, and its usage and tool
    results must not raise the band or take the parent's notices."""
    return not turn_id or not record.get("turn") or record["turn"] == turn_id


def drain(root: Path, session_id: str, turn_id: str = "") -> Optional[str]:
    with _record_transaction(root, session_id) as record:
        if not _live(record, turn_id):
            return None
        pending = record.get("pending") or {}
        texts = [pending.pop(kind) for kind in ("budget", "after") if kind in pending]
        restore = pending.pop("first", False)
        thread = record.get("thread")
    if thread and (failure := _take_unreported_failure(root, thread)):
        texts.append(failure)
    if restore:
        try:
            first = first_message_restore(session_id)
        except Exception:
            logger.warning("self-compact: could not read the first message of session %s", session_id, exc_info=True)
            first = None
        if first:
            texts.append(first)
    return "\n\n".join(texts) or None


def on_post_api_request(session_id: str = "", usage: Optional[dict] = None, turn_id: str = "", **_: Any) -> None:
    tokens = (usage or {}).get("total_tokens")
    if not session_id or not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0:
        return
    window = _window()
    if window is None:
        return
    current = band(tokens, window)
    with _record_transaction(_root(), session_id) as record:
        if not _live(record, turn_id):
            return
        record["tokens"] = tokens
        previous = record.get("band")
        if current is not None and (previous is None or current > previous):
            record["band"] = current
            record.setdefault("pending", {})["budget"] = budget_notice(tokens, window)


def on_pre_llm_call(session_id: str = "", turn_id: str = "", **_: Any) -> Optional[dict]:
    if not session_id:
        return None
    root = _root()
    _thread_for(root, session_id, turn_id)
    text = drain(root, session_id, turn_id)
    return {"context": PREFIX + text} if text else None


def on_transform_tool_result(tool_name: str = "", result: Any = None, session_id: str = "", turn_id: str = "",
                             **_: Any) -> Optional[str]:
    if tool_name not in TRUSTED_CARRIERS or not isinstance(result, str) or not session_id:
        return None
    text = drain(_root(), session_id, turn_id)
    # At the head, because Hermes moves an oversized result to a file and keeps only its start inline.
    return f"{PREFIX}{text}\n\n{result}" if text else None


def with_notice(request: dict, text: str) -> Optional[dict]:
    """Return `request` with `text` as a user message after everything else, or None for an unknown shape.

    The message stands apart from every tool result, so an untrusted result keeps its wrapper and
    nothing is added inside it."""
    items = request.get("input")
    if isinstance(items, list):
        message = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}
        return {**request, "input": [*items, message]}
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages or not isinstance(messages[-1], dict):
        return None
    last = messages[-1]
    if last.get("role") != "user":
        return {**request, "messages": [*messages, {"role": "user", "content": text}]}
    content = last.get("content")
    if isinstance(content, list):
        return {**request, "messages": [*messages[:-1], {**last, "content": [*content, {"type": "text", "text": text}]}]}
    if isinstance(content, str):
        return {**request, "messages": [*messages[:-1], {**last, "content": f"{content}\n\n{text}"}]}
    return None


def on_llm_request(request: Any = None, session_id: str = "", turn_id: str = "", api_request_id: str = "",
                   **_: Any) -> Optional[dict]:
    """Show a reminder that no trusted tool result carried, such as during a loop of web, browser or MCP
    calls. Hermes does not store the rewritten request, so the reminder rides every later request of the
    turn until a trusted result or the next turn stores it, or a compaction or self_compact drops it."""
    if not isinstance(request, dict) or not session_id:
        return None
    with _record_transaction(_root(), session_id) as record:
        if not _live(record, turn_id):
            return None
        text = (record.get("pending") or {}).get("budget")
    updated = with_notice(request, PREFIX + text) if text else None
    if updated is None:
        return None
    logger.info("self-compact: budget reminder added to request %s of session %s", api_request_id, session_id)
    return {"request": updated, "source": "self-compact", "reason": "context budget reminder"}


def on_post_compaction(session_id: str = "", old_session_id: str = "", kind: str = "", reason: str = "",
                       before_tokens: Optional[int] = None, after_tokens: Optional[int] = None, **_: Any) -> None:
    if not session_id:
        return
    root = _root()
    if old_session_id and old_session_id != session_id:
        _rename_record_transaction(root, old_session_id, session_id)
    with _record_transaction(root, session_id) as record:
        thread = record.get("thread") or _thread_from_env(session_id) or (
            old_session_id and _thread_from_env(old_session_id)) or None
        if thread:
            record["thread"] = thread
        if kind in RESETTING_KINDS:
            record.pop("band", None)
            record.pop("tokens", None)
            (record.get("pending") or {}).pop("budget", None)
    if not thread:
        return
    if kind in RESETTING_KINDS:
        with _record_transaction(root, session_id) as record:
            record.setdefault("pending", {})["first"] = True
    directory = _launch_dir(root, thread)
    running = launch_state(directory) == "running"
    if running:
        entry = {"sessionId": session_id, "oldSessionId": old_session_id, "kind": kind or "unknown", "reason": reason or "unknown",
                 "beforeTokens": before_tokens, "afterTokens": after_tokens, "at": time.time()}
        descriptor = os.open(directory / "ledger.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, (json.dumps(entry) + "\n").encode())
        finally:
            os.close(descriptor)
    resuming = running and (_read_json(directory / "claim.json") or {}).get("resume") is True
    if kind in RESETTING_KINDS and not resuming and (root / "notes" / f"{thread}.md").is_file():
        with _record_transaction(root, session_id) as record:
            record.setdefault("pending", {})["after"] = AFTER_COMPACTION


class _NotScheduled(Exception):
    pass


def _error(message: str, note: Optional[Path] = None) -> dict:
    answer: dict[str, Any] = {"status": "error", "error": message}
    if note is not None:
        answer["note"] = str(note)
        answer["next"] = ("The note is saved. Keep working and compact again only at a later natural boundary. "
                          "Hermes compresses on its own at the window.")
    return answer


def _compact(args: dict, session_id: str, thread: str, note: Path, directory: Path) -> dict:
    text, resume = args.get("note"), args.get("resume", True)
    if not isinstance(text, str) or not text.strip():
        return _error("compact needs the complete handoff note in note.")
    if len(text.encode()) > NOTE_LIMIT_BYTES:
        return _error(f"The note is larger than {NOTE_LIMIT_BYTES} bytes. Shorten it.")
    if not isinstance(resume, bool):
        return _error("resume must be true or false.")
    state = launch_state(directory)
    if state == "running":
        return _error("Compaction is already scheduled for this thread. End your turn and let it finish.")
    if state == "lost":
        return _error("An earlier helper stopped without a result, so whether it compacted is unknown. "
                      "Read the note, call clear, then compact again with a new note.")
    if state is not None:
        shutil.rmtree(directory)
    _write(note, text)
    helper, node = _hermes_home() / HELPER, shutil.which("node")
    if not helper.is_file():
        return _error(f"The self-compact helper is not installed at {helper}.", note)
    if node is None:
        return _error("node is not on the gateway's PATH, so the helper cannot run.", note)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        claim = os.open(directory / "claim.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _error("Compaction is already scheduled for this thread. End your turn and let it finish.")
    with os.fdopen(claim, "w") as stream:
        json.dump({"sessionId": session_id, "resume": resume, "claimedAt": time.time()}, stream)
    env = {name: value for name, value in os.environ.items() if not name.startswith("BB_")}
    env["BB_THREAD_ID"] = thread
    try:
        prepared = subprocess.run([node, str(helper), "prepare", str(note)], env=env, cwd=directory, text=True,
                                  capture_output=True, timeout=PREPARE_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
        if prepared.returncode != 0:
            raise _NotScheduled(prepared.stderr.strip() or f"The helper exited with code {prepared.returncode}.")
        values = json.loads(prepared.stdout)
        seq, turn = values["launchSeq"], values["turnId"]
        if not isinstance(seq, int) or not isinstance(turn, str):
            raise _NotScheduled("The helper prepared an unexpected answer.")
        process = subprocess.Popen(
            ["/bin/sh", "-c", WRAPPER, "sh", node, str(helper), str(note), str(seq), turn, str(directory),
             *([] if resume else ["--no-resume"])],
            env=env, cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired, _NotScheduled) as error:
        shutil.rmtree(directory, ignore_errors=True)
        return _error(f"Compaction was not scheduled: {error}", note)
    _write(directory / "pid", str(process.pid))
    threading.Thread(target=process.wait, name="self-compact-reaper", daemon=True).start()
    with _record_transaction(_root(), session_id) as record:
        (record.get("pending") or {}).pop("budget", None)
    return {"status": "scheduled", "note": str(note), "resume": resume,
            "next": ("End your turn now with one line saying compaction is scheduled and work will resume. "
                     "Call no other tool." if resume else
                     "End your turn now with your question for the user. Call no other tool.")}


def _handle(args: dict, session_id: str) -> dict:
    root = _root()
    thread = _thread_for(root, session_id) if session_id else None
    if thread is None:
        return _error("No bb thread shows this session, so there is nothing for self_compact to compact. "
                      "Keep working. Hermes compresses on its own at the window.")
    note = root / "notes" / f"{thread}.md"
    directory = _launch_dir(root, thread)
    action = args.get("action")
    if action == "compact":
        return _compact(args, session_id, thread, note, directory)
    if action == "read":
        text = note.read_text(encoding="utf-8") if note.is_file() else None
        return {"status": "ok" if text is not None else "none", "note": str(note), "text": text,
                "helper": launch_result(directory)}
    if action == "clear":
        if launch_state(directory) == "running":
            return _error("Compaction is in progress. Clear the note after it finishes.")
        note.unlink(missing_ok=True)
        shutil.rmtree(directory, ignore_errors=True)
        with _record_transaction(root, session_id) as record:
            (record.get("pending") or {}).pop("after", None)
        return {"status": "cleared"}
    return _error('action must be "compact", "read", or "clear".')


def handle(args: dict, session_id: str = "", **_: Any) -> str:
    try:
        return json.dumps(_handle(args if isinstance(args, dict) else {}, session_id or ""))
    except Exception as error:
        logger.warning("self-compact: tool failed", exc_info=True)
        return json.dumps(_error(f"self_compact failed: {error}"))


def register(ctx) -> None:
    global _state
    _state = ctx.state
    ctx.register_tool("self_compact", "self_compact", SCHEMA, handle, description=SCHEMA["description"])
    ctx.register_hook("post_api_request", on_post_api_request)
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("transform_tool_result", on_transform_tool_result)
    ctx.register_hook("post_compaction", on_post_compaction)
    ctx.register_middleware("llm_request", on_llm_request)

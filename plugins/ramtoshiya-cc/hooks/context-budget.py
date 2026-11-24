#!/usr/bin/env python3
"""Context budget hook: suggests compaction before Claude Code compacts on its own.

PostToolUse and UserPromptSubmit read the latest main-thread token usage from the
transcript. From 75% of the numeric `autoCompactWindow` setting, the hook asks the
model once per five-point band to compact at the next natural boundary with the
self-compact skill. SessionStart after a compaction points the model to the
handoff note if one exists. Hook input carries no context size, so the transcript
is the only source. On any error the hook prints nothing.
"""
import json
import os
from pathlib import Path
import sys

SUGGEST_PERCENT = 75
BAND_PERCENT = 5
# Transcript lines holding tool output can be large. Stop looking after this many
# bytes from the end rather than read a long transcript on every tool call.
TAIL_LIMIT = 8 << 20
CHUNK = 256 << 10
STATE_SESSIONS = 100


def state_dir():
    state = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state"
    return Path(state) / "ramtoshiya"


def handoff_path(payload):
    scratchpad = payload.get("scratchpad_dir")
    if isinstance(scratchpad, str) and scratchpad:
        return Path(scratchpad) / "handoff.md"
    return state_dir() / "handoff" / f"{payload['session_id']}.md"


def read_json(path):
    try:
        with open(path) as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def compact_window(payload):
    """Return the numeric autoCompactWindow from local, project, then user settings."""
    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""
    config = os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude"
    candidates = [Path(config) / "settings.json"]
    if project:
        candidates = [Path(project) / ".claude/settings.local.json",
                      Path(project) / ".claude/settings.json"] + candidates
    for path in candidates:
        value = (read_json(path) or {}).get("autoCompactWindow")
        if value is None:
            continue
        # "auto" or any other non-number means the window is not known here.
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
    return None


def entry_tokens(line):
    """Return tokens for a main-thread assistant entry, 0 after a compaction, else None."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict):
        return None
    if entry.get("type") == "system" and entry.get("subtype") == "compact_boundary":
        return 0
    if entry.get("type") != "assistant" or entry.get("isSidechain"):
        return None
    usage = (entry.get("message") or {}).get("usage")
    if not isinstance(usage, dict):
        return None
    keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
    return sum(value for key in keys if isinstance(value := usage.get(key), int))


def context_tokens(transcript):
    """Return the context size after the last assistant reply, or 0 if a compaction came later."""
    with open(transcript, "rb") as stream:
        position = stream.seek(0, os.SEEK_END)
        end, rest = position, b""
        while position > 0 and end - position < TAIL_LIMIT:
            step = min(CHUNK, position)
            position -= step
            stream.seek(position)
            lines = (stream.read(step) + rest).split(b"\n")
            # The first piece may be the tail of a line that starts in an earlier chunk.
            rest = lines.pop(0) if position > 0 else b""
            for line in reversed(lines):
                if line.strip() and (tokens := entry_tokens(line)) is not None:
                    return tokens
    return None


def update_band(session, band):
    """Record the band for this session. Return whether it is higher than the last one."""
    path = state_dir() / "context-budget.json"
    state = read_json(path) or {}
    previous = state.pop(session, None)
    if band == previous:
        return False
    if band is not None:
        state[session] = band
    # Keep the newest sessions only. Dicts keep insertion order.
    state = dict(list(state.items())[-STATE_SESSIONS:])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(path)
    return band is not None and (previous is None or band > previous)


def suggestion(payload):
    window = compact_window(payload)
    if window is None:
        return None
    tokens = context_tokens(payload["transcript_path"])
    if tokens is None:
        return None
    percent = tokens * 100 // window
    band = None
    if percent >= SUGGEST_PERCENT:
        band = SUGGEST_PERCENT + (percent - SUGGEST_PERCENT) // BAND_PERCENT * BAND_PERCENT
    if not update_band(payload["session_id"], band):
        return None
    text = (f"Context budget: about {percent}% of the {window:,}-token auto-compact window is in use "
            f"({tokens:,} tokens). At the next natural boundary, compact on your own by following the "
            f"ramtoshiya:self-compact skill. Handoff note path: {handoff_path(payload)}.")
    thread = os.environ.get("BB_THREAD_ID")
    if thread:
        return text + f" This session runs in BB, thread id {thread}. Use the BB section of the skill."
    agent = os.environ.get("PASEO_AGENT_ID")
    if agent:
        return text + f" This session runs in Paseo, agent id {agent}. Use the Paseo section of the skill."
    return text + " Without a supported host control, automatic compaction is the fallback."


def after_compaction(payload):
    update_band(payload["session_id"], None)
    note = handoff_path(payload)
    if not note.is_file():
        return None
    return (f"A self-compact handoff note exists at {note}. Read it before you continue. "
            "It records the task state written before this compaction.")


def main():
    try:
        payload = json.load(sys.stdin)
        if payload.get("agent_id"):
            return  # A subagent cannot compact the main conversation.
        event = payload.get("hook_event_name")
        if event == "SessionStart":
            text = after_compaction(payload) if payload.get("source") == "compact" else None
        elif event in {"PostToolUse", "UserPromptSubmit"}:
            text = suggestion(payload)
        else:
            return
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


if __name__ == "__main__":
    main()

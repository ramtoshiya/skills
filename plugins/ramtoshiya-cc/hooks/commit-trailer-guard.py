#!/usr/bin/env python3
"""PreToolUse guard against AI attribution in commit messages and PR text.

Claude Code asks the model to end commits with a Co-Authored-By trailer and
PR bodies with a "Generated with Claude Code" footer. The `attribution`
setting turns that request off; this hook blocks the lines when the model adds
them anyway. Command text is matched, never evaluated. On an internal error the
hook allows the call, so a guard bug cannot block every shell command.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

# Commands that write a commit message, tag message, or PR/issue text.
ACTION = re.compile(
    r"(?:^|[\s;&|(`])(?:"
    r"git(?:\s+(?:-[Cc]\s+\S+|--?[A-Za-z][\w-]*(?:=\S+)?))*\s+(?:commit|commit-tree|merge|tag|notes)\b"
    r"|gs\s+\S"
    r"|gh\s+(?:pr|issue)\s+(?:create|edit|comment|merge|review)\b"
    r")")
ATTRIBUTION = [
    re.compile(r"co-authored-by:[^\n]*(?:claude|anthropic|codex|openai|copilot|cursor)[^\n]*", re.I),
    re.compile(r"generated with \[?claude code", re.I),
    re.compile(r"claude\.ai/code/", re.I),
]
# Message and body files: git -F/--file, gh -F/--body-file.
MESSAGE_FILE = re.compile(r"(?:^|\s)(?:-F|--file|--body-file)(?:=|\s+)(['\"]?)([^\s'\"]+)\1")
# Message files past the soft limit are still checked and logged. Files past the
# hard limit are logged and skipped. Claude Code hides hook stderr, so warnings go
# to the same log as the Pi extension's.
HARD_LIMIT = 1 << 30
SOFT_FILE_BYTES = 1 << 20


def size_warning_log():
    state = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state"
    return Path(state) / "ramtoshiya" / "size-warnings.log"


def check_size(name, size, soft_limit):
    """Return whether size is within the hard limit, logging sizes past the soft limit."""
    if size <= soft_limit:
        return True
    within = size <= HARD_LIMIT
    limit = f"the soft limit of {soft_limit} bytes" if within else f"the hard limit of {HARD_LIMIT} bytes, so it was not checked"
    try:
        log = size_warning_log()
        log.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with log.open("a") as stream:
            stream.write(f"{stamp} warning: {name} is {size} bytes, over {limit}\n")
    except OSError:
        pass
    return within


def attribution(text):
    return next((match.group(0) for pattern in ATTRIBUTION if (match := pattern.search(text))), None)


def reason(command, cwd):
    if not ACTION.search(command):
        return None
    texts = [command]
    for _, name in MESSAGE_FILE.findall(command):
        if name == "-":
            continue  # stdin; a heredoc body is already part of the command text
        path = Path(name).expanduser()
        if not path.is_absolute() and cwd:
            path = Path(cwd) / path
        try:
            if path.is_file() and check_size(f"commit-trailer-guard message file {str(path)!r}", path.stat().st_size, SOFT_FILE_BYTES):
                texts.append(path.read_text(errors="replace"))
        except OSError:
            pass
    for text in texts:
        found = attribution(text)
        if found:
            return (f"AI attribution is not allowed in commits or PRs (found: {found.strip()!r}). "
                    "The user's instructions override Claude Code's attribution reminder. "
                    "Remove the trailer, footer, or session link and run the command again.")
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        if payload.get("tool_name") not in {"Bash", "Monitor"}:
            return
        command = payload.get("tool_input", {}).get("command", "")
        if not isinstance(command, str):
            return
        denial_reason = reason(command, payload.get("cwd"))
    except (ValueError, TypeError, AttributeError):
        return
    if denial_reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": denial_reason,
        }}))


if __name__ == "__main__":
    main()

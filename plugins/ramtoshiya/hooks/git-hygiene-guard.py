#!/usr/bin/env python3
"""Stop hook: before the agent stops, ask it to deal with uncommitted changes.

Checks the Git working tree at the session's cwd. It blocks once per prompt,
and the retry passes, so a deliberate decision to leave the tree dirty still
wins. Any error allows the stop. This hook must never trap an agent.
"""
import json
import subprocess
import sys

TIMEOUT_SECONDS = 8
LISTED_LINES = 80
INSTRUCTIONS = """\
Before stopping, inspect each change and give only work you own an intentional disposition.
Commit completed work locally by default. Otherwise ignore or exclude it, stash it, keep it as explicit WIP, or remove it if it is disposable.
Do not commit, discard, or hide unrelated or pre-existing changes.
If the remaining changes are not yours, or an explicit instruction or legitimate WIP requires them to stay, stop again. This check allows the retry."""


def git(cwd, *args):
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=True,
    ).stdout


def reason(cwd):
    """Return the block message for a dirty working tree, or None."""
    repo = git(cwd, "rev-parse", "--show-toplevel").strip()
    lines = git(repo, "status", "--porcelain", "--untracked-files=normal").splitlines()
    if not lines:
        return None
    listing = lines[:LISTED_LINES]
    if len(lines) > LISTED_LINES:
        listing.append(f"... and {len(lines) - LISTED_LINES} more")
    return "\n".join([f"Git hygiene check: {repo} has uncommitted changes:", *listing, "", INSTRUCTIONS])


def main():
    try:
        payload = json.load(sys.stdin)
        if payload.get("stop_hook_active") is True:
            return
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return
        message = reason(cwd)
    except (ValueError, AttributeError, OSError, subprocess.SubprocessError):
        return
    if message:
        print(json.dumps({"decision": "block", "reason": message}))


if __name__ == "__main__":
    main()

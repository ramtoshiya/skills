#!/usr/bin/env python3
"""Agent shell environment hook: keeps agentmemory out of agent-started test runs.

Claude Code gives SessionStart hooks a CLAUDE_ENV_FILE path and sources that
file before every Bash command in the session, foreground or background. The
hook adds `export AGENTMEMORY_SDK_CHILD=1` to it. A `claude` or `codex`
process that the agent starts from Bash, directly or through a script,
inherits the variable, and the agentmemory plugin's hooks in that process
neither inject earlier sessions nor record the run. Claude Code runs its own
hooks without this file, so the session that started the run keeps its memory.
A process started with a cleared environment, such as `env -i`, loses the
variable. On any error the hook does nothing.
"""
import os
import sys

LINE = "export AGENTMEMORY_SDK_CHILD=1"


def main():
    sys.stdin.read()
    path = os.environ.get("CLAUDE_ENV_FILE")
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as stream:
            existing = stream.read()
    except FileNotFoundError:
        existing = ""
    if LINE in existing.splitlines():
        return
    prefix = "\n" if existing and not existing.endswith("\n") else ""
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(f"{prefix}{LINE}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass

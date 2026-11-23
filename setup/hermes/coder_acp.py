#!/usr/bin/env python3
"""Start Hermes's ACP server for a bb thread on the coder or the coder-child profile.

bb shows one Hermes Coder provider. A thread whose parent thread runs on that provider is a subagent that a
coder session started, so it runs on the child profile, which reads the coder's skills and memory but saves
neither. Every other thread runs on the learner profile.

Usage: coder_acp.py <bb provider id> <learner profile> <child profile> [hermes acp arguments...]
"""

import json
import os
import shutil
import subprocess
import sys


def thread(bb: str, thread_id: str) -> dict:
    result = subprocess.run([bb, "thread", "show", thread_id, "--json"], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        sys.exit(f"coder-acp: `bb thread show {thread_id}` failed, so the profile is unknown: "
                 f"{(result.stderr or result.stdout).strip()}")
    return json.loads(result.stdout)["thread"]


def profile(provider: str, learner: str, child: str) -> str:
    # bb starts a model discovery session without a thread. It only lists models, so either profile serves.
    thread_id = os.environ.get("BB_THREAD_ID")
    if not thread_id:
        return learner
    bb = os.environ.get("BB_CLI") or shutil.which("bb")
    if bb is None:
        sys.exit("coder-acp: the bb command is not on PATH, so the profile of this thread is unknown")
    # A worker that the nest plugin placed under a host past bb's depth limit names its caller as lifecycle owner.
    current = thread(bb, thread_id)
    caller = current.get("lifecycleOwnerThreadId") or current.get("parentThreadId")
    return child if caller and thread(bb, caller).get("providerId") == provider else learner


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit(__doc__.strip().splitlines()[-1])
    provider, learner, child, rest = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    os.execvp("hermes", ["hermes", "-p", profile(provider, learner, child), "acp", *rest])


if __name__ == "__main__":
    main()

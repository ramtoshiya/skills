"""Start the hermes-learning MCP server under the Hermes interpreter, or exit with the reason it cannot run.

An exit only marks this MCP server as failed. The Claude Code session goes on without it.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import store  # noqa: E402


def main():
    if store.in_coder_runtime():
        sys.exit("hermes-learning: off in the Hermes coder runtime, which runs Hermes learning itself")
    try:
        home = store.store()
        argv = store.hermes_command(Path(__file__).with_name("server.py"))
    except store.Unavailable as missing:
        sys.exit(f"hermes-learning: {missing}")
    os.execve(argv[0], argv, {**os.environ, "HERMES_HOME": str(home)})


if __name__ == "__main__":
    main()

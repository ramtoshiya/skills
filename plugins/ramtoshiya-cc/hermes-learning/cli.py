"""The hermes-learning command: run one of Hermes's memory, skill_manage and skill_view tools on the learning store.

Usage:
  hermes-learning <tool> < arguments.json         run the tool with the JSON arguments on stdin
  hermes-learning schema <tool>                   print the tool's description and argument schema

Agents call it through Bash instead of an MCP server. A Bash call leaves the request's tool list unchanged, so
a claudex session keeps its prompt cache, while loading an MCP tool through ToolSearch changes the list and
loses the cache on the proxy route. The session's bb thread decides which tools it may run, as store.ROLES lists.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import store  # noqa: E402

USAGE = "usage: hermes-learning <memory|skill_manage|skill_view> < arguments.json, or hermes-learning schema <tool>"
REFUSED = ("a thread that another thread started only reads skills with skill_view. Put the lesson under "
           "`Learning proposals` in your final answer instead.")


def requested_tool(args):
    if args[:1] == ["schema"] and len(args) == 2 and args[1] in store.TOOLS:
        return args[1]
    return args[0] if len(args) == 1 and args[0] in store.TOOLS else None


def main():
    args = sys.argv[1:]
    tool = requested_tool(args)
    if tool is None:
        sys.exit(USAGE)
    try:
        home = store.store()
        current = store.role()
        if tool not in store.ROLES[current]:
            sys.exit(f"hermes-learning: {tool} is not available here: {REFUSED}")
        argv = store.hermes_command(Path(__file__).with_name("tool.py"), *args)
    except store.Unavailable as missing:
        sys.exit(f"hermes-learning: {missing}")
    os.execve(argv[0], argv, {**os.environ, "HERMES_HOME": str(home)})


if __name__ == "__main__":
    main()

import json
import os
import re
import sys
from pathlib import Path

EDIT_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
SPAWN = re.compile(r"\b(?:nest|thread)\s+spawn\b")
PROVIDER = re.compile(r"--provider(?:=|\s+)['\"]?([\w.-]+)")
QUIET = re.compile(r"--parent-notifications(?:=|\s+)['\"]?off\b")
LEARNING = ("Hermes keeps one learner, the parent coder. Put what you learned in the Learning proposals of your "
            "final answer instead.")


def refusal(event: dict, subagent_provider: str, learner: Path | None) -> str | None:
    tool, args = event.get("tool_name"), event.get("tool_input") or {}
    stores = [learner / "skills", learner / "memories"] if learner else []
    if tool in EDIT_TOOLS and stores:
        target = Path(os.path.realpath(Path(args.get(EDIT_TOOLS[tool]) or "").expanduser()))
        if any(target.is_relative_to(os.path.realpath(store)) for store in stores):
            return f"{target} belongs to the learner profile's skills or memory, and a child coder saves neither. {LEARNING}"
    if tool != "Bash":
        return None
    command = args.get("command") or ""
    home = Path.home()
    named = [str(store.relative_to(home)) if store.is_relative_to(home) else str(store) for store in stores]
    if any(name in command for name in named):
        return f"the command names the learner profile's skills or memory directory, and a child coder saves neither. {LEARNING}"
    if not SPAWN.search(command):
        return None
    if learner:
        for provider in PROVIDER.findall(command):
            if provider != subagent_provider:
                return f"subagents of a child coder run on --provider {subagent_provider}, not {provider}"
    if not QUIET.search(command):
        return ("start subagents with --parent-notifications off and wait for them with bb thread wait. A notice "
                "that wakes this thread starts a new Hermes turn, and that turn cancels Hermes's review of this session")
    return None


def main() -> None:
    learner = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    reason = refusal(json.load(sys.stdin), sys.argv[1], learner)
    if reason:
        print(f"Refused in a coder session: {reason}.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

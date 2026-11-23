import json
import os
import re
import sys
from pathlib import Path

EDIT_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
PROVIDER = re.compile(r"--provider(?:=|\s+)['\"]?([\w.-]+)")


def refusal(event: dict, learner: Path, subagent_provider: str) -> str | None:
    stores = [learner / "skills", learner / "memories"]
    tool, args = event.get("tool_name"), event.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        target = Path(os.path.realpath(Path(args.get(EDIT_TOOLS[tool]) or "").expanduser()))
        if any(target.is_relative_to(os.path.realpath(store)) for store in stores):
            return f"{target} belongs to the learner profile's skills or memory"
    if tool == "Bash":
        command = args.get("command") or ""
        home = Path.home()
        named = [str(store.relative_to(home)) if store.is_relative_to(home) else str(store) for store in stores]
        if any(name in command for name in named):
            return "the command names the learner profile's skills or memory directory"
        if "spawn" in command:
            for provider in PROVIDER.findall(command):
                if provider != subagent_provider:
                    return f"subagents of a child coder run on --provider {subagent_provider}, not {provider}"
    return None


def main() -> None:
    reason = refusal(json.load(sys.stdin), Path(sys.argv[1]), sys.argv[2])
    if reason:
        print(f"Refused in a child coder session: {reason}. Hermes keeps one learner, the parent coder. "
              "Put what you learned in the Learning proposals of your final answer instead.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()

"""Register selected skills from a pinned checkout without copying upstream files."""

import json
import os
from pathlib import Path
import re
import subprocess
from threading import Lock

PENDING = {}
LOCK = Lock()


def call_key(tool_name, args, ids):
    return (ids.get("session_id", ""), ids.get("tool_call_id", ""), tool_name,
            json.dumps(args, sort_keys=True, default=str))


def tool_payloads(tool_name, args, cwd):
    if tool_name == "terminal":
        yield "Bash", args
    elif tool_name == "write_file":
        path = Path(args["path"]).expanduser()
        yield "Write", {"file_path": str(path if path.is_absolute() else Path(cwd) / path),
                        "content": args["content"]}
    elif tool_name == "patch":
        if args.get("mode") == "patch":
            yield "apply_patch", {"command": args["patch"]}
        else:
            path = Path(args["path"]).expanduser()
            yield "Edit", {**args, "file_path": str(path if path.is_absolute() else Path(cwd) / path)}
    elif tool_name == "tool_call":
        for call in args.get("calls", []):
            yield from tool_payloads(call["name"], call.get("arguments", {}), cwd)
    elif tool_name.startswith(("mcp__", "connectors__")):
        yield tool_name if tool_name.startswith("mcp__") else "mcp__" + tool_name, args


def advisory_hooks(context, source):
    """Translate the pinned Humanize PreToolUse advisory, without changing its rules."""
    root = Path(source["root"])
    hooks = json.loads((root / "hooks/hooks.json").read_text())["hooks"]
    if set(hooks) != {"PreToolUse"}:
        raise ValueError("Unsupported advisory hook events")

    def before(tool_name, args, **ids):
        warnings = []
        try:
            cwd = args.get("workdir") or os.environ.get("TERMINAL_CWD") or os.getcwd()
            for name, payload in tool_payloads(tool_name, args, cwd):
                for group in hooks["PreToolUse"]:
                    if not re.search(group.get("matcher", ".*"), name):
                        continue
                    for hook in group["hooks"]:
                        if hook.get("type") != "command":
                            continue
                        result = subprocess.run(
                            ["sh", "-c", hook["command"]],
                            input=json.dumps({"tool_name": name, "tool_input": payload, "cwd": cwd}),
                            capture_output=True, text=True, cwd=cwd, timeout=2, check=True,
                            env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(root)},
                        )
                        output = json.loads(result.stdout) if result.stdout.strip() else {}
                        warning = output.get("hookSpecificOutput", {}).get("additionalContext")
                        if isinstance(warning, str) and warning.strip():
                            warnings.append(warning)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            # Humanize is advisory. Its failure must not block the user's tool.
            pass
        with LOCK:
            key = call_key(tool_name, args, ids)
            PENDING.pop(key, None)
            if warnings:
                if len(PENDING) >= 512:
                    PENDING.pop(next(iter(PENDING)))
                PENDING[key] = "\n\n".join(warnings)
        return None

    def after(tool_name, args, result, **ids):
        with LOCK:
            warning = PENDING.pop(call_key(tool_name, args, ids), None)
        if not warning:
            return None
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                return json.dumps({**parsed, "humanize_warning": warning}, ensure_ascii=False)
            return result + "\n\n" + warning
        if isinstance(result, dict):
            return json.dumps({**result, "humanize_warning": warning}, ensure_ascii=False)
        return str(result) + "\n\n" + warning

    context.register_hook("pre_tool_call", before)
    context.register_hook("transform_tool_result", after)


def register(context):
    from agent.skill_utils import parse_frontmatter

    source = json.loads((Path(__file__).parent / "source.json").read_text())
    root = Path(source["root"])
    for relative in source["skills"]:
        path = root / relative / "SKILL.md"
        frontmatter, _ = parse_frontmatter(path.read_text())
        context.register_skill(path.parent.name, path, frontmatter.get("description", ""), frontmatter)
    if source.get("advisory_hooks"):
        advisory_hooks(context, source)

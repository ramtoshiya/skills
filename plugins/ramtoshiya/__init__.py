import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
RUNNER = [
    "uv", "run", "--offline", "--no-project", "--managed-python", "--python", ">=3.11",
    "--no-config", "--exclude-newer", "3 days", "python",
]
UNAVAILABLE = (
    "Package/Python guard could not verify this command. Check uv, a cached "
    "uv-managed Python >=3.11, and the guard source. The command was not executed."
)
def working_directory():
    return os.environ.get("TERMINAL_CWD") or os.getcwd()


def run_guard(script, payload, timeout):
    result = subprocess.run(
        [*RUNNER, str(ROOT / "hooks" / script)], input=json.dumps(payload),
        capture_output=True, text=True, timeout=timeout, check=True,
        cwd=payload["cwd"],
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def package_guard(tool_name, args, **kwargs):
    if tool_name != "terminal":
        return None
    try:
        output = run_guard("global-package-guard.py", {
            "tool_name": "Bash", "tool_input": args,
            "cwd": args.get("workdir") or working_directory(),
        }, 5)
        if output is None:
            return None
        decision = output["hookSpecificOutput"]
        message = decision["permissionDecisionReason"]
        if decision["permissionDecision"] != "deny" or not isinstance(message, str) or not message.strip():
            raise ValueError("Invalid package guard decision")
        return {"action": "block", "message": message}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return {"action": "block", "message": UNAVAILABLE}


def module_hint(tool_name, args, result, **kwargs):
    if tool_name != "terminal" or not isinstance(result, str):
        return None
    try:
        output = run_guard("python-module-hint.py", {
            "tool_name": "Bash", "tool_input": args, "tool_response": result,
            "cwd": args.get("workdir") or working_directory(),
        }, 5)
        context = output and output["hookSpecificOutput"]["additionalContext"]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return None
    return f"{result}\n\n{context}" if isinstance(context, str) and context else None


def register_optional_machine_preferences(ctx):
    from hermes_constants import get_hermes_home

    preferences = get_hermes_home() / "AGENTS.md"
    if preferences.is_file():
        ctx.register_system_prompt_section(
            "ramtoshiya.preferences", preferences.read_text(), max_chars=4000,
        )


def register(ctx):
    ctx.register_hook("pre_tool_call", package_guard)
    ctx.register_hook("transform_tool_result", module_hint)
    from agent.skill_utils import parse_frontmatter

    for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        frontmatter, _ = parse_frontmatter(path.read_text())
        ctx.register_skill(path.parent.name, path, frontmatter.get("description", ""), frontmatter)
    register_optional_machine_preferences(ctx)

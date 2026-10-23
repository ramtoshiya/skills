"""Hermes registration and translation for the shared Python guards."""

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
SKILLS = {
    "codex-session-reader": "Find and read local Codex CLI session transcripts.",
    "excalidraw-board": "Read and draw on shared Excalidraw rooms.",
    "figma-rest": "Read Figma designs through the REST API.",
    "imagegen": "Generate and edit raster images with GPT Image or Grok Imagine.",
    "mermaid-check": "Validate Mermaid diagrams with the real parser before delivery.",
    "reorganize-commits": "Reorganize branch commits when explicitly requested.",
    "stable-refs": "Keep document and plan identifiers stable through edits.",
}


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


def git_hygiene(attempt=0, **kwargs):
    try:
        output = run_guard("git-hygiene-guard.py", {
            "hook_event_name": "Stop", "cwd": working_directory(),
            "stop_hook_active": attempt > 0,
        }, 10)
        if output and output.get("decision") == "block":
            return output
    except (OSError, ValueError, AttributeError, TypeError, subprocess.SubprocessError):
        pass
    return None


def register(ctx):
    ctx.register_hook("pre_tool_call", package_guard)
    ctx.register_hook("pre_verify", git_hygiene)
    for name, description in SKILLS.items():
        ctx.register_skill(name, ROOT / "skills" / name / "SKILL.md", description,
                           {"disable-model-invocation": True} if name == "reorganize-commits" else {})

    # Preferences are optional machine setup, independent of plugin installation.
    from hermes_constants import get_hermes_home

    preferences = get_hermes_home() / "AGENTS.md"
    if preferences.is_file():
        ctx.register_system_prompt_section(
            "ramtoshiya.preferences", preferences.read_text(), max_chars=4000,
        )

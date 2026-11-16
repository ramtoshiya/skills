"""Hermes registration and translation for the shared package guard."""

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
    "excalidraw-board": "Read and draw on shared Excalidraw rooms.",
    "figma-rest": "Read Figma designs through the REST API.",
    "github-actions-authoring": (
        "Use before creating or editing .github/workflows/*.yml, "
        ".github/workflows/*.yaml, action.yml, or action.yaml. Verify official "
        "releases, the 72-hour cooldown, compatibility, and immutable commit pins."
    ),
    "imagegen": "Generate and edit raster images with GPT Image or Grok Imagine.",
    "impeccable-interview": (
        "Clarify or resume an Impeccable product task or user flow, and save "
        "approved surface-brief context without implementing UI."
    ),
    "mermaid-check": "Validate Mermaid diagrams with the real parser before delivery.",
    "read-x": "Read public X posts, profiles, and searches through the mdfromx API.",
    "reorganize-commits": "Reorganize branch commits when explicitly requested.",
    "stable-refs": "Keep document and plan identifiers stable through edits.",
    "worker-routing": (
        "Shared model, effort, provider, quota, retry, and escalation policy. Read when "
        "a skill or session mode names it. Loading it does not activate lead mode."
    ),
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


def register(ctx):
    ctx.register_hook("pre_tool_call", package_guard)
    for name, description in SKILLS.items():
        ctx.register_skill(name, ROOT / "skills" / name / "SKILL.md", description)

    # Preferences are optional machine setup, independent of plugin installation.
    from hermes_constants import get_hermes_home

    preferences = get_hermes_home() / "AGENTS.md"
    if preferences.is_file():
        ctx.register_system_prompt_section(
            "ramtoshiya.preferences", preferences.read_text(), max_chars=4000,
        )

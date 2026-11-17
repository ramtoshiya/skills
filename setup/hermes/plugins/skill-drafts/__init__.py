"""Turn every skill_manage call into a bb draft thread and block the local write.

Installed skills are copies of files that live in other repositories. A local
edit would drift from its source, so each write becomes a brief for a coding
agent instead. The user approves it by sending the draft in bb.

The hook fails closed: when the draft cannot be created, the call is still
blocked and the agent is told why. Hermes treats an exception in a hook as
"proceed", so every error is caught here.
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

SOURCES = Path(__file__).with_name("sources.json")
BB_TIMEOUT_SECONDS = 60
MAX_DIFF_LINES = 400


def operations(args: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the call as a list of operations, accepting the legacy flat shape."""
    ops = args.get("operations")
    if isinstance(ops, list):
        return [op for op in ops if isinstance(op, dict)]
    return [args] if args.get("action") else []


def installed_file(sources: dict[str, Any], name: str, file_path: str | None) -> Path | None:
    skill = sources.get("skills", {}).get(name)
    if skill is None:
        return None
    return Path(skill["installed"]) / (file_path or "SKILL.md")


def proposed_diff(sources: dict[str, Any], op: dict[str, Any]) -> str:
    """Unified diff of one operation against the installed copy, when it can be computed."""
    action = op.get("action")
    name = str(op.get("name", ""))
    file_path = op.get("file_path")
    target = installed_file(sources, name, file_path)
    before = target.read_text(encoding="utf-8") if target and target.is_file() else ""
    if action == "create" or (action == "patch" and "content" in op and "old_string" not in op):
        after = str(op.get("content", ""))
    elif action == "write_file":
        after = str(op.get("file_content", ""))
    elif action == "patch" and before and op.get("old_string") in before:
        count = -1 if op.get("replace_all") else 1
        after = before.replace(str(op["old_string"]), str(op.get("new_string", "")), count)
    elif action in ("delete", "remove_file"):
        after = ""
    else:
        return ""
    label = f"{name}/{file_path or 'SKILL.md'}"
    lines = list(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{label}", tofile=f"b/{label}"))
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"... diff truncated after {MAX_DIFF_LINES} lines\n"]
    return "".join(lines)


def owner(sources: dict[str, Any], name: str) -> dict[str, str]:
    """Checkout a change starts in, and where the skill's files live. Unknown names are new skills
    for the default repository."""
    skill = sources.get("skills", {}).get(name)
    if skill is None:
        return {"repo": sources["defaultRepo"], "location": ""}
    if skill.get("upstream"):
        return {"repo": skill["repo"], "location": (
            f"`{skill['path']}` in {skill['upstream']} at `{skill['commit']}`, pinned in "
            f"`.claude-plugin/marketplace.json` of `{skill['repo']}`. Change the fork, then update the "
            f"pin as that repository's `docs/upstream-skills.md` describes")}
    return {"repo": skill["repo"], "location": f"`{skill['path']}` in `{skill['repo']}`"}


def build_brief(sources: dict[str, Any], args: dict[str, Any], origin: str, session_id: str) -> str:
    ops = operations(args)
    names = sorted({str(op.get("name", "")) for op in ops})
    owners = []
    for name in names:
        where = owner(sources, name)
        location = where["location"] or f"a new skill. Place it in `{where['repo']}` where that repository's docs say"
        owners.append(f"- `{name}`: {location}")
    diffs = [d for d in (proposed_diff(sources, op) for op in ops) if d]
    session = (f"`{session_id}`. Read it with `hermes -p {sources['profile']} sessions export "
               f"--session-id {session_id} --format jsonl -`" if session_id else "unknown")
    parts = [
        f"Read {sources['modePath']} and follow it for this task.",
        "",
        "## Goal",
        "",
        "Decide whether the skill change below is worth making and, if it is, make it in the "
        "repository that owns the skill. If it is not, change nothing and say why.",
        "",
        "## Context",
        "",
        f"The Hermes operator agent tried to change installed skills with `skill_manage` "
        f"(writer: {origin}). A plugin blocked the call and created this draft. The installed "
        f"skills are copies, so the change must be made at their source.",
        "",
        "Skills and their sources:",
        "",
        *owners,
        "",
        "## Observation",
        "",
        "The tool call does not say why the change was proposed. Find the reason in the Hermes "
        f"session {session}.",
        "",
        "## Proposed change",
        "",
        "Raw `skill_manage` arguments:",
        "",
        "```json",
        json.dumps(args, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    if diffs:
        parts += ["Diff against the installed copy:", "", "```diff", *[d.rstrip("\n") for d in diffs], "```", ""]
    parts += [
        "## Constraints",
        "",
        "- Edit the source repository, never the copy under the Hermes profile.",
        "- Keep the change to what the observation supports. Follow the owning repository's rules.",
        "",
        "## Expected result",
        "",
        "The skill change is committed and pushed in the owning repository, and the Hermes "
        "operator profile has the updated copy.",
        "",
        "## Authority",
        "",
        "Sending this draft is the user's approval. You own the whole change: make it in the "
        "repository that owns the skill, commit, and push. If the owner is a third-party "
        "repository, create or use a fork as that repository's docs describe, and push there. "
        f"Then reinstall the operator profile's copies by running `mise run hermes:operator` in "
        f"`{sources['skillsRepo']}` once your commit is in the checkouts it copies from "
        f"({', '.join(f'`{c}`' for c in sources['sourceCheckouts'])}). After a pin update, run "
        f"`mise run agents:sync` there first. "
        "Report what you changed, the commits, and anything left undone.",
    ]
    return "\n".join(parts) + "\n"


def project_for(repo: str, bb: str) -> str | None:
    listing = subprocess.run([bb, "projects", "list", "--json"], capture_output=True, text=True,
                             timeout=BB_TIMEOUT_SECONDS, check=True)
    for project in json.loads(listing.stdout):
        for source in project.get("sources", []):
            if source.get("path") and Path(source["path"]) == Path(repo):
                return project["id"]
    return None


def create_draft(sources: dict[str, Any], args: dict[str, Any], origin: str, session_id: str) -> str:
    """Create the draft and return its thread id. Raises on any failure."""
    bb = os.environ.get("BB_CLI") or shutil.which("bb")
    if not bb:
        raise RuntimeError("the bb CLI is not on PATH")
    names = sorted({str(op.get("name", "")) for op in operations(args)})
    repo = owner(sources, names[0])["repo"] if names else sources["defaultRepo"]
    command = [bb, "draft", "create", "--json", "--new-environment", "worktree",
               "--title", f"Skill change: {', '.join(names) or 'unknown'}",
               "--prompt", build_brief(sources, args, origin, session_id)]
    if sources.get("provider"):
        command += ["--provider", sources["provider"]]
    project = project_for(repo, bb)
    if project:
        command += ["--project", project]
    result = subprocess.run(command, capture_output=True, text=True, timeout=BB_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:500])
    return json.loads(result.stdout)["threadId"]


def write_origin() -> str:
    try:
        from tools.write_approval import current_origin
        return current_origin()
    except Exception:
        return "unknown"


def on_pre_tool_call(tool_name: str = "", args: dict[str, Any] | None = None, **kwargs: Any):
    if tool_name != "skill_manage":
        return None
    try:
        sources = json.loads(SOURCES.read_text(encoding="utf-8"))
        thread = create_draft(sources, args or {}, write_origin(), str(kwargs.get("session_id") or ""))
    except Exception as error:  # fail closed: any error still blocks the write
        return {"action": "block", "message": (
            f"Blocked. Skills are not changed locally, and creating a bb draft for this change "
            f"failed: {error}. Tell the user, and do not retry through the terminal.")}
    return {"action": "block", "message": (
        f"Not applied locally. Created the draft @thread:{thread} for a coding agent. Tell the user "
        f"that sending it approves the change and deleting it rejects it. The draft carries the raw "
        f"arguments and this session's id, so state your reason for the change in your reply, "
        f"where the worker will read it.")}


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", on_pre_tool_call)

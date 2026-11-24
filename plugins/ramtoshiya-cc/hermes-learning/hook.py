"""Claude Code hooks for the Hermes learning store.

session-start: refresh the hermes-skills plugin folder in the store, which the CLAUDE_CODE_PLUGIN_DIRS setting
names, and add the store's USER.md and MEMORY.md to the session context.
skill-used: record a Skill tool use of a hermes-skills skill in the store's skills/.usage.json with Hermes's
own bump_view and bump_use, the pair Hermes's skill_view records.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import store  # noqa: E402

PLUGIN_NAME = "hermes-skills"


def learned_skills(home: Path) -> dict[str, Path]:
    """Skill folders by folder name, without Hermes's bundled skills and hidden folders such as .archive."""
    root = home / "skills"
    manifest = root / ".bundled_manifest"
    bundled = ({line.split(":", 1)[0] for line in manifest.read_text(encoding="utf-8").split()}
               if manifest.is_file() else set())
    found = {}
    for skill_md in sorted(root.rglob("SKILL.md")) if root.is_dir() else ():
        parts = skill_md.relative_to(root).parts
        if not any(part.startswith(".") for part in parts) and skill_md.parent.name not in bundled:
            found[skill_md.parent.name] = skill_md.parent
    return found


def sync_skills_plugin(home: Path) -> None:
    root = home / store.SKILLS_PLUGIN
    skills = root / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    manifest = root / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        manifest.parent.mkdir(exist_ok=True)
        manifest.write_text(json.dumps({"name": PLUGIN_NAME, "description": "Skills the Hermes profile learned"})
                            + "\n")
    wanted = learned_skills(home)
    for link in skills.iterdir():
        if link.name not in wanted or not link.is_symlink() or Path(os.readlink(link)) != wanted[link.name]:
            link.unlink()
    for name, target in wanted.items():
        if not (skills / name).is_symlink():
            (skills / name).symlink_to(target, target_is_directory=True)


def memory_context(home: Path) -> str:
    parts = []
    for name, label in (("USER.md", "User profile"), ("MEMORY.md", "Environment memory")):
        path = home / "memories" / name
        text = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        if text:
            parts.append(f"## Hermes {label} ({name})\n\n{text}")
    if not parts:
        return ""
    return ("# Hermes profile memory\n\nThe Hermes learning store held these notes when this session started.\n\n"
            + "\n\n".join(parts))


def session_start(event: dict) -> dict:
    if store.in_coder_runtime():
        return {}
    try:
        home = store.store()
    except store.Unavailable:
        return {}  # the hermes-learning MCP server reports the missing store
    sync_skills_plugin(home)
    context = memory_context(home)
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}} if context else {}


def skill_used(event: dict) -> dict:
    plugin, _, folder = str((event.get("tool_input") or {}).get("skill") or "").partition(":")
    if plugin != PLUGIN_NAME:
        return {}
    home = store.store()
    skill = learned_skills(home).get(folder)
    if skill is None:
        return {}
    command = store.hermes_command(Path(__file__).with_name("usage.py"), str(skill), event.get("session_id") or "")
    subprocess.run(command, env={**os.environ, "HERMES_HOME": str(home)}, check=True, timeout=60,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return {}


if __name__ == "__main__":
    handler = {"session-start": session_start, "skill-used": skill_used}[sys.argv[1]]
    try:
        print(json.dumps(handler(json.load(sys.stdin))))
    except store.Unavailable as missing:
        print(json.dumps({"systemMessage": f"hermes-learning: {missing}"}))

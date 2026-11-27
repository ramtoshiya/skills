"""Claude Code hooks for the Hermes learning store.

session-start: refresh the hermes-skills plugin folder in the store, which the CLAUDE_CODE_PLUGIN_DIRS setting
names, add the store's USER.md and MEMORY.md and the role's learning instructions to the session context, and
start Hermes's curator in the background.
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
CLI = Path(__file__).with_name("hermes-learning")
RECORD = ("Hermes learning store: memory holds the USER.md and MEMORY.md notes above, and the skills are the "
          "hermes-skills plugin. When this session confirms a lesson a later session would reuse, such as a user "
          "preference or correction, a fact about the machine or a project, or a procedure that worked, record "
          "it then. Put a lesson that matters only for one class of task, including the user's preferences for "
          "that kind of work, in the skill that governs that class with skill_manage (skill_view it before you "
          "patch it, or create a class-level skill). Use memory only for short facts every session needs "
          "whatever its task. Record only what a person or an agent in the conversation stated, or a tool result showed. Run "
          f"these tools with Bash. `{CLI} schema <tool>` prints a tool's arguments, and `{CLI} <tool> <<'JSON'` "
          "followed by the JSON arguments and a closing `JSON` line runs it.")
CHILD = ("You are a child agent that another agent started. Read Hermes skills, but do not record memory or "
         "skills. End your final answer with a `Learning proposals` section of at most five bullets. Each "
         "bullet is something your own tool runs in this task showed that a later session could reuse, such "
         "as a command that works, a path, or a project rule, followed by the command or file that shows it. "
         "Write `Learning proposals: none` when nothing qualifies.")
INSTRUCTIONS = {"top": RECORD, "solo": RECORD, "child": CHILD}


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


def start_curator() -> None:
    """Detached, because importing Hermes takes seconds and the session should not wait for it."""
    subprocess.Popen([sys.executable, __file__, "curator"], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_curator(home: Path) -> None:
    argv = store.hermes_command(Path(__file__).with_name("curator.py"))
    os.execve(argv[0], argv, {**os.environ, "HERMES_HOME": str(home)})


def session_start(event: dict) -> dict:
    role = store.role()
    try:
        home = store.store()
    except store.Unavailable:
        return {}
    sync_skills_plugin(home)
    if role in ("top", "solo"):
        start_curator()
    context = "\n\n".join(part for part in (memory_context(home), INSTRUCTIONS.get(role, "")) if part)
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
    if sys.argv[1] == "curator":
        run_curator(store.store())
    handler = {"session-start": session_start, "skill-used": skill_used}[sys.argv[1]]
    try:
        print(json.dumps(handler(json.load(sys.stdin))))
    except store.Unavailable as missing:
        print(json.dumps({"systemMessage": f"hermes-learning: {missing}"}))

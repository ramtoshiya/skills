"""Install or update the Hermes operator profile from this checkout.

Run with `mise run hermes:operator`. docs/setup.md describes what it changes.
Every installed file is a copy. Running it again replaces the managed copies
and leaves memories, sessions, credentials, and other settings alone.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PSTACK_SKILLS = ("in-your-own-words", "why", "how", "interrogate", "statechart",
                 "technical-writing", "unslop")
PSTACK_SKILL_DIR = "plugins/pstack-mode/skills"
LOCAL_SKILLS = ("operator-handoff",)
PLUGINS = ("skill-drafts", "bb-thread-env")
SOUL_BEGIN = "<!-- BEGIN ramtoshiya:operator -->"
SOUL_END = "<!-- END ramtoshiya:operator -->"
CONFIG = {
    "agent.disabled_toolsets": '["file", "code_execution"]',
    "skills.auto_load": '["operator-handoff"]',
    "skills.project_discovery": "false",
    "curator.enabled": "false",
    "memory.write_approval": "false",
}


def run(*command: str, cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"hermes-operator: `{' '.join(command[:4])}` failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def main_checkout(path: Path) -> Path:
    """The main working tree of the repository that contains path, also from a linked worktree."""
    common = run("git", "-C", str(path), "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common.strip()).parent


def with_soul_block(text: str, block: str) -> str:
    """Return text with exactly one operator block, replacing an existing one."""
    managed = f"{SOUL_BEGIN}\n{block.strip()}\n{SOUL_END}\n"
    pattern = re.compile(re.escape(SOUL_BEGIN) + r".*?" + re.escape(SOUL_END) + r"\n?", re.S)
    if pattern.search(text):
        return pattern.sub(lambda _: managed, text, count=1)
    return text.rstrip("\n") + "\n\n" + managed if text.strip() else managed


def copy_tracked(repo: Path, subdir: str, target: Path) -> None:
    """Copy only the files Git tracks under subdir, so build output and dependencies stay behind."""
    listing = run("git", "-C", str(repo), "ls-files", "-z", "--", subdir)
    files = [name for name in listing.split("\0") if name]
    if not files:
        sys.exit(f"hermes-operator: no tracked files under {repo / subdir}")
    for name in files:
        destination = target / Path(name).relative_to(subdir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / name, destination)


def install_skills(skills_dir: Path, pstack: Path, skills_repo: Path, values: dict[str, str],
                   previous: dict[str, object]) -> dict[str, dict[str, str]]:
    installed: dict[str, dict[str, str]] = {}
    for name in previous:
        if name not in PSTACK_SKILLS + LOCAL_SKILLS:
            shutil.rmtree(skills_dir / name, ignore_errors=True)
    for name in PSTACK_SKILLS:
        target = skills_dir / name
        shutil.rmtree(target, ignore_errors=True)
        copy_tracked(pstack, f"{PSTACK_SKILL_DIR}/{name}", target)
        installed[name] = {"repo": str(pstack), "path": f"{PSTACK_SKILL_DIR}/{name}", "installed": str(target)}
    for name in LOCAL_SKILLS:
        target = skills_dir / name
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(HERE / "skills" / name, target, ignore=shutil.ignore_patterns("__pycache__"))
        skill = target / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        skill.write_text(text, encoding="utf-8")
        installed[name] = {"repo": str(skills_repo), "path": f"setup/hermes/skills/{name}", "installed": str(target)}
    return installed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="operator")
    parser.add_argument("--pstack", default="~/workspaces/pstack-mode",
                        help="pstack-mode checkout that supplies mode.md and the conversation skills")
    parser.add_argument("--worker-provider", default="claude-code",
                        help="bb provider for drafts created from blocked skill writes")
    options = parser.parse_args()

    if shutil.which("hermes") is None:
        sys.exit("hermes-operator: the hermes command is not on PATH. Install Hermes Agent first.")
    pstack = main_checkout(Path(options.pstack).expanduser())
    mode_md = pstack / "plugins/pstack-mode/mode.md"
    if not mode_md.is_file():
        sys.exit(f"hermes-operator: {mode_md} not found. Pass --pstack <checkout>.")
    skills_repo = main_checkout(HERE)
    profile = options.profile

    if subprocess.run(["hermes", "profile", "show", profile], capture_output=True).returncode != 0:
        run("hermes", "profile", "create", profile, "--no-skills")
    run("hermes", "profile", "use", profile)
    home = Path.home() / ".hermes" / "profiles" / profile
    if not home.is_dir():
        sys.exit(f"hermes-operator: profile home {home} not found after creating the profile")

    soul = home / "SOUL.md"
    current = soul.read_text(encoding="utf-8") if soul.exists() else ""
    updated = with_soul_block(current, (HERE / "soul-operator.md").read_text(encoding="utf-8"))
    if updated != current:
        soul.write_text(updated, encoding="utf-8")

    sources_json = home / "plugins" / "skill-drafts" / "sources.json"
    previous = {}
    if sources_json.is_file():
        previous = json.loads(sources_json.read_text(encoding="utf-8")).get("skills", {})
    skills_dir = home / "skills"
    skills_dir.mkdir(exist_ok=True)
    values = {"MODE_MD": str(mode_md), "SOURCES_JSON": str(sources_json), "SKILLS_REPO": str(skills_repo)}
    installed = install_skills(skills_dir, pstack, skills_repo, values, previous)

    for plugin in PLUGINS:
        plugin_dir = home / "plugins" / plugin
        shutil.rmtree(plugin_dir, ignore_errors=True)
        shutil.copytree(HERE / "plugins" / plugin, plugin_dir, ignore=shutil.ignore_patterns("__pycache__"))
    sources = {
        "profile": profile,
        "modePath": str(mode_md),
        "defaultRepo": str(skills_repo),
        "skillsRepo": str(skills_repo),
        "provider": options.worker_provider,
        "sourceCheckouts": [str(skills_repo), str(pstack)],
        "skills": installed,
    }
    sources_json.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")

    for key, value in CONFIG.items():
        run("hermes", "-p", profile, "config", "set", key, value)
    for plugin in PLUGINS:
        run("hermes", "-p", profile, "plugins", "enable", plugin, "--no-allow-tool-override")

    others = sorted(p.name for p in skills_dir.iterdir()
                    if p.is_dir() and not p.name.startswith(".") and p.name not in installed)
    print(f"hermes-operator: profile {profile} at {home} is the default profile")
    print(f"hermes-operator: installed skills {', '.join(sorted(installed))} and plugins {', '.join(PLUGINS)}")
    if others:
        print(f"hermes-operator: other skills in the profile, left in place: {', '.join(others)}")


if __name__ == "__main__":
    main()

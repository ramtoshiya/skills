"""Install or update the Hermes operator profile from this checkout.

Run with `mise run hermes:operator`. docs/setup.md describes what it changes.
Every installed file is a copy. Running it again replaces the managed copies
and leaves memories, sessions, credentials, and other settings alone.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PSTACK_PLUGIN = "pstack-mode"
PSTACK_SKILLS = ("in-your-own-words", "why", "how", "interrogate", "statechart",
                 "technical-writing", "unslop")
PSTACK_SKILL_DIR = "plugins/pstack-mode/skills"
LOCAL_SKILLS = ("operator-handoff",)
PLUGINS = ("skill-drafts", "bb-thread-env")
MANAGED_SKILLS = "ramtoshiya-skills"
SOUL_BEGIN = "<!-- BEGIN ramtoshiya:operator -->"
SOUL_END = "<!-- END ramtoshiya:operator -->"
CONFIG = {
    "agent.disabled_toolsets": '["file", "code_execution"]',
    "skills.auto_load": '["operator-handoff"]',
    "skills.project_discovery": "false",
    "curator.enabled": "false",
    "memory.write_approval": "false",
}


@dataclass(frozen=True)
class Source:
    """Files Git tracks under `path` in `checkout`, and the plugin they come from.

    A change to them starts in the local checkout `repo`. `upstream` and `commit` name the
    third-party fork and the commit `repo` pins, when the files come from one.
    """
    plugin: str
    checkout: Path
    path: str
    repo: Path
    upstream: str | None = None
    commit: str | None = None


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


def copy_tracked(source: Source, target: Path) -> None:
    """Copy only the files Git tracks under the source path, so build output and dependencies stay behind."""
    listing = run("git", "-C", str(source.checkout), "ls-files", "-z", "--", source.path)
    files = [name for name in listing.split("\0") if name]
    if not files:
        sys.exit(f"hermes-operator: no tracked files under {source.checkout / source.path}")
    for name in files:
        destination = target / Path(name).relative_to(source.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.checkout / name, destination)


def marketplace(skills_repo: Path) -> tuple[dict[str, str], dict[str, Source], dict[str, Source]]:
    """Plugin descriptions, the skills each marketplace entry selects, and entries that are Hermes plugins.

    Pinned sources come from the checkouts `mise run agents:sync` fetches. pstack-mode is left
    to --pstack. An entry with a plugin.yaml is a native Hermes plugin and is installed whole.
    """
    sys.path.insert(0, str(HERE.parent / "agents"))
    import sync as agents

    descriptions: dict[str, str] = {}
    skills: dict[str, Source] = {}
    packages: dict[str, Source] = {}
    try:
        sync = agents.Sync(skills_repo)
        for entry in sync.marketplace["plugins"]:
            name = entry["name"]
            descriptions[name] = entry.get("description", "")
            if name == PSTACK_PLUGIN:
                continue
            package = sync.sources.package(entry)
            pinned = {}
            if isinstance(entry["source"], dict):
                package.check()
                pinned = {"upstream": f"https://github.com/{entry['source']['url']}", "commit": package.ref}
            if (package.root / "plugin.yaml").is_file():
                packages[name] = Source(name, package.repository, package.prefix, skills_repo, **pinned)
                continue
            for path in package.skills():
                if path.name in skills:
                    sys.exit(f"hermes-operator: {skills[path.name].plugin} and {name} both provide the skill {path.name}")
                skills[path.name] = Source(name, package.repository,
                                           path.relative_to(package.repository).as_posix(), skills_repo, **pinned)
    except agents.ERRORS as error:
        sys.exit(f"hermes-operator: {error}. Run `mise run agents:sync` first to fetch the pinned sources.")
    return descriptions, skills, packages


def plugin_skills(name: str, package: Source) -> dict[str, Source]:
    """Skills a Hermes plugin package registers from hermes/skills, under its plugin namespace."""
    root = package.checkout / package.path / "hermes/skills"
    return {f"{name}:{path.parent.name}": Source(name, package.checkout, f"{package.path}/hermes/skills/{path.parent.name}",
                                                 package.repo, package.upstream, package.commit)
            for path in sorted(root.glob("*/SKILL.md"))}


def plugin_list(descriptions: dict[str, str], skills: dict[str, Source]) -> str:
    """Markdown list of each plugin's description and skills, for operator-handoff."""
    by_plugin: dict[str, list[str]] = {}
    for name, source in sorted(skills.items()):
        by_plugin.setdefault(source.plugin, []).append(f"`{name}`")
    return "\n".join(f"- `{plugin}`: {descriptions.get(plugin, '').rstrip('.')}. Skills: {', '.join(names)}."
                     for plugin, names in by_plugin.items())


def install_skills(target: Path, sources: dict[str, Source], local_values: dict[str, str]) -> None:
    """Build every managed skill in a staging directory, then swap it in for target."""
    staging = target.with_name(f".{target.name}.new")
    shutil.rmtree(staging, ignore_errors=True)
    for name, source in sources.items():
        copy_tracked(source, staging / name)
        if name in LOCAL_SKILLS:
            skill = staging / name / "SKILL.md"
            text = skill.read_text(encoding="utf-8")
            for key, value in local_values.items():
                text = text.replace("{{" + key + "}}", value)
            skill.write_text(text, encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)


def with_dirs(profile: str, dirs: list[Path]) -> str:
    """The profile's skills.external_dirs with dirs added, as JSON for `hermes config set`."""
    current = json.loads(run("hermes", "-p", profile, "config", "get", "skills.external_dirs", "--json") or "[]")
    current = [current] if isinstance(current, str) else current or []
    return json.dumps(current + [str(d) for d in dirs if str(d) not in current])


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
    descriptions, skills, packages = marketplace(skills_repo)
    profile = options.profile

    pstack_skills = {name: Source(PSTACK_PLUGIN, pstack, f"{PSTACK_SKILL_DIR}/{name}", pstack) for name in PSTACK_SKILLS}
    local_skills = {name: Source("operator", HERE.parents[1], f"setup/hermes/skills/{name}", skills_repo)
                    for name in LOCAL_SKILLS}
    managed: dict[str, Source] = {}
    for group in (skills, pstack_skills, local_skills):
        clash = managed.keys() & group.keys()
        if clash:
            sys.exit(f"hermes-operator: two plugins provide the skill {', '.join(sorted(clash))}")
        managed.update(group)
    registered = {name: source for plugin, package in packages.items()
                  for name, source in plugin_skills(plugin, package).items()}

    if subprocess.run(["hermes", "profile", "show", profile], capture_output=True).returncode != 0:
        run("hermes", "profile", "create", profile, "--no-skills")
    run("hermes", "profile", "use", profile)
    default_home = Path.home() / ".hermes"
    home = default_home / "profiles" / profile
    if not home.is_dir():
        sys.exit(f"hermes-operator: profile home {home} not found after creating the profile")

    soul = home / "SOUL.md"
    current = soul.read_text(encoding="utf-8") if soul.exists() else ""
    updated = with_soul_block(current, (HERE / "soul-operator.md").read_text(encoding="utf-8"))
    if updated != current:
        soul.write_text(updated, encoding="utf-8")

    sources_json = home / "plugins" / "skill-drafts" / "sources.json"
    previous = json.loads(sources_json.read_text(encoding="utf-8")) if sources_json.is_file() else {}
    skills_dir = home / "skills"
    skills_dir.mkdir(exist_ok=True)
    for entry in previous.get("skills", {}).values():
        old = Path(entry["installed"])
        if old.parent == skills_dir:
            shutil.rmtree(old, ignore_errors=True)
    managed_dir = home / MANAGED_SKILLS
    values = {"MODE_MD": str(mode_md), "SOURCES_JSON": str(sources_json), "SKILLS_REPO": str(skills_repo),
              "SKILL_PLUGINS": plugin_list(descriptions, {**skills, **pstack_skills, **registered})}
    install_skills(managed_dir, managed, values)

    for plugin in PLUGINS:
        plugin_dir = home / "plugins" / plugin
        shutil.rmtree(plugin_dir, ignore_errors=True)
        shutil.copytree(HERE / "plugins" / plugin, plugin_dir, ignore=shutil.ignore_patterns("__pycache__"))
    for plugin in set(previous.get("packagePlugins", [])) - packages.keys():
        run("hermes", "-p", profile, "plugins", "disable", plugin)
        shutil.rmtree(home / "plugins" / plugin, ignore_errors=True)
    for plugin, package in packages.items():
        plugin_dir = home / "plugins" / plugin
        shutil.rmtree(plugin_dir, ignore_errors=True)
        copy_tracked(package, plugin_dir)

    installed = {name: managed_dir / name for name in managed}
    installed |= {name: home / "plugins" / source.plugin / Path(source.path).relative_to(packages[source.plugin].path)
                  for name, source in registered.items()}
    owners = {name: {"plugin": source.plugin, "repo": str(source.repo),
                     "path": source.path, "installed": str(installed[name]),
                     **({"upstream": source.upstream, "commit": source.commit} if source.upstream else {})}
              for name, source in {**managed, **registered}.items()}
    sources = {
        "profile": profile,
        "modePath": str(mode_md),
        "defaultRepo": str(skills_repo),
        "skillsRepo": str(skills_repo),
        "provider": options.worker_provider,
        "sourceCheckouts": [str(skills_repo), str(pstack)],
        "skills": owners,
        "packagePlugins": sorted(packages),
    }
    sources_json.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")

    config = {**CONFIG, "skills.external_dirs": with_dirs(profile, [managed_dir])}
    for key, value in config.items():
        run("hermes", "-p", profile, "config", "set", key, value)
    for plugin in (*PLUGINS, *sorted(packages)):
        run("hermes", "-p", profile, "plugins", "enable", plugin, "--no-allow-tool-override")
    # bb lists Hermes skills from the default home, not the sticky profile, so the default home
    # shows the profile's skills and no bundled ones.
    for name in (profile, "default"):
        run("hermes", "-p", name, "skills", "opt-out", "--remove", "--yes")
    run("hermes", "-p", "default", "config", "set", "skills.external_dirs", with_dirs("default", [skills_dir, managed_dir]))

    others = sorted(p.parent.name for p in skills_dir.rglob("SKILL.md")
                    if not any(part.startswith(".") for part in p.relative_to(skills_dir).parts))
    print(f"hermes-operator: profile {profile} at {home} is the default profile")
    print(f"hermes-operator: installed skills {', '.join(sorted({**managed, **registered}))}")
    print(f"hermes-operator: enabled plugins {', '.join((*PLUGINS, *sorted(packages)))}")
    if others:
        print(f"hermes-operator: other skills in {skills_dir}, left in place: {', '.join(others)}")


if __name__ == "__main__":
    main()

"""Install or update the Hermes operator profile from this checkout.

Run with `mise run hermes:operator`. docs/setup.md describes what it changes.
Every installed file is a copy. Running it again replaces the managed copies
and leaves memories, sessions, credentials, and other settings alone.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
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
PLUGINS = ("skill-drafts", "bb-thread-env", "self-compact")
RESEARCH_PROJECT = "proj_personal"
# Hermes seeds these into every home, opted out or not, until the home's .bundled_manifest tracks
# them as deleted. Mirrors ESSENTIAL_SKILLS in Hermes's agent/skill_utils.py.
ESSENTIAL_SKILLS = ("hermes-agent",)
# bb's shipped Hermes entry, minus the launch and skill roots that bb_catalog_agent sets. Manual
# compaction is on because bb refuses `bb thread compact` for an entry without the flag.
BB_AGENT = {"id": "hermes-agent", "displayName": "Hermes Agent", "command": "hermes",
            "supportsManualCompaction": True,
            "nativeReasoning": {"configId": "reasoning_effort", "defaultLevel": "medium",
                                "supportedLevels": ["none", "low", "medium", "high", "xhigh", "max"]}}
SOUL_BEGIN = "<!-- BEGIN ramtoshiya:operator -->"
SOUL_END = "<!-- END ramtoshiya:operator -->"
CONFIG = {
    "agent.disabled_toolsets": '["file", "code_execution", "delegation"]',
    "skills.auto_load": '["operator-handoff"]',
    "skills.project_discovery": "false",
    "curator.enabled": "false",
    "memory.write_approval": "false",
    "compression.threshold_tokens": "300000",
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
            manifest = package.root / "plugin.yaml"
            if manifest.is_file():
                declared = re.search(r"^name:\s*[\"']?([^\"'\s]+)", manifest.read_text(encoding="utf-8"), re.M)
                if declared is None or declared[1] != name:
                    sys.exit(f"hermes-operator: {manifest} must declare `name: {name}`, its marketplace entry, "
                             "because Hermes enables the plugin and namespaces its skills by that name")
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


def install_skill(target: Path, source: Source, local_values: dict[str, str]) -> None:
    """Replace target with a fresh copy of the skill, filling the placeholders of this repository's own skills."""
    shutil.rmtree(target, ignore_errors=True)
    copy_tracked(source, target)
    if target.name in LOCAL_SKILLS:
        skill = target / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        for key, value in local_values.items():
            text = text.replace("{{" + key + "}}", value)
        skill.write_text(text, encoding="utf-8")


def skill_name(skill_md: Path) -> str:
    """The frontmatter name Hermes keys a skill by, or its directory name."""
    text = skill_md.read_text(encoding="utf-8")
    header = text.split("\n---", 1)[0] if text.startswith("---") else ""
    found = re.search(r"^name:\s*[\"']?(.+?)[\"']?\s*$", header, re.M)
    return found[1] if found else skill_md.parent.name


def drop_bundled(profile: str, home: Path, keep: set[Path]) -> None:
    """Delete every Hermes bundled skill in home and keep its manifest entry.

    Every chat start, gateway start, and `hermes update` syncs bundled skills. With the opt-out
    marker the sync seeds only ESSENTIAL_SKILLS, and it skips a skill the manifest tracks but the
    disk lacks, because the user deleted it. `reset --restore` makes the essential skills tracked
    first, so the deletion below covers them.
    """
    run("hermes", "-p", profile, "skills", "opt-out")
    for name in ESSENTIAL_SKILLS:
        run("hermes", "-p", profile, "skills", "reset", name, "--restore", "--yes")
    skills_dir = home / "skills"
    manifest = skills_dir / ".bundled_manifest"
    tracked = ({line.split(":", 1)[0] for line in manifest.read_text(encoding="utf-8").split()}
               if manifest.is_file() else set())
    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        top = skills_dir / skill_md.relative_to(skills_dir).parts[0]
        if (skill_md.is_file() and not top.name.startswith(".") and top not in keep
                and skill_name(skill_md) in tracked):
            shutil.rmtree(skill_md.parent)


def reload_gateway(profile: str) -> None:
    """Load the plugin files just copied into the gateway that serves the profile, without a restart."""
    lines = run("hermes", "-p", profile, "skill-drafts", "reload").strip().splitlines()
    answer = json.loads(lines[-1]) if lines else None
    if answer is None:
        print(f"hermes-operator: no running gateway serves profile {profile}. The next one to start loads its plugins")
    elif not answer.get("reloaded"):
        sys.exit(f"hermes-operator: the running gateway did not reload profile {profile}'s plugins: "
                 f"{answer.get('error') or 'no reason given'}. Its sessions keep the previous plugin code "
                 f"until that gateway restarts")
    else:
        print(f"hermes-operator: the running gateway reloaded profile {profile}'s plugins")


def bb_catalog_agent(profile: str, home: Path, packages: dict[str, Source]) -> None:
    """Point bb's Hermes provider at the profile: the process it launches and the skills its composer lists.

    bb's shipped Hermes entry launches the sticky profile and lists only the default home's skills.
    A customAgents entry with id hermes-agent replaces it. The other custom agents stay.
    """
    bb = os.environ.get("BB_CLI") or shutil.which("bb")
    if bb is None:
        print("hermes-operator: bb is not on PATH, so bb's Hermes provider was left as it was")
        return
    values = json.loads(run(bb, "plugin", "config", "provider-acp", "--json"))["values"]
    agents = [agent for agent in json.loads(values.get("customAgents") or "[]") if agent.get("id") != BB_AGENT["id"]]
    relative = home.relative_to(Path.home()).as_posix()
    roots = [{"path": f"{relative}/skills", "recursive": True}]
    roots += [{"path": f"{relative}/plugins/{name}/hermes/skills", "namePrefix": f"{name}:"} for name in sorted(packages)]
    agents.append({**BB_AGENT, "args": ["-p", profile, "acp"], "nativeSkillRoots": {"user": roots}})
    run(bb, "plugin", "config", "provider-acp", "set", "customAgents", json.dumps(agents))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="operator")
    parser.add_argument("--pstack", default="~/workspaces/pstack-mode",
                        help="pstack-mode checkout that supplies mode.md and the conversation skills")
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
    values = {"MODE_MD": str(mode_md), "SOURCES_JSON": str(sources_json), "SKILLS_REPO": str(skills_repo),
              "RESEARCH_PROJECT": RESEARCH_PROJECT,
              "SKILL_PLUGINS": plugin_list(descriptions, {**skills, **pstack_skills, **registered})}
    for name, source in managed.items():
        install_skill(skills_dir / name, source, values)

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

    installed = {name: skills_dir / name for name in managed}
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
        "researchProject": RESEARCH_PROJECT,
        "skillsDir": str(skills_dir),
        "sourcesPath": str(sources_json),
        "skills": owners,
        "packagePlugins": sorted(packages),
    }
    sources_json.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")

    for key, value in CONFIG.items():
        run("hermes", "-p", profile, "config", "set", key, value)
    for plugin in (*PLUGINS, *sorted(packages)):
        run("hermes", "-p", profile, "plugins", "enable", plugin, "--no-allow-tool-override")
    reload_gateway(profile)
    # bb lists the default home's skills/ for Hermes even with its own skill roots, so that home
    # loses its bundled skills too.
    drop_bundled(profile, home, {skills_dir / name for name in managed})
    drop_bundled("default", default_home, set())
    bb_catalog_agent(profile, home, packages)
    print(run("hermes", "-p", profile, "sessions", "refresh-prompts").strip())

    others = sorted(p.parent.name for p in skills_dir.rglob("SKILL.md")
                    if p.relative_to(skills_dir).parts[0] not in managed
                    and not any(part.startswith(".") for part in p.relative_to(skills_dir).parts))
    print(f"hermes-operator: profile {profile} at {home} is the default profile")
    print(f"hermes-operator: installed skills {', '.join(sorted({**managed, **registered}))}")
    print(f"hermes-operator: enabled plugins {', '.join((*PLUGINS, *sorted(packages)))}")
    if others:
        print(f"hermes-operator: other skills in {skills_dir}, left in place: {', '.join(others)}")


if __name__ == "__main__":
    main()

"""Install or update the Hermes coder profiles from the checkout that holds this file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "agents"))
import level  # noqa: E402
import sync as agents  # noqa: E402

PROVIDER = "claude-code-runtime"
PLUGINS = ("claude-code-commands", "bb-thread-env", "bb-title-input")
DEFAULT_MODEL = "sonnet"
STAMP = "hermes-coder.json"
BB_AGENT = {"command": "hermes",
            "nativeReasoning": {"configId": "reasoning_effort", "defaultLevel": "medium",
                                "supportedLevels": ["none", "low", "medium", "high", "xhigh", "max"]}}


@dataclass(frozen=True)
class Profile:
    name: str
    agent_id: str
    display_name: str
    learner: Profile | None = None

    @property
    def home(self) -> Path:
        return Path.home() / ".hermes" / "profiles" / self.name


LEARNER = Profile("coder", "hermes-coder", "Hermes Coder")
CHILD = Profile("coder-child", "hermes-coder-child", "Hermes Coder (agents only)", learner=LEARNER)
PROFILES = (LEARNER, CHILD)


def config(profile: Profile) -> dict[str, str]:
    # Hermes lists its direct Anthropic provider wherever a Claude Code login exists, and a model picked
    # there would bypass Claude Code.
    shared = {"model.provider": PROVIDER, "compression.enabled": "false",
              "model_catalog.excluded_providers": '["anthropic"]',
              "claude_code_runtime.subagent_provider": f"acp-{CHILD.agent_id}"}
    if profile.learner is None:
        return shared
    return shared | {"auxiliary.background_review.enabled": "false",
                     "claude_code_runtime.learner_home": str(profile.learner.home)}


def run(*command: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"hermes-coder: `{' '.join(command[:5])}` failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def plugin_targets(home: Path) -> dict[str, Path]:
    return {PROVIDER: home / "plugins" / "model-providers" / PROVIDER,
            **{name: home / "plugins" / name for name in PLUGINS}}


def installed_plugins() -> dict[str, Path]:
    return {f"{profile.name}/{name}": path for profile in PROFILES for name, path in plugin_targets(profile.home).items()}


def fingerprint(trees: dict[str, Path], extra: dict[str, bytes | str]) -> str:
    entries = dict(extra)
    for name, path in trees.items():
        entries |= {f"plugins/{name}/{file}": value for file, value in
                    (agents.files(path) if path.is_dir() else {}).items()}
    return digest(entries)


def digest(entries: dict[str, bytes | str]) -> str:
    hasher = hashlib.sha256()
    for key in sorted(entries):
        value = entries[key]
        hasher.update(f"{key}\0{len(value)}\0".encode())
        hasher.update(value.encode() if isinstance(value, str) else value)
    return hasher.hexdigest()


def bb_catalog_agents() -> None:
    bb = os.environ.get("BB_CLI") or shutil.which("bb")
    if bb is None:
        print("hermes-coder: bb is not on PATH, so bb has no Hermes Coder entries")
        return
    values = json.loads(run(bb, "plugin", "config", "provider-acp", "--json"))["values"]
    ours = {profile.agent_id for profile in PROFILES}
    custom = [agent for agent in json.loads(values.get("customAgents") or "[]") if agent.get("id") not in ours]
    skills = {"path": f"{LEARNER.home.relative_to(Path.home()).as_posix()}/skills", "recursive": True}
    custom += [{"id": profile.agent_id, "displayName": profile.display_name, **BB_AGENT,
                "args": ["-p", profile.name, "acp"], "nativeSkillRoots": {"user": [skills]}} for profile in PROFILES]
    run(bb, "plugin", "config", "provider-acp", "set", "customAgents", json.dumps(custom))


def install(profile: Profile, sources: dict[str, Path]) -> None:
    if subprocess.run(["hermes", "profile", "show", profile.name], capture_output=True).returncode != 0:
        run("hermes", "profile", "create", profile.name, "--no-skills", "--no-credentials", "--no-alias")
    if not profile.home.is_dir():
        sys.exit(f"hermes-coder: profile home {profile.home} not found after creating the profile")
    for name, target in plugin_targets(profile.home).items():
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(sources[name], target, ignore=shutil.ignore_patterns("__pycache__"))
    current = subprocess.run(["hermes", "-p", profile.name, "config", "get", "model.provider", "--json"],
                             capture_output=True, text=True)
    first_use_of_provider = current.returncode != 0 or json.loads(current.stdout or "null") != PROVIDER
    if first_use_of_provider:
        run("hermes", "-p", profile.name, "config", "set", "model.default", DEFAULT_MODEL)
    for key, value in config(profile).items():
        run("hermes", "-p", profile.name, "config", "set", key, value)
    for name in PLUGINS:
        run("hermes", "-p", profile.name, "plugins", "enable", name, "--no-allow-tool-override")
    lines = run("hermes", "-p", profile.name, "claude-code", "reload").strip().splitlines()
    answer = json.loads(lines[-1]) if lines else None
    if answer is not None and not answer.get("reloaded"):
        sys.exit(f"hermes-coder: the running gateway did not reload profile {profile.name}'s plugins: "
                 f"{answer.get('error') or 'no reason given'}")
    model = json.loads(run("hermes", "-p", profile.name, "config", "get", "model.default", "--json") or "null")
    print(f"hermes-coder: profile {profile.name} at {profile.home} uses {PROVIDER}, default model {model}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 unless the installed profiles match their sources, and change nothing")
    options = parser.parse_args()

    if shutil.which("hermes") is None:
        sys.exit("hermes-coder: the hermes command is not on PATH. Install Hermes Agent first.")
    checkout = HERE.parent.parent
    sources = {PROVIDER: HERE / "plugins" / PROVIDER, **{name: HERE / "plugins" / name for name in PLUGINS}}
    configs = {profile.name: config(profile) for profile in PROFILES}
    wanted = fingerprint(sources, {"installer": Path(__file__).read_bytes(), "config": json.dumps(configs)})
    stamp = level.state_dir() / STAMP
    previous = json.loads(stamp.read_text(encoding="utf-8")) if stamp.is_file() else {}
    names = " and ".join(profile.name for profile in PROFILES)

    if options.check:
        if not previous:
            sys.exit(f"hermes-coder: profiles {names} have no install record. Run `mise run hermes:coder`")
        if wanted != previous.get("wanted"):
            sys.exit(f"hermes-coder: profiles {names} are out of date: their sources changed since the install "
                     f"from {previous.get('commit', '?')[:12]}")
        if fingerprint(installed_plugins(), {}) != previous.get("loaded"):
            sys.exit(f"hermes-coder: profiles {names} are out of date: their plugin files changed since the last install")
        print(f"hermes-coder: profiles {names} match their sources, installed from {previous['commit'][:12]}")
        return

    warning = level.install_source_warning(checkout)
    if warning:
        print(f"hermes-coder: {warning}", file=sys.stderr)
    for profile in PROFILES:
        install(profile, sources)
    bb_catalog_agents()
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps({
        "commit": run("git", "-C", str(checkout), "rev-parse", "HEAD").strip(),
        "wanted": wanted,
        "loaded": fingerprint(installed_plugins(), {}),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"hermes-coder: enabled plugins {', '.join(PLUGINS)}")

if __name__ == "__main__":
    main()

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
LAUNCHER = "coder_acp.py"
BB_AGENT_ID = "hermes-coder"
BB_PROVIDER = f"acp-{BB_AGENT_ID}"
RETIRED_AGENT_IDS = ("hermes-coder-child",)
BB_AGENT = {"id": BB_AGENT_ID, "displayName": "Hermes Coder",
            "nativeReasoning": {"configId": "reasoning_effort", "defaultLevel": "medium",
                                "supportedLevels": ["none", "low", "medium", "high", "xhigh", "max"]}}


@dataclass(frozen=True)
class Profile:
    name: str
    learner: Profile | None = None

    @property
    def home(self) -> Path:
        return Path.home() / ".hermes" / "profiles" / self.name


LEARNER = Profile("coder")
CHILD = Profile("coder-child", learner=LEARNER)
PROFILES = (LEARNER, CHILD)


def config(profile: Profile, pstack_root: Path) -> dict[str, str]:
    # Hermes lists its direct Anthropic provider wherever a Claude Code login exists, and a model picked
    # there would bypass Claude Code.
    shared = {"model.provider": PROVIDER, "compression.enabled": "false",
              "model_catalog.excluded_providers": '["anthropic"]',
              "claude_code_runtime.subagent_provider": BB_PROVIDER,
              "claude_code_runtime.pstack_root": str(pstack_root)}
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


def installed_launcher() -> Path:
    return LEARNER.home / LAUNCHER


def installed_plugins() -> dict[str, Path]:
    return {f"{profile.name}/{name}": path for profile in PROFILES for name, path in plugin_targets(profile.home).items()}


def loaded_launcher() -> dict[str, bytes]:
    path = installed_launcher()
    return {"launcher": path.read_bytes()} if path.is_file() else {}


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


def install_launcher() -> None:
    target = installed_launcher()
    shutil.copyfile(HERE / LAUNCHER, target)
    target.chmod(0o755)


def bb_catalog_agents() -> None:
    bb = os.environ.get("BB_CLI") or shutil.which("bb")
    if bb is None:
        print("hermes-coder: bb is not on PATH, so bb has no Hermes Coder entry")
        return
    values = json.loads(run(bb, "plugin", "config", "provider-acp", "--json"))["values"]
    ours = {BB_AGENT_ID, *RETIRED_AGENT_IDS}
    custom = [agent for agent in json.loads(values.get("customAgents") or "[]") if agent.get("id") not in ours]
    skills = {"path": f"{LEARNER.home.relative_to(Path.home()).as_posix()}/skills", "recursive": True}
    custom.append({**BB_AGENT, "command": str(installed_launcher()), "args": [BB_PROVIDER, LEARNER.name, CHILD.name],
                   "nativeSkillRoots": {"user": [skills]}})
    run(bb, "plugin", "config", "provider-acp", "set", "customAgents", json.dumps(custom))


def pstack_root(checkout: Path) -> Path:
    common = run("git", "-C", str(checkout), "rev-parse", "--path-format=absolute", "--git-common-dir")
    root = Path(common.strip()).parent / "plugins/pstack-mode"
    if not (root / "mode.md").is_file():
        sys.exit(f"hermes-coder: {root / 'mode.md'} not found. Pass --pstack <checkout>.")
    return root


def install(profile: Profile, sources: dict[str, Path], configs: dict[str, dict[str, str]]) -> None:
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
    for key, value in configs[profile.name].items():
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
    parser.add_argument("--pstack", default="~/workspaces/pstack-mode",
                        help="pstack-mode checkout whose mode.md every coding run follows")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 unless the installed profiles match their sources, and change nothing")
    options = parser.parse_args()

    if shutil.which("hermes") is None:
        sys.exit("hermes-coder: the hermes command is not on PATH. Install Hermes Agent first.")
    checkout = HERE.parent.parent
    sources = {PROVIDER: HERE / "plugins" / PROVIDER, **{name: HERE / "plugins" / name for name in PLUGINS}}
    root = pstack_root(Path(options.pstack).expanduser())
    configs = {profile.name: config(profile, root) for profile in PROFILES}
    wanted = fingerprint(sources, {"installer": Path(__file__).read_bytes(), "launcher": (HERE / LAUNCHER).read_bytes(),
                                   "config": json.dumps(configs)})
    stamp = level.state_dir() / STAMP
    previous = json.loads(stamp.read_text(encoding="utf-8")) if stamp.is_file() else {}
    names = " and ".join(profile.name for profile in PROFILES)

    if options.check:
        if not previous:
            sys.exit(f"hermes-coder: profiles {names} have no install record. Run `mise run hermes:coder`")
        if wanted != previous.get("wanted"):
            sys.exit(f"hermes-coder: profiles {names} are out of date: their sources changed since the install "
                     f"from {previous.get('commit', '?')[:12]}")
        if fingerprint(installed_plugins(), loaded_launcher()) != previous.get("loaded"):
            sys.exit(f"hermes-coder: profiles {names} are out of date: their plugin files changed since the last install")
        print(f"hermes-coder: profiles {names} match their sources, installed from {previous['commit'][:12]}")
        return

    warning = level.install_source_warning(checkout)
    if warning:
        print(f"hermes-coder: {warning}", file=sys.stderr)
    for profile in PROFILES:
        install(profile, sources, configs)
    install_launcher()
    bb_catalog_agents()
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps({
        "commit": run("git", "-C", str(checkout), "rev-parse", "HEAD").strip(),
        "wanted": wanted,
        "loaded": fingerprint(installed_plugins(), loaded_launcher()),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"hermes-coder: enabled plugins {', '.join(PLUGINS)}")

if __name__ == "__main__":
    main()

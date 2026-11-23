"""Install or update the Hermes coder profile from the checkout that holds this file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "agents"))
import level  # noqa: E402
import sync as agents  # noqa: E402

PROFILE = "coder"
PROVIDER = "claude-code-runtime"
PLUGINS = ("claude-code-commands", "bb-thread-env", "bb-title-input")
DEFAULT_MODEL = "sonnet"
# Hermes lists its direct Anthropic provider wherever a Claude Code login exists, and a model picked
# there would bypass Claude Code.
CONFIG = {"model.provider": PROVIDER, "compression.enabled": "false",
          "model_catalog.excluded_providers": '["anthropic"]'}
BB_AGENT = {"id": "hermes-coder", "displayName": "Hermes Coder", "command": "hermes",
            "nativeReasoning": {"configId": "reasoning_effort", "defaultLevel": "medium",
                                "supportedLevels": ["none", "low", "medium", "high", "xhigh", "max"]}}


def run(*command: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"hermes-coder: `{' '.join(command[:5])}` failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def plugin_targets(home: Path) -> dict[str, Path]:
    return {PROVIDER: home / "plugins" / "model-providers" / PROVIDER,
            **{name: home / "plugins" / name for name in PLUGINS}}


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


def bb_catalog_agent(home: Path) -> None:
    bb = os.environ.get("BB_CLI") or shutil.which("bb")
    if bb is None:
        print("hermes-coder: bb is not on PATH, so bb has no Hermes Coder entry")
        return
    values = json.loads(run(bb, "plugin", "config", "provider-acp", "--json"))["values"]
    custom = [agent for agent in json.loads(values.get("customAgents") or "[]") if agent.get("id") != BB_AGENT["id"]]
    skills = {"path": f"{home.relative_to(Path.home()).as_posix()}/skills", "recursive": True}
    custom.append({**BB_AGENT, "args": ["-p", PROFILE, "acp"], "nativeSkillRoots": {"user": [skills]}})
    run(bb, "plugin", "config", "provider-acp", "set", "customAgents", json.dumps(custom))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 unless the installed profile matches its sources, and change nothing")
    options = parser.parse_args()

    if shutil.which("hermes") is None:
        sys.exit("hermes-coder: the hermes command is not on PATH. Install Hermes Agent first.")
    checkout = HERE.parent.parent
    sources = {PROVIDER: HERE / "plugins" / PROVIDER, **{name: HERE / "plugins" / name for name in PLUGINS}}
    home = Path.home() / ".hermes" / "profiles" / PROFILE
    wanted = fingerprint(sources, {"installer": Path(__file__).read_bytes(), "config": json.dumps(CONFIG)})
    stamp = level.state_dir() / f"hermes-{PROFILE}.json"
    previous = json.loads(stamp.read_text(encoding="utf-8")) if stamp.is_file() else {}

    if options.check:
        if not previous:
            sys.exit(f"hermes-coder: profile {PROFILE} has no install record. Run `mise run hermes:coder`")
        if wanted != previous.get("wanted"):
            sys.exit(f"hermes-coder: profile {PROFILE} is out of date: its sources changed since the install "
                     f"from {previous.get('commit', '?')[:12]}")
        if fingerprint(plugin_targets(home), {}) != previous.get("loaded"):
            sys.exit(f"hermes-coder: profile {PROFILE} is out of date: its plugin files changed since the last install")
        print(f"hermes-coder: profile {PROFILE} matches its sources, installed from {previous['commit'][:12]}")
        return

    warning = level.install_source_warning(checkout)
    if warning:
        print(f"hermes-coder: {warning}", file=sys.stderr)
    if subprocess.run(["hermes", "profile", "show", PROFILE], capture_output=True).returncode != 0:
        run("hermes", "profile", "create", PROFILE, "--no-skills", "--no-credentials", "--no-alias")
    if not home.is_dir():
        sys.exit(f"hermes-coder: profile home {home} not found after creating the profile")

    for name, target in plugin_targets(home).items():
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(sources[name], target, ignore=shutil.ignore_patterns("__pycache__"))
    current = subprocess.run(["hermes", "-p", PROFILE, "config", "get", "model.provider", "--json"],
                             capture_output=True, text=True)
    first_use_of_provider = current.returncode != 0 or json.loads(current.stdout or "null") != PROVIDER
    if first_use_of_provider:
        run("hermes", "-p", PROFILE, "config", "set", "model.default", DEFAULT_MODEL)
    for key, value in CONFIG.items():
        run("hermes", "-p", PROFILE, "config", "set", key, value)
    for name in PLUGINS:
        run("hermes", "-p", PROFILE, "plugins", "enable", name, "--no-allow-tool-override")
    lines = run("hermes", "-p", PROFILE, "claude-code", "reload").strip().splitlines()
    answer = json.loads(lines[-1]) if lines else None
    if answer is not None and not answer.get("reloaded"):
        sys.exit(f"hermes-coder: the running gateway did not reload profile {PROFILE}'s plugins: "
                 f"{answer.get('error') or 'no reason given'}")
    bb_catalog_agent(home)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps({
        "commit": run("git", "-C", str(checkout), "rev-parse", "HEAD").strip(),
        "wanted": wanted,
        "loaded": fingerprint(plugin_targets(home), {}),
    }, indent=2) + "\n", encoding="utf-8")
    model = json.loads(run("hermes", "-p", PROFILE, "config", "get", "model.default", "--json") or "null")
    print(f"hermes-coder: profile {PROFILE} at {home} uses {PROVIDER}, default model {model}")
    print(f"hermes-coder: enabled plugins {', '.join(PLUGINS)}")


if __name__ == "__main__":
    main()

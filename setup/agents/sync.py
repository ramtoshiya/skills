"""Reconcile agent packages and registered Claude profiles."""

import argparse
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hook_binary  # noqa: E402
import level  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
IGNORED = {".git", "__pycache__", ".DS_Store", ".in_use"}
PREFERENCES_BEGIN = b"<!-- BEGIN ramtoshiya:preferences -->"
PREFERENCES_END = b"<!-- END ramtoshiya:preferences -->"
PREFERENCES_HINT = re.compile(rb"ramtoshiya:preferences|<!--\s*(?:BEGIN|END)\s+ramtoshiya\b", re.IGNORECASE)


class Conflict(Exception):
    pass


ERRORS = (Conflict, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False, timeout=300)
    if result.returncode:
        raise Conflict(f"{args[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


class CodexAppServer:
    def __enter__(self):
        self.process = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True)
        self.requests = 0
        self.call("initialize", {"clientInfo": {"name": "ramtoshiya-agents-sync", "version": "1"}})
        self.send({"method": "initialized"})
        return self

    def __exit__(self, *_):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def call(self, method, params):
        self.requests += 1
        self.send({"id": self.requests, "method": method, "params": params})
        for line in self.process.stdout:
            message = json.loads(line)
            if message.get("id") != self.requests:
                continue
            if "error" in message:
                raise Conflict(f"codex app-server {method} failed: {message['error'].get('message')}")
            return message["result"]
        raise Conflict(f"codex app-server exited during {method}")

    def plugin_hooks(self, plugin_id, cwd):
        data = self.call("hooks/list", {"cwds": [str(cwd)]})["data"]
        return [hook for entry in data for hook in entry["hooks"] if hook.get("pluginId") == plugin_id]

    def trust(self, hooks):
        approvals = {hook["key"]: {"trusted_hash": hook["currentHash"]} for hook in hooks}
        self.call("config/batchWrite", {
            "edits": [{"keyPath": "hooks.state", "value": approvals, "mergeStrategy": "upsert"}],
            "reloadUserConfig": True,
        })


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, data):
    write_bytes(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())


def write_bytes(path, data):
    if path.is_symlink():
        raise Conflict(f"Refusing to replace a symlinked configuration file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def reconcile_instructions(actual, source, path):
    begins = actual.count(PREFERENCES_BEGIN)
    ends = actual.count(PREFERENCES_END)
    hints = len(PREFERENCES_HINT.findall(actual))
    if not begins and not ends and not hints:
        separator = b"\n" if actual and not actual.endswith(b"\n") else b""
        prefix = actual + separator + PREFERENCES_BEGIN
        suffix = PREFERENCES_END + b"\n"
    elif begins == 1 and ends == 1 and hints == 2 and actual.index(PREFERENCES_BEGIN) < actual.index(PREFERENCES_END):
        start = actual.index(PREFERENCES_BEGIN) + len(PREFERENCES_BEGIN)
        end = actual.index(PREFERENCES_END)
        prefix, suffix = actual[:start], actual[end:]
    else:
        raise Conflict(f"Malformed or duplicate managed instruction markers in {path}")
    body = b"\n" + source + (b"" if source.endswith(b"\n") else b"\n")
    return prefix + body + suffix


def preferences_source(root):
    path = root / "setup/agents/preferences.md"
    try:
        source = path.read_bytes()
    except OSError as error:
        raise Conflict(f"Cannot use instructions source: {path}") from error
    if PREFERENCES_HINT.search(source):
        raise Conflict(f"Cannot use instructions source: {path}")
    return source


def reconcile_instructions_file(path, source, apply):
    try:
        actual = path.read_bytes() if path.exists() or path.is_symlink() else b""
    except OSError as error:
        raise Conflict(f"Cannot read instructions file: {path}") from error
    merged = reconcile_instructions(actual, source, path)
    if merged == actual:
        return "ok"
    if apply:
        write_bytes(path, merged)
        return "updated"
    return "drift"


def settings_json(path, missing=None):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Invalid JSON constant")

    try:
        if not path.exists() and not path.is_symlink():
            if missing is not None:
                return deepcopy(missing)
            raise Conflict(f"Missing JSON file: {path}")
        data = json.loads(path.read_text(), object_pairs_hook=unique_keys, parse_constant=invalid_constant)
    except (ValueError, UnicodeError) as error:
        raise Conflict(f"Invalid JSON in {path}") from error
    except OSError as error:
        raise Conflict(f"Cannot read JSON file: {path}") from error
    if not isinstance(data, dict):
        raise Conflict(f"Expected a JSON object in {path}")
    return data


def same_value(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def overlay_settings(base, layer, prefix=""):
    result = deepcopy(base)
    for key, value in layer.items():
        name = f"{prefix}.{key}" if prefix else key
        old = result.get(key)
        if isinstance(old, dict) and isinstance(value, dict):
            result[key] = overlay_settings(old, value, name)
        elif isinstance(old, list) and isinstance(value, list):
            result[key] = old + [item for item in value if not any(same_value(item, entry) for entry in old)]
        elif name == "permissions" and isinstance(old, dict):
            raise Conflict(f"Expected an object in profile settings: {name}")
        elif name == "permissions.deny" and isinstance(old, list):
            raise Conflict(f"Expected an array in profile settings: {name}")
        else:
            result[key] = deepcopy(value)
    return result


def reconcile_settings(actual, expected, path, prefix=""):
    result = deepcopy(actual)
    changed = []
    for key, required in expected.items():
        name = f"{prefix}.{key}" if prefix else key
        present = key in result
        current = result.get(key)
        if isinstance(required, dict):
            if present and not isinstance(current, dict):
                raise Conflict(f"Expected an object at {path}: {name}")
            merged, nested = reconcile_settings(current if present else {}, required, path, name)
            if nested:
                result[key] = merged
                changed.extend(nested)
        elif isinstance(required, list):
            if present and not isinstance(current, list):
                raise Conflict(f"Expected an array at {path}: {name}")
            merged = deepcopy(current) if present else []
            for item in required:
                if not any(same_value(item, entry) for entry in merged):
                    merged.append(deepcopy(item))
            if not present or not same_value(current, merged):
                result[key] = merged
                changed.append(name)
        else:
            if present and isinstance(current, (dict, list)):
                raise Conflict(f"Expected a scalar at {path}: {name}")
            if not present or not same_value(current, required):
                result[key] = deepcopy(required)
                changed.append(name)
    return result, changed


class ClaudeSettings:
    def __init__(self, root, record):
        self.root = root
        self.record = record
        self.home = Path.home()
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or self.home / ".config")
        self.registry = config_home / "ramtoshiya/claude-profiles.json"
        self.default = (self.home / ".claude").resolve()

    def profiles(self):
        profiles = {self.default: ("default", {})}
        registry = settings_json(self.registry, {"version": 1, "profiles": {}})
        if (set(registry) != {"version", "profiles"} or type(registry["version"]) is not int
                or registry["version"] != 1 or not isinstance(registry["profiles"], dict)):
            raise Conflict(f"Invalid registry structure in {self.registry}")
        registered = set()
        for name, entry in registry["profiles"].items():
            if (not name.strip() or not isinstance(entry, dict) or "configDir" not in entry
                    or set(entry) - {"configDir", "overrides"} or not isinstance(entry.get("overrides", {}), dict)):
                raise Conflict(f"Invalid profile in {self.registry}")
            directory = entry["configDir"]
            if (not isinstance(directory, str) or not directory
                    or not (directory.startswith("~/") or Path(directory).is_absolute())):
                raise Conflict(f"Profile configDir must be absolute or start with ~/ in {self.registry}")
            path = Path(directory).expanduser().resolve()
            if path in registered:
                raise Conflict(f"Duplicate profile directory in {self.registry}: {path}")
            registered.add(path)
            profiles[path] = (name, entry.get("overrides", {}))
        return profiles

    def unregistered(self, profiles):
        candidates = {path.parent.resolve() / "settings.json" for path in self.home.glob(".claude*/settings.json")}
        active = os.environ.get("CLAUDE_CONFIG_DIR")
        if active:
            candidates.add(Path(active).expanduser().resolve() / "settings.json")
        managed = {path / "settings.json" for path in profiles}
        return sorted(candidates - managed)

    def process(self, apply=False):
        try:
            profiles = self.profiles()
            common = settings_json(self.root / "setup/agents/claude-settings.json")
            terminal = settings_json(self.root / "setup/agents/claude-terminal-settings.json")
            unregistered = self.unregistered(profiles)
        except (Conflict, OSError) as error:
            self.record("claude", "settings", "conflict", str(error))
            return
        expected_profiles = {}
        for directory, (label, overrides) in profiles.items():
            try:
                expected = overlay_settings(common, terminal) if directory == self.default else common
                expected_profiles[directory] = overlay_settings(expected, overrides)
            except Conflict as error:
                self.record("claude", f"settings:{label}", "conflict", str(error))
                return
        try:
            source, source_error = preferences_source(self.root), None
        except Conflict as error:
            source, source_error = None, str(error)
        for directory, (label, overrides) in profiles.items():
            path = directory / "settings.json"
            try:
                actual = settings_json(path, {})
                merged, changed = reconcile_settings(actual, expected_profiles[directory], path)
                if apply and changed:
                    write_json(path, merged)
                status = ("updated" if apply else "drift") if changed else "ok"
                detail = str(path)
                if overrides:
                    _, override_keys = reconcile_settings({}, overrides, path)
                    detail += " (local overrides: " + ", ".join(override_keys) + ")"
                if changed:
                    detail += ": " + ", ".join(changed)
                self.record("claude", f"settings:{label}", status, detail)
            except (Conflict, OSError) as error:
                self.record("claude", f"settings:{label}", "conflict", str(error))
            path = directory / "CLAUDE.md"
            try:
                if source_error:
                    raise Conflict(source_error)
                self.record("claude", f"instructions:{label}", reconcile_instructions_file(path, source, apply), str(path))
            except (Conflict, OSError) as error:
                self.record("claude", f"instructions:{label}", "conflict", str(error))
        for path in unregistered:
            self.record("claude", "settings:unregistered", "drift",
                        f"{path}: register its configDir in {self.registry}")


def relative_path(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise Conflict(f"Expected a relative path, got {value!r}")
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def files(path):
    if not path.is_dir():
        raise Conflict(f"Missing directory: {path}")
    result = {}
    for item in sorted(path.rglob("*")):
        relative = item.relative_to(path)
        if any(part in IGNORED for part in relative.parts) or item.suffix == ".pyc":
            continue
        if item.is_symlink():
            result[str(relative)] = "link:" + str(item.readlink())
        elif item.is_file():
            result[str(relative)] = digest(item.read_bytes())
    return result


def fingerprint(mapping):
    return digest(json.dumps(mapping, sort_keys=True).encode())


def different(actual, expected):
    return sorted(key for key in actual.keys() | expected.keys() if actual.get(key) != expected.get(key))


def git_files(repository, ref, prefix):
    prefix = str(relative_path(prefix)).rstrip("/")
    result = subprocess.run(
        ["git", "-C", str(repository), "archive", ref, prefix],
        capture_output=True, check=False, timeout=60,
    )
    if result.returncode:
        raise Conflict(f"Cannot read {ref[:12]}:{prefix} from {repository}")
    mapping = {}
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        for member in archive:
            if not member.name.startswith(prefix + "/"):
                continue
            name = member.name[len(prefix) + 1:]
            relative_path(name)
            if member.issym():
                mapping[name] = "link:" + member.linkname
            elif member.isfile():
                mapping[name] = digest(archive.extractfile(member).read())
    return mapping


def build_outputs(prefix):
    return [Path(output).relative_to(prefix) for output in hook_binary.OUTPUTS if Path(output).is_relative_to(prefix)]


@dataclass
class Package:
    entry: dict
    root: Path
    repository: Path
    ref: str
    prefix: str
    generated: dict = field(default_factory=dict)

    @property
    def expected(self):
        return {**git_files(self.repository, self.ref, self.prefix), **self.generated}

    def check(self):
        changed = different(files(self.root), self.expected)
        if changed:
            raise Conflict(f"Modified source {self.root}: {', '.join(changed[:5])}")

    def skills(self):
        selected = self.entry.get("skills")
        if selected is not None:
            paths = [self.root / relative_path(value) for value in selected]
        else:
            paths = sorted((self.root / "skills").glob("*/"))
        for path in paths:
            if not (path / "SKILL.md").is_file():
                raise Conflict(f"Missing skill: {path / 'SKILL.md'}")
        if not paths:
            raise Conflict(f"No skills found in {self.root}")
        return paths


class Sources:
    def __init__(self, root, state_dir):
        self.root = root
        self.directory = state_dir / "sources"
        self.history = {}

    def approved_refs(self, entry):
        name = entry["name"]
        if name in self.history:
            return self.history[name]
        source = entry["source"]
        if isinstance(source, str):
            refs = run("git", "-C", str(self.root), "log", "--format=%H", "--", source).splitlines()
            refs.insert(0, run("git", "-C", str(self.root), "rev-parse", "HEAD").strip())
        else:
            refs = [source["sha"]]
            revisions = run("git", "-C", str(self.root), "log", "--format=%H", "--", ".claude-plugin/marketplace.json").splitlines()
            for revision in revisions:
                manifest = json.loads(run("git", "-C", str(self.root), "show", revision + ":.claude-plugin/marketplace.json"))
                for old_entry in manifest["plugins"]:
                    old = old_entry["source"]
                    if old_entry["name"] == name and isinstance(old, dict) and old["url"] == source["url"] and old["path"] == source["path"]:
                        refs.append(old["sha"])
        self.history[name] = list(dict.fromkeys(refs))
        return self.history[name]

    def referenced(self, entry, checkout, ref):
        if ref not in self.approved_refs(entry):
            raise Conflict(f"Source revision {ref} was not approved in the marketplace")
        if run("git", "-C", str(checkout), "rev-parse", "HEAD").strip() != ref:
            raise Conflict(f"Checkout at {checkout} is not pinned to {ref}")
        prefix = str(relative_path(entry["source"]["path"]))
        package = Package(entry, checkout / prefix, checkout, ref, prefix)
        package.check()
        return package

    def package(self, entry, fetch=False, ref=None):
        source = entry["source"]
        if isinstance(source, str):
            prefix = str(relative_path(source))
            directory = self.root / prefix
            if ref:
                return Package(entry, directory, self.root, ref, prefix)
            revision = run("git", "-C", str(self.root), "rev-parse", "HEAD").strip()
            generated = {str(name): digest((directory / name).read_bytes())
                         for name in build_outputs(prefix) if (directory / name).is_file()}
            return Package(entry, directory, self.root, revision, prefix, generated)
        revision = ref or source["sha"]
        repo = source["url"]
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise Conflict("Sources must use a GitHub owner/repository and a full commit SHA")
        prefix = str(relative_path(source["path"]))
        suffix = Path(repo) / revision
        target = self.directory / suffix
        if (target / ".git").exists():
            actual = run("git", "-C", str(target), "rev-parse", "HEAD").strip()
            if actual != revision:
                raise Conflict(f"Checkout at {target} is not pinned to {revision}")
            return Package(entry, target / prefix, target, revision, prefix)
        if not fetch:
            raise Conflict(f"Source {repo}@{revision[:12]} not cached, run agents:sync")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise Conflict(f"Unrecognized source directory: {target}")
        with tempfile.TemporaryDirectory(dir=target.parent) as directory:
            staging = Path(directory) / "checkout"
            run("git", "init", "-q", str(staging))
            run("git", "-C", str(staging), "remote", "add", "origin", f"https://github.com/{repo}.git")
            run("git", "-C", str(staging), "fetch", "--depth=1", "origin", revision)
            run("git", "-C", str(staging), "-c", "core.hooksPath=/dev/null", "checkout", "--detach", revision)
            staging.rename(target)
        return Package(entry, target / prefix, target, revision, prefix)


class Sync:
    def __init__(self, root=ROOT, settings_only=False):
        root = root.resolve()
        self.root = root
        home = Path.home()
        self.homes = {
            "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")),
            "codex": Path(os.environ.get("CODEX_HOME", home / ".codex")),
        }
        self.state_dir = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state")) / "ramtoshiya-agents"
        self.state_path = self.state_dir / "state.json"
        self.settings_only = settings_only
        if not settings_only:
            self.state = read_json(self.state_path, {"version": 1, "packages": {}})
            if self.state.get("version") != 1:
                raise Conflict("Unsupported ownership state version")
            self.marketplace = read_json(root / ".claude-plugin/marketplace.json")
            self.policy = read_json(root / "setup/agents/hosts.json")
            self.sources = Sources(root, self.state_dir)
        self.results = []

    def record(self, host, name, status, detail):
        self.results.append({"host": host, "component": name, "status": status, "detail": detail})

    def save(self):
        if read_json(self.state_path) != self.state:
            write_json(self.state_path, self.state)

    def owned(self, host, name):
        return self.state["packages"].get(f"{host}:{name}")

    def remember(self, host, name, path, package, **extra):
        self.state["packages"][f"{host}:{name}"] = {
            "path": str(path), "fingerprint": fingerprint(files(path)), "pin": package.ref,
            **extra,
        }
        self.save()

    def check_owned(self, host, name, path):
        previous = self.owned(host, name)
        if previous and (previous["path"] != str(path) or previous["fingerprint"] != fingerprint(files(path))):
            raise Conflict(f"Locally changed managed installation: {path}")
        return previous

    def native_files(self, entry, path, expected):
        actual = files(path)
        # Codex synthesizes a manifest for marketplace skill collections.
        manifest = ".codex-plugin/plugin.json"
        if manifest not in expected and manifest in actual:
            data = read_json(path / manifest)
            if data.get("name") != entry["name"] or data.get("skills") != entry.get("skills"):
                raise Conflict(f"Unexpected generated manifest in {path}")
            if any(key in data for key in ["hooks", "mcpServers", "apps", "commands", "agents"]):
                raise Conflict(f"Unexpected capabilities in {path / manifest}")
            del actual[manifest]
        return actual

    def adopt_native(self, host, entry, path, package, installed_ref, fetch):
        expected = package.expected
        if self.native_files(entry, path, expected) == expected:
            return
        previous = self.check_owned(host, entry["name"], path)
        if previous:
            return
        refs = [package.ref]
        refs.extend(self.sources.approved_refs(entry))
        if installed_ref in refs:
            refs.remove(installed_ref)
            refs.insert(0, installed_ref)
        for ref in dict.fromkeys(refs):
            if not ref:
                continue
            try:
                old = self.sources.package(entry, fetch=fetch, ref=ref)
                expected = old.expected
            except Conflict:
                continue
            if self.native_files(entry, path, expected) == expected:
                return
        raise Conflict(f"Unrecognized or modified installation: {path}. Preserve local edits before syncing")

    def marketplace_setup(self, host, apply):
        if host == "claude":
            marketplaces = json.loads(run(host, "plugin", "marketplace", "list", "--json"))
            existing = next((row for row in marketplaces if row["name"] == self.marketplace["name"]), None)
            location = existing.get("path") or existing.get("installLocation") if existing else None
        else:
            marketplaces = json.loads(run(host, "plugin", "marketplace", "list", "--json"))["marketplaces"]
            existing = next((row for row in marketplaces if row["name"] == self.marketplace["name"]), None)
            location = existing.get("root") if existing else None
        if existing and Path(location).resolve() != self.root:
            raise Conflict(f"Marketplace {self.marketplace['name']} is not this checkout: {location}")
        if not existing:
            if not apply:
                raise Conflict("Local marketplace is missing, run agents:sync")
            run(host, "plugin", "marketplace", "add", str(self.root))
        if host == "claude":
            self.inventory = json.loads(run(host, "plugin", "list", "--json"))
        else:
            self.inventory = json.loads(run(host, "plugin", "list", "--json", "--marketplace", self.marketplace["name"]))["installed"]

    def installed(self, host, entry):
        selector = entry["name"] + "@" + self.marketplace["name"]
        if host == "claude":
            records = [row for row in self.inventory if row["id"] == selector and row["scope"] == "user"]
            if not records:
                return None, False, None
            row = records[0]
            path = Path(row.get("readFromFolder") or row["installPath"])
            data = read_json(self.homes[host] / "plugins/installed_plugins.json", {}).get("plugins", {})
            metadata = next((x for x in data.get(selector, []) if x.get("scope") == "user"), {})
            return path, row["enabled"], metadata.get("gitCommitSha")
        row = next((row for row in self.inventory if row["pluginId"] == selector and row.get("installed")), None)
        if not row:
            return None, False, None
        path = self.homes[host] / "plugins/cache" / self.marketplace["name"] / entry["name"] / row["version"]
        return path, row["enabled"], None

    def native(self, host, entry, package, apply):
        name = entry["name"]
        selector = name + "@" + self.marketplace["name"]
        path, enabled, ref = self.installed(host, entry)
        expected = package.expected
        matches = path is not None and path.is_dir() and self.native_files(entry, path, expected) == expected
        if path and path.exists() and path.resolve() != package.root.resolve():
            self.adopt_native(host, entry, path, package, ref, apply)
        if not apply:
            if not (matches and enabled):
                return "drift", "missing, disabled, or outdated plugin"
            untrusted = self.codex_hooks_left_untrusted(host, selector, path, approve=False)
            if untrusted:
                return "drift", f"Codex has not trusted hooks {untrusted}, run agents:sync"
            return "ok", package.ref[:12]
        changed = not matches or not enabled
        if not matches:
            if host == "claude":
                command = "update" if path else "install"
                run(host, "plugin", command, selector, "--scope", "user")
            else:
                run(host, "plugin", "add", selector)
            self.marketplace_setup(host, False)
            path, enabled, _ = self.installed(host, entry)
        if not enabled:
            if host == "claude":
                run(host, "plugin", "enable", selector, "--scope", "user")
            elif matches:
                run(host, "plugin", "add", selector)
        if changed:
            self.marketplace_setup(host, False)
            path, enabled, _ = self.installed(host, entry)
        if not path or not path.is_dir() or self.native_files(entry, path, expected) != expected or not enabled:
            raise Conflict(f"Native installer did not reconcile {selector}. Close active sessions and retry, do not edit caches")
        self.remember(host, name, path, package)
        untrusted = self.codex_hooks_left_untrusted(host, selector, path, approve=True)
        if untrusted:
            raise Conflict(f"Codex still does not trust hooks {untrusted} of {selector} after approval")
        return "updated" if changed else "ok", "restart the agent" if changed else package.ref[:12]

    def codex_hooks_left_untrusted(self, host, selector, path, approve):
        declared = read_json(path / "hooks/hooks.json", {}).get("hooks") if host == "codex" else None
        if not declared:
            return []
        with CodexAppServer() as server:
            hooks = server.plugin_hooks(selector, self.root)
            if not hooks:
                raise Conflict(f"Codex lists none of the hooks in {path / 'hooks/hooks.json'}")
            untrusted = [hook for hook in hooks if hook["trustStatus"] in {"untrusted", "modified"}]
            if untrusted and approve:
                server.trust(untrusted)
                untrusted = [hook for hook in server.plugin_hooks(selector, self.root)
                             if hook["trustStatus"] in {"untrusted", "modified"}]
            return [hook["key"] for hook in untrusted]

    def retire(self, host, names, apply, selected=None):
        retiring = {
            key for key in self.state["packages"]
            if key.split(":", 1)[0] == host and key.split(":", 1)[1] not in names
            and (selected is None or key.split(":", 1)[1] in selected)
        }
        for key, previous in list(self.state["packages"].items()):
            if key not in retiring:
                continue
            _, name = key.split(":", 1)
            try:
                path = Path(previous["path"])
                self.check_owned(host, name, path)
                if not apply:
                    self.record(host, name, "drift", "no longer declared for this host")
                    continue
                if host == "claude":
                    run(host, "plugin", "uninstall", name + "@" + self.marketplace["name"], "--scope", "user", "--keep-data")
                else:
                    run(host, "plugin", "remove", name + "@" + self.marketplace["name"])
                del self.state["packages"][key]
                self.save()
                self.record(host, name, "updated", "retired managed registration, source checkouts retained")
            except ERRORS as error:
                self.record(host, name, "conflict", str(error))

    def build_hooks(self, apply):
        try:
            if apply:
                return ("updated", "rebuilt from its Go source") if hook_binary.build(self.root) else ("ok", "matches its Go source")
            return {
                "ok": ("ok", "matches its Go source"),
                "drift": ("drift", "differs from its Go source, run agents:sync"),
                "absent": ("drift", "missing, run agents:sync"),
            }[hook_binary.status(self.root)]
        except (hook_binary.BuildError, OSError, subprocess.SubprocessError) as error:
            return "conflict", str(error)

    def process(self, hosts, apply=False, selected=None):
        if selected is not None:
            selected = set(selected)
            known = {entry["name"] for entry in self.marketplace["plugins"]}
            known.update(key.split(":", 1)[1] for key in self.state["packages"])
            if selected - known:
                raise Conflict(f"Unknown plugins: {', '.join(sorted(selected - known))}")
        chosen = [entry for entry in self.marketplace["plugins"] if selected is None or entry["name"] in selected]
        if (self.root / hook_binary.SOURCE).is_dir() and any(
                isinstance(entry["source"], str) and build_outputs(relative_path(entry["source"])) for entry in chosen):
            status, detail = self.build_hooks(apply)
            self.record("build", "ramtoshiya-hooks", status, detail)
            if apply and status == "conflict":
                return self.results
        for host in hosts:
            if not shutil.which(host):
                self.record(host, "host", "absent", "executable not on PATH")
                continue
            try:
                self.marketplace_setup(host, apply)
            except ERRORS as error:
                self.record(host, "marketplace", "conflict", str(error))
                continue
            names = set()
            for entry in self.marketplace["plugins"]:
                name = entry["name"]
                if selected is not None and name not in selected:
                    continue
                if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
                    raise Conflict(f"Invalid plugin name: {name}")
                if host not in self.policy["plugins"].get(name, self.policy["hosts"]):
                    continue
                names.add(name)
                try:
                    package = self.sources.package(entry, fetch=apply)
                    package.check()
                    status, detail = self.native(host, entry, package, apply)
                    self.record(host, name, status, detail)
                except ERRORS as error:
                    self.record(host, name, "conflict", str(error))
            self.retire(host, names, apply, selected)
        return self.results

    @contextmanager
    def lock(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "sync.lock").open("w") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Conflict("Another agent sync is running") from error
            if not self.settings_only:
                self.state = read_json(self.state_path, {"version": 1, "packages": {}})
            yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "sync"])
    parser.add_argument("--host", action="append", choices=["claude", "codex"])
    parser.add_argument("--plugin", action="append", help="check or sync only this plugin (repeatable)")
    parser.add_argument("--settings-only", action="store_true",
                        help="check or sync registered Claude settings and instructions only")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()
    if args.settings_only and args.plugin:
        parser.error("--settings-only cannot be combined with --plugin")
    if args.settings_only and args.host and "claude" not in args.host:
        parser.error("--settings-only requires --host claude, or omit --host")
    try:
        sync = Sync(settings_only=args.settings_only)
        hosts = args.host or (["claude"] if args.settings_only else sync.policy["hosts"])

        def process(apply=False):
            if not args.settings_only:
                sync.process(hosts, apply=apply, selected=args.plugin)
            if args.plugin is None and "claude" in hosts:
                ClaudeSettings(sync.root, sync.record).process(apply=apply)
            return sync.results

        if args.command == "sync":
            with sync.lock():
                results = process(apply=True)
            warning = level.install_source_warning(sync.root)
            if warning:
                print(f"agents:sync: {warning}", file=sys.stderr)
        else:
            results = process()
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for row in results:
                print(f"{row['host']:7} {row['component']:25} {row['status']:10} {row['detail']}")
        return int(any(row["status"] in {"drift", "conflict"} for row in results))
    except ERRORS as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

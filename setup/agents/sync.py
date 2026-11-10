"""Reconcile agent packages and registered Claude profiles."""

import argparse
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
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


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, data):
    if path.is_symlink():
        raise Conflict(f"Refusing to replace a symlinked configuration file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


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
    """Replace the managed block without changing any bytes outside it."""
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
    """Combine defaults and overrides, retaining required entries in arrays."""
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
    """Return merged settings and changed key paths without exposing values."""
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
        source_path = self.root / "setup/agents/preferences.md"
        try:
            source = source_path.read_bytes()
            if PREFERENCES_HINT.search(source):
                raise Conflict(f"Managed instruction markers in source: {source_path}")
            source_error = None
        except (Conflict, OSError):
            source = None
            source_error = f"Cannot use instructions source: {source_path}"
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
                try:
                    actual = path.read_bytes() if path.exists() or path.is_symlink() else b""
                except OSError as error:
                    raise Conflict(f"Cannot read instructions file: {path}") from error
                merged = reconcile_instructions(actual, source, path)
                changed = merged != actual
                if apply and changed:
                    write_bytes(path, merged)
                status = ("updated" if apply else "drift") if changed else "ok"
                self.record("claude", f"instructions:{label}", status, str(path))
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
    """Read committed bytes without extracting or executing upstream files."""
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


@dataclass
class Package:
    root: Path
    repository: Path
    ref: str
    prefix: str

    @property
    def expected(self):
        return git_files(self.repository, self.ref, self.prefix)

    def check(self):
        changed = different(files(self.root), self.expected)
        if changed:
            raise Conflict(f"Modified source {self.root}: {', '.join(changed[:5])}")


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

    def package(self, entry, fetch=False, ref=None):
        source = entry["source"]
        if isinstance(source, str):
            prefix = str(relative_path(source))
            revision = ref or run("git", "-C", str(self.root), "rev-parse", "HEAD").strip()
            return Package(self.root / prefix, self.root, revision, prefix)
        revision = ref or source["sha"]
        repo = source["url"]
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise Conflict("Sources must use a GitHub owner/repository and a full commit SHA")
        prefix = str(relative_path(source["path"]))
        suffix = Path(repo) / revision
        candidates = [self.directory / suffix]
        for candidate in candidates:
            if (candidate / ".git").exists():
                actual = run("git", "-C", str(candidate), "rev-parse", "HEAD").strip()
                if actual != revision:
                    raise Conflict(f"Checkout at {candidate} is not pinned to {revision}")
                return Package(candidate / prefix, candidate, revision, prefix)
        if not fetch:
            raise Conflict(f"Source {repo}@{revision[:12]} not cached, run agents:sync")
        target = candidates[0]
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
        return Package(target / prefix, target, revision, prefix)


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
            return ("ok", package.ref[:12]) if matches and enabled else ("drift", "missing, disabled, or outdated plugin")
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
        detail = "restart the agent" if changed else package.ref[:12]
        if host == "codex" and (path / "hooks").is_dir():
            detail += ". Review hook trust in /hooks (never granted by sync)"
        return "updated" if changed else "ok", detail

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
                elif host == "codex":
                    run(host, "plugin", "remove", name + "@" + self.marketplace["name"])
                del self.state["packages"][key]
                self.save()
                self.record(host, name, "updated", "retired managed registration, source checkouts retained")
            except ERRORS as error:
                self.record(host, name, "conflict", str(error))

    def process(self, hosts, apply=False, selected=None):
        if selected is not None:
            selected = set(selected)
            known = {entry["name"] for entry in self.marketplace["plugins"]}
            known.update(key.split(":", 1)[1] for key in self.state["packages"])
            if selected - known:
                raise Conflict(f"Unknown plugins: {', '.join(sorted(selected - known))}")
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
    parser.add_argument("--settings-only", action="store_true", help="check or sync registered Claude settings and instructions only")
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
            if "claude" in hosts and args.plugin is None:
                ClaudeSettings(sync.root, sync.record).process(apply=apply)
            return sync.results

        if args.command == "sync":
            with sync.lock():
                results = process(apply=True)
        else:
            results = process()
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for row in results:
                print(f"{row['host']:7} {row['component']:25} {row['status']:10} {row['detail']}")
        return int(any(row["status"] in {"drift", "conflict", "approval"} for row in results))
    except ERRORS as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

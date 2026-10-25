"""Reconcile this checkout's agent packages without owning unrelated settings."""

import argparse
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
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
IGNORED = {".git", "__pycache__", ".DS_Store", ".in_use"}


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
            temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


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
    entry: dict
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
    def __init__(self, root, homes, state_dir):
        self.root = root
        self.homes = homes
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

    def require_approved(self, entry, ref):
        if ref != entry["source"]["sha"] and ref not in self.approved_refs(entry):
            raise Conflict(f"Source revision {ref} was not approved in the marketplace")

    def referenced(self, entry, checkout, ref):
        self.require_approved(entry, ref)
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
            revision = ref or run("git", "-C", str(self.root), "rev-parse", "HEAD").strip()
            return Package(entry, self.root / prefix, self.root, revision, prefix)
        revision = ref or source["sha"]
        repo = source["url"]
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise Conflict("Sources must use a GitHub owner/repository and a full commit SHA")
        prefix = str(relative_path(source["path"]))
        suffix = Path(repo) / revision
        candidates = [self.directory / suffix]
        candidates += [home / "skill-sources" / suffix for home in self.homes.values()]
        for candidate in candidates:
            if (candidate / ".git").exists():
                actual = run("git", "-C", str(candidate), "rev-parse", "HEAD").strip()
                if actual != revision:
                    raise Conflict(f"Checkout at {candidate} is not pinned to {revision}")
                return Package(entry, candidate / prefix, candidate, revision, prefix)
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
        return Package(entry, target / prefix, target, revision, prefix)


def reconcile_array(current, previous, desired):
    """Remove only previously owned entries, retaining unrelated order and values."""
    if not isinstance(current, list):
        raise Conflict("Expected a settings array")
    missing = [item for item in previous if item not in current]
    if missing:
        raise Conflict("Previously managed settings entries were removed or changed")
    result = [item for item in current if item not in previous or item in desired]
    result.extend(item for item in desired if item not in result)
    return result


class Sync:
    def __init__(self, root=ROOT):
        root = root.resolve()
        self.root = root
        home = Path.home()
        self.homes = {
            "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")),
            "codex": Path(os.environ.get("CODEX_HOME", home / ".codex")),
            "pi": Path(os.environ.get("PI_CODING_AGENT_DIR", home / ".pi/agent")),
            "hermes": Path(os.environ.get("HERMES_HOME", home / ".hermes")),
        }
        self.state_dir = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state")) / "ramtoshiya-agents"
        self.state_path = self.state_dir / "state.json"
        self.state = read_json(self.state_path, {"version": 1, "packages": {}})
        if self.state.get("version") != 1:
            raise Conflict("Unsupported ownership state version")
        self.marketplace = read_json(root / ".claude-plugin/marketplace.json")
        self.policy = read_json(root / "setup/agents/hosts.json")
        self.sources = Sources(root, self.homes, self.state_dir)
        self.results = []
        self.hermes_inventory = None

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

    def pi(self, entry, package, apply):
        host = "pi"
        name = entry["name"]
        home = self.homes[host]
        path = home / "settings.json"
        before = path.read_bytes() if path.exists() else None
        settings = read_json(path, {})
        previous = self.owned(host, name)
        desired = {"skills": [], "extensions": [], "packages": []}
        if isinstance(entry["source"], str):
            desired["packages"] = [str(self.root)]
        else:
            desired["skills"] = [str(p) for p in package.skills()]
            extension = package.root / "hooks/pi.ts"
            if extension.exists():
                desired["extensions"] = [str(extension)]
        old = previous.get("settings", {}) if previous else {key: [] for key in desired}
        if previous:
            old_path = Path(previous["path"])
            if old_path.resolve() != package.root.resolve() or previous["pin"] == package.ref:
                self.check_owned(host, name, old_path)
        else:
            # Adopt only paths in the documented layout whose bytes match their pin.
            for key in desired:
                for item in settings.get(key, []):
                    if not isinstance(item, str):
                        continue
                    absolute = (home / item).resolve()
                    if isinstance(entry["source"], str):
                        if key == "packages" and absolute == self.root:
                            old[key].append(item)
                        continue
                    source = entry["source"]
                    match = re.search(r"/skill-sources/" + re.escape(source["url"]) + r"/([0-9a-f]{40})/", str(absolute))
                    if not match:
                        continue
                    checkout = Path(str(absolute)[:match.end()])
                    if not absolute.is_relative_to((checkout / relative_path(source["path"])).resolve()):
                        continue
                    old_package = self.sources.referenced(entry, checkout, match[1])
                    if absolute in [p.resolve() for p in old_package.skills()] or absolute == (old_package.root / "hooks/pi.ts").resolve():
                        old[key].append(item)
        updated = dict(settings)
        for key, values in desired.items():
            if old.get(key) or values:
                updated[key] = reconcile_array(settings.get(key, []), old.get(key, []), values)
        changed = updated != settings
        if not apply:
            return "drift" if changed else "ok", "settings differ" if changed else package.ref[:12]
        if changed:
            if (path.read_bytes() if path.exists() else None) != before:
                raise Conflict(f"Settings changed during sync: {path}")
            write_json(path, updated)
        self.remember(host, name, package.root, package, settings=desired)
        return "updated" if changed else "ok", "run /reload in Pi" if changed else package.ref[:12]

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

    def hermes_enabled(self):
        if self.hermes_inventory is None:
            output = run("hermes", "plugins", "list", "--user", "--json")
            try:
                self.hermes_inventory = json.loads(output)
            except ValueError:
                # Hermes prints a human message instead of JSON for an empty inventory.
                if any((self.homes["hermes"] / "plugins").glob("*/plugin.yaml")):
                    raise Conflict("Hermes returned an invalid plugin inventory")
                self.hermes_inventory = []
        return [row["name"] for row in self.hermes_inventory if row["status"] == "enabled"]

    def install_link(self, path, target):
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_name(path.name + ".sync-link")
        if staging.exists() or staging.is_symlink():
            raise Conflict(f"Unexpected staging link: {staging}")
        staging.symlink_to(target, target_is_directory=True)
        backup = None
        try:
            if path.exists() and not path.is_symlink():
                backups = self.state_dir / "backups"
                backups.mkdir(parents=True, exist_ok=True)
                backup = Path(tempfile.mkdtemp(prefix=path.name + "-", dir=backups)) / path.name
                path.rename(backup)
            os.replace(staging, path)
        except OSError:
            if backup is not None and backup.exists() and not path.exists():
                backup.rename(path)
            raise
        finally:
            if staging.is_symlink():
                staging.unlink()

    def hermes(self, entry, package, apply):
        host = "hermes"
        name = entry["name"]
        home = self.homes[host]
        enabled = name in self.hermes_enabled()
        native = (package.root / "plugin.yaml").exists()
        path = home / ("skills" if name == "open-pencil" else "plugins") / ("open-pencil" if name == "open-pencil" else name)
        if name == "open-pencil":
            source = package.skills()[0]
            expected = files(source)
            if path.exists():
                self.check_owned(host, name, path)
                if not self.owned(host, name) and files(path) != expected:
                    raise Conflict(f"Locally modified standalone skill: {path}")
            matches = path.exists() and files(path) == expected
            if apply and not matches:
                self.install_link(path, source)
            enabled = True
        elif native:
            if path.is_symlink() and not path.exists():
                raise Conflict(f"Broken plugin link: {path}")
            if path.exists():
                if path.resolve() != package.root.resolve():
                    self.adopt_native(host, entry, path, package, None, apply)
            matches = path.exists() and files(path) == package.expected
            if apply and not matches:
                self.install_link(path, package.root)
        else:
            metadata_path = path / "source.json"
            metadata = read_json(metadata_path)
            managed_adapter = metadata.get("managed_adapter", False) if metadata else True
            template = (self.root / "setup/agents/hermes-skills.py").read_bytes()
            manifest = f"name: {name}\ndescription: Skills from the pinned marketplace source\n"
            if name == "humanize":
                manifest += "provides_hooks:\n  - pre_tool_call\n  - transform_tool_result\n"
            desired = {
                "source": "git-subdir", **entry["source"],
                "checkout": str(package.repository), "root": str(package.root),
                "skills": [str(p.relative_to(package.root)) for p in package.skills()],
                "advisory_hooks": name == "humanize", "managed_adapter": managed_adapter,
            }
            if path.exists():
                self.check_owned(host, name, path)
                if not metadata or metadata.get("url") != entry["source"]["url"] or metadata.get("path") != entry["source"]["path"]:
                    raise Conflict(f"Unrecognized Hermes wrapper: {path}")
                checkout = Path(metadata["root"])
                for _ in relative_path(entry["source"]["path"]).parts:
                    checkout = checkout.parent
                self.sources.referenced(entry, checkout, metadata["sha"])
            matches = metadata is not None and all(metadata.get(k) == desired[k] for k in ["sha", "root", "skills", "advisory_hooks", "managed_adapter"])
            if managed_adapter and path.exists():
                template_matches = (path / "__init__.py").read_bytes() == template and (path / "plugin.yaml").read_text() == manifest
                if not template_matches and not self.owned(host, name):
                    raise Conflict(f"Unrecognized generated Hermes adapter: {path}")
                matches = matches and template_matches
            if apply and not matches:
                path.mkdir(parents=True, exist_ok=True)
                if managed_adapter:
                    (path / "plugin.yaml").write_text(manifest)
                    (path / "__init__.py").write_bytes(template)
                write_json(metadata_path, desired)
        changed = not matches or not enabled
        if apply:
            if changed or not self.owned(host, name):
                if name != "open-pencil":
                    run("hermes", "plugins", "doctor", str(path), "--ci")
                    if not enabled:
                        run("hermes", "plugins", "enable", name, "--no-allow-tool-override")
                        self.hermes_inventory = None
                        if name not in self.hermes_enabled():
                            raise Conflict(f"Hermes did not enable {name}")
            self.remember(host, name, path, package)
            return "updated" if changed else "ok", "restart Hermes" if changed else package.ref[:12]
        return ("ok", package.ref[:12]) if not changed else ("drift", "missing, disabled, or outdated plugin")

    def retire(self, host, names, apply, selected=None):
        for key, previous in list(self.state["packages"].items()):
            owner, name = key.split(":", 1)
            if owner != host or name in names or (selected is not None and name not in selected):
                continue
            try:
                path = Path(previous["path"])
                self.check_owned(host, name, path)
                if not apply:
                    self.record(host, name, "drift", "no longer declared for this host")
                    continue
                if host == "pi":
                    settings_path = self.homes[host] / "settings.json"
                    before = settings_path.read_bytes()
                    settings = read_json(settings_path)
                    for field, entries in previous.get("settings", {}).items():
                        if entries:
                            settings[field] = reconcile_array(settings.get(field, []), entries, [])
                    if settings_path.read_bytes() != before:
                        raise Conflict(f"Settings changed during sync: {settings_path}")
                    write_json(settings_path, settings)
                elif host == "claude":
                    run(host, "plugin", "uninstall", name + "@" + self.marketplace["name"], "--scope", "user", "--keep-data")
                elif host == "codex":
                    run(host, "plugin", "remove", name + "@" + self.marketplace["name"])
                elif name == "open-pencil":
                    if not path.is_symlink():
                        raise Conflict(f"Preserve the standalone skill before removing {path}")
                    path.unlink()
                elif name in self.hermes_enabled():
                    run("hermes", "plugins", "disable", name)
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
                if host in {"claude", "codex"}:
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
                    method = self.pi if host == "pi" else self.hermes if host == "hermes" else self.native
                    status, detail = method(entry, package, apply) if host in {"pi", "hermes"} else method(host, entry, package, apply)
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
            self.state = read_json(self.state_path, {"version": 1, "packages": {}})
            yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "sync"])
    parser.add_argument("--host", action="append", choices=["claude", "codex", "pi", "hermes"])
    parser.add_argument("--plugin", action="append", help="check or sync only this plugin (repeatable)")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()
    try:
        sync = Sync()
        hosts = args.host or sync.policy["hosts"]
        if args.command == "sync":
            with sync.lock():
                results = sync.process(hosts, apply=True, selected=args.plugin)
        else:
            results = sync.process(hosts, selected=args.plugin)
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

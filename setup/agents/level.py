"""Keep origin/main, the shared checkout's main, and this machine's installs level."""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

BRANCH = "main"
REMOTE = "origin"
HOOKS = "setup/git-hooks"
STOPS_HOOK_RERUN = "RAMTOSHIYA_LEVEL"
# A Git hook inherits variables that point Git at the repository and worktree that ran it.
HOOK_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR",
                  "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_PARAMETERS",
                  "GIT_CONFIG_COUNT")
BB_PLUGINS = "bb-plugins"
TOOLS = "tools"
# A plugin that wraps a CLI under tools/ keeps state from it, such as the model list its provider caches, so a
# change to these files rebuilds the plugin even when the plugin's own folder is unchanged.
PLUGIN_INPUTS = {"claudex-native": ("tools/claudex/claudex.cjs",)}


class Stop(Exception):
    pass


class Rebasing(Exception):
    pass


def environment():
    env = {key: value for key, value in os.environ.items()
           if key not in HOOK_VARIABLES and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))}
    return {**env, STOPS_HOOK_RERUN: "1"}


def git(repo, *args, check=True, timeout=120):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, env=environment(), timeout=timeout)
    if check and result.returncode:
        raise Stop(f"`git {' '.join(args[:3])}` failed in {repo}: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip() if check else result


def shared_checkout(path):
    return Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")).parent


@dataclass(frozen=True)
class Checkout:
    path: Path
    branch: str
    head: str
    origin: str
    ahead: int
    behind: int
    changes: tuple

    def why_not_install_source(self):
        if self.branch != BRANCH:
            return f"the shared checkout {self.path} is on {self.branch or 'a detached HEAD'}, not {BRANCH}"
        if self.ahead and self.behind:
            return (f"{BRANCH} in {self.path} is {self.ahead} ahead and {self.behind} behind {REMOTE}/{BRANCH}. "
                    f"Put its own commits on top of {REMOTE}/{BRANCH} and push without force")
        if self.changes:
            shown = ", ".join(self.changes[:5]) + (", ..." if len(self.changes) > 5 else "")
            return f"the shared checkout {self.path} has uncommitted changes: {shown}"
        if self.ahead:
            return f"{BRANCH} in {self.path} has {self.ahead} commits that {REMOTE}/{BRANCH} lacks"
        if self.behind:
            return (f"{BRANCH} in {self.path} is {self.behind} commits behind {REMOTE}/{BRANCH}, "
                    f"so every install from it is behind too")
        return None


def read_checkout(path, origin):
    branch = git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
    head = git(path, "rev-parse", "HEAD")
    if git(path, "cat-file", "-e", f"{origin}^{{commit}}", check=False).returncode:
        ahead, behind = 0, -1
    else:
        behind, ahead = map(int, git(path, "rev-list", "--left-right", "--count", f"{origin}...HEAD").split())
    # Compared with HEAD rather than the index, which a running commit may still hold locked.
    changed = git(path, "diff", "--name-only", "HEAD").splitlines()
    untracked = git(path, "ls-files", "--others", "--exclude-standard").splitlines()
    return Checkout(path, branch, head, origin, ahead, behind, tuple(sorted({*changed, *untracked})))


def install_source_warning(path):
    try:
        shared = shared_checkout(path)
        if Path(path).resolve() != shared:
            return (f"this install reads {path}, which is not the shared checkout {shared}. "
                    f"`mise run main:status` reports the difference until `mise run main:sync` runs")
        origin = git(shared, "rev-parse", "--verify", "--quiet", f"refs/remotes/{REMOTE}/{BRANCH}")
        problem = read_checkout(shared, origin).why_not_install_source()
    except (Stop, OSError, subprocess.SubprocessError) as error:
        return f"could not compare the install source with {REMOTE}/{BRANCH}: {error}"
    if problem:
        return (f"this install reads a tree that is not {REMOTE}/{BRANCH}, because {problem}. "
                f"`mise run main:status` reports the difference")
    return None


def state_dir():
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "ramtoshiya-agents"


class BbPlugins:
    """bb plugins installed from the shared checkout's bb-plugins, rebuilt when their tree changes.

    bb neither rebuilds a path plugin on reload nor stamps its build with the source it read, so the tree each
    install read is recorded here.
    """

    def __init__(self, shared):
        self.shared = shared
        self.record_file = state_dir() / "bb-plugins.json"

    def bb(self, *args):
        result = subprocess.run(["bb", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                env=environment(), timeout=600)
        if result.returncode:
            raise Stop(f"`bb {' '.join(args[:3])}` failed: {(result.stderr or result.stdout).strip()}")
        return result.stdout

    def records(self):
        try:
            return json.loads(self.record_file.read_text())
        except (OSError, ValueError):
            return {}

    def record(self, plugin_id, tree):
        records = {**self.records(), plugin_id: tree}
        self.record_file.parent.mkdir(parents=True, exist_ok=True)
        self.record_file.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")

    def home(self, plugin_id):
        return self.shared / BB_PLUGINS / plugin_id

    def tree(self, plugin_id):
        """Identify what a build of the plugin reads: its folder, then each file in PLUGIN_INPUTS that exists."""
        stamp = [git(self.shared, "rev-parse", f"HEAD:{BB_PLUGINS}/{plugin_id}")]
        for path in PLUGIN_INPUTS.get(plugin_id, ()):
            found = git(self.shared, "rev-parse", "--verify", "--quiet", f"HEAD:{path}", check=False)
            if found.returncode == 0:
                stamp.append(found.stdout.strip())
        return "+".join(stamp)

    def from_this_repository(self):
        """Return (plugin, installed from the shared checkout) for each path plugin this repository provides."""
        worktrees = [Path(line.removeprefix("worktree ")).resolve() for line in
                     git(self.shared, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]
        ours = []
        for plugin in json.loads(self.bb("plugin", "list", "--json"))["plugins"]:
            if not plugin["source"].startswith("path:"):
                continue
            source = Path(plugin["source"].removeprefix("path:")).resolve()
            if source == self.home(plugin["id"]).resolve():
                ours.append((plugin, True))
            elif (self.home(plugin["id"]) / "package.json").is_file() or any(
                    source.is_relative_to(tree) for tree in worktrees):
                ours.append((plugin, False))
        return ours

    def status_rows(self):
        if shutil.which("bb") is None:
            return [row("bb", "plugins", "absent", "bb not on PATH")]
        try:
            plugins = self.from_this_repository()
            records = self.records()
            rows = []
            for plugin, shared in plugins:
                name = f"plugin:{plugin['id']}"
                if not shared:
                    home = self.home(plugin["id"])
                    packages = (f"`npm ci --ignore-scripts --prefix {home}`, then "
                                if (home / "package-lock.json").is_file() else "")
                    move = (f"Move it with {packages}`bb plugin install path:{home} --yes`"
                            if (home / "package.json").is_file()
                            else f"{BRANCH} has no {BB_PLUGINS}/{plugin['id']}")
                    rows.append(row("bb", name, "drift",
                                    f"runs {plugin['source'].removeprefix('path:')}, not the shared checkout. {move}"))
                elif plugin["id"] not in records:
                    rows.append(row("bb", name, "drift", "no record of the tree it was built from"))
                elif records[plugin["id"]] != self.tree(plugin["id"]):
                    rows.append(row("bb", name, "drift", "built from an older tree than the shared checkout"))
                else:
                    rows.append(row("bb", name, "ok", f"built from {self.home(plugin['id'])}"))
            return rows or [row("bb", "plugins", "ok", f"none installed from {BB_PLUGINS}")]
        except (Stop, ValueError, KeyError, subprocess.SubprocessError) as error:
            return [row("bb", "plugins", "conflict", str(error))]

    def install_dependencies(self, plugin_id):
        """Install the lockfile's packages, which the bb build bundles from node_modules."""
        if not (self.home(plugin_id) / "package-lock.json").is_file():
            return
        result = subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=self.home(plugin_id),
                                capture_output=True, text=True, stdin=subprocess.DEVNULL, env=environment(), timeout=600)
        if result.returncode:
            raise Stop(f"`npm ci` failed in {self.home(plugin_id)}: {(result.stderr or result.stdout).strip()}")

    def active_providers(self):
        threads = json.loads(self.bb("thread", "list", "--include-hidden", "--json"))
        return {thread["providerId"] for thread in threads if thread.get("status") == "active"}

    def sync(self):
        failed = []
        try:
            plugins = [plugin for plugin, shared in self.from_this_repository() if shared]
            for plugin in plugins:
                tree = self.tree(plugin["id"])
                if self.records().get(plugin["id"]) == tree:
                    continue
                # A reinstall restarts the provider's worker and with it every turn on that provider.
                busy = set(plugin.get("providerIds") or []) & self.active_providers()
                if busy:
                    print(f"main:sync: postponed {plugin['id']}, which a running {', '.join(sorted(busy))} turn uses. "
                          f"Run `mise run main:sync` after it finishes", file=sys.stderr)
                    failed.append(plugin["id"])
                    continue
                try:
                    self.install_dependencies(plugin["id"])
                    self.bb("plugin", "install", f"path:{self.home(plugin['id'])}", "--yes")
                except Stop as error:
                    print(f"main:sync: {error}", file=sys.stderr)
                    failed.append(plugin["id"])
                    continue
                self.record(plugin["id"], tree)
                print(f"main:sync: reinstalled the bb plugin {plugin['id']}", file=sys.stderr)
        except (Stop, ValueError, KeyError, subprocess.SubprocessError) as error:
            print(f"main:sync: {error}", file=sys.stderr)
            return False
        return not failed


@dataclass(frozen=True)
class Tool:
    """A CLI under tools/ whose install step copies files into place, with the copies a status check compares."""
    name: str
    command: str
    files: tuple

    def install_step(self, shared):
        return shared / TOOLS / self.name / "install.sh"

    def differing(self, shared, home):
        return [source for source, target in self.files
                if not (home / target).is_file()
                or (home / target).read_bytes() != (shared / TOOLS / self.name / source).read_bytes()]


def copies(directory, names):
    return tuple((name, f"{directory}/{name}") for name in names)


CLI_TOOLS = (
    Tool("claudex", ".local/bin/claudex", copies(".local/share/claudex", ["claudex.cjs"])),
    Tool("excalidraw-board", ".local/bin/excalidraw-board", copies(".local/share/excalidraw-board", [
        "excalidraw-board.mjs", "rooms.mjs", "protocol.mjs", "scene.mjs", "images.mjs", "request.mjs",
        "snapshot.mjs", "size-limit.mjs"])),
    Tool("excalidraw-web-export", ".local/bin/excalidraw-web-export", copies(".local/share/excalidraw-web-export", [
        "export.mjs", "size-limit.mjs", "package.json", "package-lock.json", ".npmrc"])),
    Tool("sidecar", ".local/bin/sidecar", copies(".local/share/sidecar/0.1.0", ["sidecar.m"])),
    Tool("windowserver-ports", ".local/bin/windowserver-ports", copies(".local/share/windowserver-ports", [
        "windowserver-ports.mjs", "probe-client.m"])),
    Tool("worktreeinclude", ".local/bin/worktreeinclude", (("worktreeinclude.mjs", ".local/bin/worktreeinclude"),)),
)


class CliTools:
    """CLIs under tools/ that this machine already has, reinstalled when an installed copy differs from the checkout.

    A CLI whose command is not installed is left alone, because installing one is the person's choice.
    """

    def __init__(self, shared, home):
        self.shared = shared
        self.home = home

    def present(self):
        return [tool for tool in CLI_TOOLS
                if tool.install_step(self.shared).is_file() and os.path.lexists(self.home / tool.command)]

    def status_rows(self):
        rows = []
        for tool in CLI_TOOLS:
            if tool not in self.present():
                rows.append(row("cli", tool.name, "absent", "not installed on this machine"))
                continue
            differing = tool.differing(self.shared, self.home)
            rows.append(row("cli", tool.name, "drift" if differing else "ok",
                            f"installed copy differs from the shared checkout in {', '.join(differing)}"
                            if differing else f"{self.home / tool.command}"))
        return rows

    def sync(self):
        failed = []
        for tool in self.present():
            if not tool.differing(self.shared, self.home):
                continue
            result = subprocess.run(["sh", str(tool.install_step(self.shared))], cwd=self.shared, env=environment(),
                                    stdin=subprocess.DEVNULL, text=True, capture_output=True)
            if result.returncode:
                print(f"main:sync: reinstalling {tool.name} failed: {(result.stderr or result.stdout).strip()}",
                      file=sys.stderr)
                failed.append(tool.name)
            else:
                print(f"main:sync: reinstalled the CLI {tool.name}", file=sys.stderr)
        return not failed


def remote_head(shared):
    output = git(shared, "ls-remote", "--exit-code", REMOTE, f"refs/heads/{BRANCH}", timeout=60)
    return output.split()[0]


class Installers:
    def __init__(self, shared):
        self.shared = shared
        self.python = [sys.executable, "-I"]
        self.home = Path.home()

    def run(self, command, check=False, capture=True):
        return subprocess.run(command, cwd=self.shared, env=environment(), stdin=subprocess.DEVNULL,
                              capture_output=capture, text=True, check=check)

    def status_rows(self):
        rows = []
        result = self.run([*self.python, str(self.shared / "setup/agents/sync.py"), "status", "--json"])
        try:
            rows += json.loads(result.stdout)
        except ValueError:
            rows.append(row("agents", "sync.py", "conflict", (result.stderr or result.stdout).strip()))
        if shutil.which("mise"):
            result = self.run(["mise", "-C", str(self.shared), "dotfiles", "status", "--json"])
            try:
                entries = json.loads(result.stdout)
                for entry in [*entries["files"], *entries["edits"]]:
                    if entry["state"] != "applied":
                        label = entry.get("target") or entry.get("id") or "entry"
                        rows.append(row("mise", "dotfiles", "drift", f"{label}: {entry['state']}"))
                if not any(r["host"] == "mise" for r in rows):
                    rows.append(row("mise", "dotfiles", "ok", "every entry applied"))
            except (ValueError, KeyError) as error:
                rows.append(row("mise", "dotfiles", "conflict", (result.stderr or str(error)).strip()))
        else:
            rows.append(row("mise", "dotfiles", "absent", "mise not on PATH"))
        if shutil.which("mise") or (self.home / ".local/bin/takeaturn").exists():
            result = self.run([*self.python, str(self.shared / "setup/agents/takeaturn.py"), "status"])
            try:
                rows += json.loads(result.stdout)
            except ValueError:
                rows.append(row("takeaturn", "cli", "conflict", (result.stderr or result.stdout).strip()))
        else:
            rows.append(row("takeaturn", "cli", "absent", "not installed and mise not on PATH"))
        return rows + CliTools(self.shared, self.home).status_rows() + BbPlugins(self.shared).status_rows()

    def steps(self):
        agents = ("agents:sync", [*self.python, str(self.shared / "setup/agents/sync.py"), "sync"])
        dotfiles = ("mise dotfiles", ["mise", "-C", str(self.shared), "dotfiles", "apply", "--yes"])
        takeaturn = ("takeaturn", [*self.python, str(self.shared / "setup/agents/takeaturn.py"), "install"])
        steps = [agents, *([dotfiles, takeaturn] if shutil.which("mise") else [])]
        steps.append(("cli tools", CliTools(self.shared, self.home).sync))
        if shutil.which("bb"):
            steps.append(("bb plugins", BbPlugins(self.shared).sync))
        return steps


def row(host, component, status, detail):
    return {"host": host, "component": component, "status": status, "detail": detail}


def status(shared):
    rows = []
    try:
        remote = remote_head(shared)
        rows.append(row("origin", BRANCH, "ok", remote[:12]))
    except Stop as error:
        remote = git(shared, "rev-parse", f"refs/remotes/{REMOTE}/{BRANCH}")
        rows.append(row("origin", BRANCH, "conflict", f"cannot reach {REMOTE}, compared with the last fetch: {error}"))
    checkout = read_checkout(shared, remote)
    if checkout.behind < 0:
        problem = f"{REMOTE}/{BRANCH} is at {remote[:12]}, which this machine has not fetched"
    else:
        problem = checkout.why_not_install_source()
    rows.append(row("checkout", BRANCH, "drift" if problem else "ok",
                    problem or f"{checkout.head[:12]} {shared}"))
    rows += Installers(shared).status_rows()
    return rows


@contextmanager
def locked():
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True)
    with (state / "level.lock").open("w") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("main:sync: waiting for another main:sync to finish", file=sys.stderr)
            fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def activate_hooks(shared):
    wanted = str(shared / HOOKS)
    current = git(shared, "config", "--local", "--get", "core.hooksPath", check=False).stdout.strip()
    if current == wanted:
        return
    if current:
        raise Stop(f"core.hooksPath is already {current}. Set it to {wanted} by hand if that is what you want")
    git(shared, "config", "--local", "core.hooksPath", wanted)
    print(f"main:sync: Git now runs the hooks in {wanted} for every worktree of this repository", file=sys.stderr)


def level_main_and_return_target(shared):
    git(shared, "fetch", "--quiet", "--no-prune", "--no-tags", REMOTE, f"+refs/heads/{BRANCH}:refs/remotes/{REMOTE}/{BRANCH}", timeout=300)
    origin = git(shared, "rev-parse", f"refs/remotes/{REMOTE}/{BRANCH}")
    checkout = read_checkout(shared, origin)
    if not checkout.branch and any(Path(git(shared, "rev-parse", "--path-format=absolute", "--git-path", name)).exists()
                                   for name in ("rebase-merge", "rebase-apply")):
        raise Rebasing()
    if checkout.branch != BRANCH or (checkout.ahead and checkout.behind):
        raise Stop(checkout.why_not_install_source())
    if checkout.behind:
        if checkout.changes:
            raise Stop(checkout.why_not_install_source())
        git(shared, "merge", "--ff-only", "--no-overwrite-ignore", "--quiet", origin)
        print(f"main:sync: fast-forwarded {shared} to {origin[:12]}", file=sys.stderr)
    elif checkout.ahead:
        result = git(shared, "push", "--quiet", "--no-follow-tags", REMOTE, f"refs/heads/{BRANCH}:refs/heads/{BRANCH}",
                     check=False, timeout=300)
        if result.returncode:
            raise Stop(f"pushing {BRANCH} from {shared} failed: {(result.stderr or result.stdout).strip()}")
        print(f"main:sync: pushed {checkout.ahead} commits from {shared} to {REMOTE}/{BRANCH}", file=sys.stderr)
    checkout = read_checkout(shared, git(shared, "rev-parse", f"refs/remotes/{REMOTE}/{BRANCH}"))
    problem = checkout.why_not_install_source()
    if problem:
        raise Stop(f"{problem}. Installs wait until it is committed. If you discard it instead, "
                   f"run `mise run main:sync` in {shared}")
    return checkout.head


def stop_unless_still_at_target(shared, target, previous):
    checkout = read_checkout(shared, target)
    during = f"during {previous}, so that install may hold it" if previous else "before the first install"
    if checkout.head != target:
        raise Stop(f"{BRANCH} in {shared} moved to {checkout.head[:12]} {during}. "
                   f"The hook run for that commit installs it")
    if checkout.changes:
        raise Stop(f"{checkout.why_not_install_source()}, which appeared {during}. "
                   f"Commit it, or discard it and run `mise run main:sync`")


def sync(shared):
    with locked():
        activate_hooks(shared)
        target = level_main_and_return_target(shared)
        installers = Installers(shared)
        failed = []
        previous = None
        for name, command in installers.steps():
            stop_unless_still_at_target(shared, target, previous)
            print(f"main:sync: {name}", file=sys.stderr)
            if not (command() if callable(command) else installers.run(command, capture=False).returncode == 0):
                failed.append(name)
            previous = name
        stop_unless_still_at_target(shared, target, previous)
        if failed:
            raise Stop(f"{', '.join(failed)} failed. {REMOTE}/{BRANCH} and the shared checkout are at "
                       f"{target[:12]}, and those installs are not. Fix the error above, then run `mise run main:sync`")
        print(f"main:sync: {REMOTE}/{BRANCH}, {shared}, and the installs are level at {target[:12]}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["status", "sync"])
    parser.add_argument("--json", action="store_true", help="print status rows as JSON")
    args = parser.parse_args()
    try:
        shared = shared_checkout(Path(__file__).resolve().parent)
        if args.command == "status":
            rows = status(shared)
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for item in rows:
                    print(f"{item['host']:8} {item['component']:25} {item['status']:9} {item['detail']}")
            return int(any(item["status"] in {"drift", "conflict"} for item in rows))
        sync(shared)
        return 0
    except Rebasing:
        print("main:sync: a rebase of main is in progress. Its last step runs this again", file=sys.stderr)
        return 0
    except Stop as error:
        print(f"main:sync: STOPPED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

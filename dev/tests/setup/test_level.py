import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_hermes_operator import FAKE_BB, FAKE_HERMES, PSTACK_ALLOWED, commit_repo, skill, under, write_tree

ROOT = Path(__file__).resolve().parents[3]
HANDOFF = "setup/hermes/skills/operator-handoff/SKILL.md"
LEVEL = "setup/agents/level.py"
FAKE_NPM = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["CALLS"], "a") as log:
    log.write(json.dumps({{"args": ["npm", *sys.argv[1:], os.getcwd()]}}) + "\\n")
"""


def uv_python_dir():
    return subprocess.run(["uv", "python", "dir"], capture_output=True, text=True, check=True).stdout.strip()


class LevelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name).resolve()
        self.home = self.tmp / "home"
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, script in {"hermes": FAKE_HERMES, "bb": FAKE_BB, "npm": FAKE_NPM}.items():
            (bin_dir / name).write_text(script)
            (bin_dir / name).chmod(0o755)
        bundled = self.tmp / "bundled"
        write_tree(bundled, under("autonomous-ai-agents", skill("hermes-agent")))
        tools = {str(Path(shutil.which(name)).parent) for name in ("git", "uv")}
        self.env = {
            "HOME": str(self.home), "XDG_STATE_HOME": str(self.tmp / "state"), "FAKE_BUNDLED": str(bundled),
            "PATH": os.pathsep.join([str(bin_dir), *sorted(tools), "/usr/bin", "/bin"]),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "UV_PYTHON_INSTALL_DIR": uv_python_dir(), "UV_CACHE_DIR": str(self.tmp / "uv-cache"),
            "CALLS": str(self.tmp / "bb-calls.jsonl"),
        }
        commit_repo(self.home / "workspaces/pstack-mode", {"plugins/pstack-mode/mode.md": "# Mode\n", **under(
            "plugins/pstack-mode/skills", {k: v for s in PSTACK_ALLOWED for k, v in skill(s).items()})})
        (self.home / ".hermes").mkdir(parents=True)
        subprocess.run([str(bin_dir / "hermes"), "profile", "create", "default"], env=self.env, check=True)
        (self.home / ".hermes/SOUL.md").write_text("Default soul.\n")
        (self.home / "bb-provider-acp.json").write_text(json.dumps({"customAgents": "[]"}))

        setup_files = {str(p.relative_to(ROOT)): p.read_text() for p in (ROOT / "setup").rglob("*")
                       if p.is_file() and p.parts[len(ROOT.parts) + 1] in {"hermes", "agents", "git-hooks"}
                       and "__pycache__" not in p.parts}
        seed = self.tmp / "seed"
        commit_repo(seed, {
            **setup_files,
            ".gitignore": (ROOT / ".gitignore").read_text(),
            ".claude-plugin/marketplace.json": json.dumps({"name": "fixture", "plugins": [
                {"name": "ramtoshiya", "description": "Personal skills.", "source": "./plugins/ramtoshiya"}]}),
            **under("plugins/ramtoshiya/skills", skill("read-x")),
        })
        (seed / "setup/git-hooks/reference-transaction").chmod(0o755)
        self.git(seed, "add", "-A")
        self.git(seed, "commit", "-q", "-m", "executable hook")
        self.git(seed, "branch", "-M", "main")
        self.remote = self.tmp / "remote.git"
        self.git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.remote))
        self.shared = self.tmp / "skills"
        self.git(self.tmp, "clone", "-q", str(self.remote), str(self.shared))
        self.worktree = self.tmp / "worktrees/thr_1/skills"
        self.git(self.shared, "worktree", "add", "-q", "-b", "task", str(self.worktree), "origin/main")
        self.installed = self.home / ".hermes/profiles/operator/skills/operator-handoff/SKILL.md"

        result = self.level("sync", "--hermes")
        self.assertEqual(result.returncode, 0, result.stderr)

    def git(self, cwd, *args, env=None):
        result = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                                cwd=cwd, env=env or self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def run_git(self, cwd, *args, env=None):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                              cwd=cwd, env=env or self.env, capture_output=True, text=True)

    def level(self, *args):
        return subprocess.run([sys.executable, "-I", str(self.shared / LEVEL), *args],
                              env=self.env, capture_output=True, text=True)

    def status(self):
        result = self.level("status", "--json")
        rows = {(row["host"], row["component"]): row for row in json.loads(result.stdout)}
        return result.returncode, rows

    def commit(self, cwd, path, text, env=None):
        (cwd / path).write_text(text)
        self.git(cwd, "add", path, env=env)
        return self.run_git(cwd, "commit", "-q", "-m", f"change {path}", env=env)

    def without_hook(self):
        return {**self.env, "RAMTOSHIYA_LEVEL": "1"}

    def remote_main(self):
        return self.git(self.remote, "rev-parse", "main")

    def test_push_from_a_worktree_reaches_the_shared_checkout_and_the_install(self):
        self.commit(self.worktree, HANDOFF, "pushed from a worktree\n")

        push = self.run_git(self.worktree, "push", "-q", "origin", "HEAD:main")

        self.assertEqual(push.returncode, 0, push.stderr)
        self.assertEqual(self.git(self.shared, "rev-parse", "HEAD"), self.remote_main())
        self.assertIn("pushed from a worktree", self.installed.read_text())
        code, rows = self.status()
        self.assertEqual(code, 0, rows)

    def test_commit_on_shared_main_is_pushed_and_installed(self):
        result = self.commit(self.shared, HANDOFF, "committed on the shared main\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote_main(), self.git(self.shared, "rev-parse", "HEAD"))
        self.assertIn("committed on the shared main", self.installed.read_text())
        self.assertEqual(self.status()[0], 0)

    def test_dirty_shared_checkout_stops_and_keeps_its_changes(self):
        before = self.git(self.shared, "rev-parse", "HEAD")
        installed = self.installed.read_text()
        (self.shared / HANDOFF).write_text("uncommitted edit\n")
        self.commit(self.worktree, HANDOFF, "pushed while the shared checkout is dirty\n")

        push = self.run_git(self.worktree, "push", "-q", "origin", "HEAD:main")

        self.assertEqual(push.returncode, 0)
        self.assertIn("STOPPED", push.stderr)
        self.assertIn("uncommitted changes", push.stderr)
        self.assertEqual((self.shared / HANDOFF).read_text(), "uncommitted edit\n")
        self.assertEqual(self.git(self.shared, "rev-parse", "HEAD"), before)
        self.assertEqual(self.installed.read_text(), installed)
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertEqual(rows[("checkout", "main")]["status"], "drift")

    def test_ignored_file_in_the_shared_checkout_stops_a_fast_forward_that_would_replace_it(self):
        before = self.git(self.shared, "rev-parse", "HEAD")
        (self.shared / ".env").write_text("local secret\n")
        (self.worktree / ".env").write_text("tracked by mistake\n")
        self.git(self.worktree, "add", "-f", ".env")
        self.git(self.worktree, "commit", "-q", "-m", "track .env")

        push = self.run_git(self.worktree, "push", "-q", "origin", "HEAD:main")

        self.assertEqual(push.returncode, 0)
        self.assertIn("STOPPED", push.stderr)
        self.assertEqual((self.shared / ".env").read_text(), "local secret\n")
        self.assertEqual(self.git(self.shared, "rev-parse", "HEAD"), before)

    def test_diverged_shared_checkout_stops_and_keeps_both_sides(self):
        self.commit(self.shared, "local.txt", "local commit\n", env=self.without_hook())
        local = self.git(self.shared, "rev-parse", "HEAD")
        self.commit(self.worktree, HANDOFF, "pushed after the local commit\n")

        push = self.run_git(self.worktree, "push", "-q", "origin", "HEAD:main")

        pushed = self.git(self.worktree, "rev-parse", "HEAD")
        self.assertEqual(push.returncode, 0)
        self.assertIn("1 ahead and 1 behind", push.stderr)
        self.assertEqual(self.git(self.shared, "rev-parse", "HEAD"), local)
        self.assertEqual(self.remote_main(), pushed)
        self.assertNotIn("pushed after the local commit", self.installed.read_text())
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertIn("1 ahead and 1 behind", rows[("checkout", "main")]["detail"])

        self.git(self.shared, "rebase", "-q", "origin/main")

        self.assertEqual(self.remote_main(), self.git(self.shared, "rev-parse", "HEAD"))
        self.assertIn("pushed after the local commit", self.installed.read_text())
        self.assertEqual(self.status()[0], 0)

    def test_status_names_each_gap(self):
        self.assertEqual(self.status()[0], 0)
        other = self.tmp / "other"
        self.git(self.tmp, "clone", "-q", str(self.remote), str(other))
        self.commit(other, "remote.txt", "pushed from another machine\n")
        self.git(other, "push", "-q", "origin", "main")
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertIn("has not fetched", rows[("checkout", "main")]["detail"])

        self.git(self.shared, "fetch", "-q", env=self.without_hook())
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertIn("1 commits behind", rows[("checkout", "main")]["detail"])

        self.git(self.shared, "merge", "-q", "--ff-only", "origin/main", env=self.without_hook())
        self.commit(self.shared, "unpushed.txt", "unpushed\n", env=self.without_hook())
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertIn("1 commits that origin/main lacks", rows[("checkout", "main")]["detail"])

        self.git(self.shared, "push", "-q", "origin", "main", env=self.without_hook())
        (self.shared / "scratch.txt").write_text("not committed\n")
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertIn("scratch.txt", rows[("checkout", "main")]["detail"])

        (self.shared / "scratch.txt").unlink()
        self.commit(self.shared, HANDOFF, "pushed but not installed\n", env=self.without_hook())
        self.git(self.shared, "push", "-q", "origin", "main", env=self.without_hook())
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertEqual(rows[("checkout", "main")]["status"], "ok")
        self.assertEqual(rows[("hermes", "profile:operator")]["status"], "drift")
        self.assertIn("sources changed", rows[("hermes", "profile:operator")]["detail"])

        self.assertEqual(self.level("sync").returncode, 0)
        (self.home / ".claude/CLAUDE.md").write_text("edited by hand\n")
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertEqual(rows[("claude", "instructions:default")]["status"], "drift")

    def test_installer_run_from_a_worktree_installs_the_shared_checkout(self):
        self.commit(self.worktree, HANDOFF, "only in the worktree\n")

        result = subprocess.run([sys.executable, "-I", str(self.worktree / "setup/hermes/operator_profile.py")],
                                env=self.env, capture_output=True, text=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("left alone", result.stdout)
        self.assertNotIn("only in the worktree", self.installed.read_text())
        self.assertEqual(self.status()[0], 0)

    def push_bb_plugin(self, text):
        (self.worktree / "bb-plugins/demo").mkdir(parents=True, exist_ok=True)
        (self.worktree / "bb-plugins/demo/package-lock.json").write_text("{}\n")
        self.git(self.worktree, "add", "bb-plugins/demo/package-lock.json")
        self.commit(self.worktree, "bb-plugins/demo/package.json", text)
        return self.run_git(self.worktree, "push", "-q", "origin", "HEAD:main")

    def install_calls(self):
        calls = Path(self.env["CALLS"])
        lines = calls.read_text().splitlines() if calls.exists() else []
        return [call["args"] for call in map(json.loads, lines) if call["args"][:2] in (["plugin", "install"], ["npm", "ci"])]

    def install_bb_plugin(self, source):
        (self.home / "bb-plugins.json").write_text(json.dumps(
            [{"id": "demo", "source": f"path:{source}", "providerIds": ["demo-agent"]}]))

    def set_turn(self, status):
        (self.home / "bb-threads.json").write_text(json.dumps([{"id": "thr_2", "providerId": "demo-agent",
                                                                 "status": status}]))

    def test_bb_plugin_from_the_shared_checkout_is_reinstalled_when_no_turn_uses_it(self):
        self.push_bb_plugin('{"name": "demo"}\n')
        self.install_bb_plugin(self.shared / "bb-plugins/demo")
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertIn("no record", rows[("bb", "plugin:demo")]["detail"])

        self.set_turn("active")
        push = self.push_bb_plugin('{"name": "demo", "version": "2"}\n')

        self.assertEqual(push.returncode, 0)
        self.assertIn("postponed demo", push.stderr)
        self.assertEqual(self.install_calls(), [])
        self.assertEqual(self.status()[1][("bb", "plugin:demo")]["status"], "drift")

        self.set_turn("idle")
        self.assertEqual(self.level("sync").returncode, 0)

        home = f"{self.shared}/bb-plugins/demo"
        self.assertEqual(self.install_calls(), [["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", home],
                                              ["plugin", "install", f"path:{home}", "--yes"]])
        code, rows = self.status()
        self.assertEqual(code, 0, rows)
        self.assertEqual(rows[("bb", "plugin:demo")]["status"], "ok")

    def test_bb_plugin_running_from_a_copy_is_reported_and_left_where_it_is(self):
        self.push_bb_plugin('{"name": "demo"}\n')
        copy = self.tmp / "preserved/demo"
        self.install_bb_plugin(copy)

        self.assertEqual(self.level("sync").returncode, 0)

        self.assertEqual(self.install_calls(), [])
        code, rows = self.status()
        self.assertEqual(code, 1)
        self.assertIn(f"bb plugin install path:{self.shared}/bb-plugins/demo --yes",
                      rows[("bb", "plugin:demo")]["detail"])
        self.assertIn(f"npm ci --ignore-scripts --prefix {self.shared}/bb-plugins/demo",
                      rows[("bb", "plugin:demo")]["detail"])


if __name__ == "__main__":
    unittest.main()

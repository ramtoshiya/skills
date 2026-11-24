import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HOOK = [str(Path(__file__).resolve().parents[3] / "plugins/ramtoshiya/hooks/ramtoshiya-hooks"), "guard"]

GLOBAL = "Global package installs and mutations are disabled."
ONE_SHOT = "One-shot execution requires exact package versions"
WEAKER = "Release-age overrides must preserve a minimum of three days"
UNCONFIGURED = "Package operations require a configured three-day release-age floor."
EXEMPTION = "Release-age exemption lists weaken the three-day policy."
PYTHON = "pip and package installs into a system or Homebrew Python are blocked."
PROCESS = "macOS pkill and pgrep read every argument after the first pattern as another pattern"
UNKNOWN_CWD = "The working directory comes from a variable here"


class GlobalPackageGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.cwd = self.home / "project"
        self.cwd.mkdir()
        self.environment = {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / "config")}
        self.write(".npmrc", "min-release-age=3\n")
        self.write("config/uv/uv.toml", 'exclude-newer = "3 days"\n')
        self.write("config/pnpm/config.yaml", "minimumReleaseAge: 4320\n")
        self.write(".yarnrc.yml", 'npmMinimalAgeGate: "3d"\n')

    def write(self, name, content):
        path = self.home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def check(self, command, cwd=None):
        payload = {"tool_name": "Bash", "cwd": str(cwd or self.cwd), "tool_input": {"command": command}}
        output = self.hook(payload, self.environment)
        return output["permissionDecisionReason"] if output else None

    def assert_denied(self, message, commands):
        for command in commands:
            with self.subTest(command=command):
                self.assertIn(message, self.check(command) or "")

    def assert_allowed(self, commands):
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(self.check(command))

    def hook(self, payload, environment=None):
        result = subprocess.run(HOOK, input=json.dumps(payload), text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout else None

    def test_model_acquisition_requires_immutable_revision(self):
        revision = "a" * 40
        self.assert_denied("Model downloads require --revision with a full 40-character commit hash", [
            "hf download publisher/model", "huggingface-cli download publisher/model --revision main",
            "hf download publisher/model --revision v1.0", "hf download publisher/model --revision abcdef0",
            f"hf download publisher/model --revision main --revision {revision}",
            f"hf download publisher/model -- --revision {revision}",
            "bash -lc 'hf download publisher/model'",
            "uv run hf download publisher/model --revision main",
        ])
        self.assert_denied("Model options require explicit literal values", [
            "hf download publisher/model --revision", "hf download publisher/model --revision '$REV'",
        ])
        self.assert_denied("Ollama pull/run/create cannot establish immutable artifact provenance", [
            "ollama pull model:latest", "ollama run model:7b", "ollama create model -f Modelfile",
        ])
        self.assert_allowed([
            f"hf download publisher/model --revision {revision}",
            f"huggingface-cli download publisher/model weights.safetensors --revision={revision}",
            "hf cache ls", "hf --help", "hf download --help", "ollama pull --help",
            "ollama list", "ollama show model",
            "echo 'hf download publisher/model'",
        ])

    def test_model_loading_uses_local_artifacts_and_loopback(self):
        (self.cwd / "model").mkdir()
        self.assert_allowed([
            "omlx serve --model-dir ./model --host 127.0.0.1",
            "uv run python -m mlx_lm.server --model ./model --host=::1",
            "uv run mlx_vlm.generate --model ./model --prompt test",
            "vllm serve ./model --host localhost",
            "llama-server -m ./model --host 127.0.0.1",
            "uv run python -m mlx_lm.convert --hf-path ./model",
        ])
        for command, message in [
            ("omlx serve --model-dir ./model", "loopback"),
            ("omlx serve --model-dir ./model --host 0.0.0.0", "loopback"),
            ("omlx serve --model-dir ./model --host 0.0.0.0 --host 127.0.0.1", "loopback"),
            ("vllm serve publisher/model --host 127.0.0.1", "local artifact"),
            ("uv run python -m mlx_lm.generate --model publisher/model", "local artifact"),
            ("uv run python -m mlx_vlm.convert --hf-path publisher/model", "local artifact"),
            ("llama-server --host 127.0.0.1", "local artifact"),
            ("omlx serve --model-dir ./missing --host 127.0.0.1", "must already exist"),
            ("vllm serve ./model --host localhost --trust-remote-code", "remote code"),
            ("uv run mlx_vlm.generate --model ./model --trust_remote_code=true", "remote code"),
            ("uv run python -mmlx_lm.server --model publisher/model --host 0.0.0.0", "local artifact"),
            (".venv/bin/python -Immlx_vlm.generate --model publisher/model", "local artifact"),
            ("uv run python -m mlx_lm.server --model ./model --host localhost --trust-remote-cod", "remote code"),
            ("uv run mlx_vlm.generate --model ./model --tr", "remote code"),
            ("llama-server -m ./model -hf publisher/model --host localhost", "Remote model sources"),
            ("llama-cli -m ./model --model-url=https://example.org/weights.gguf", "Remote model sources"),
            ("LLAMA_ARG_HF_REPO=publisher/model llama-server -m ./model --host localhost", "Remote model sources"),
            ("uv run mlx_lm.generate --model ./model --adapter-path publisher/adapter", "local artifact"),
        ]:
            with self.subTest(command=command):
                self.assertIn(message, self.check(command) or "")

    def test_global_mutations(self):
        self.assert_denied(GLOBAL, [
            "npm install -g example", "npm --global install example",
            "npm install --global=true example", "pnpm add -g example",
            "npm uninstall -g example", "yarn global add example",
            "uv tool install example", "uv tool upgrade example",
            "env npm_config_global=true npm install example",
            "sudo -u someone /opt/bin/npm install -g example",
            "cd repo && npm install -g example", "echo ok\nnpm install -g example",
            "bash -lc 'npm install -g example'", "if true; then npm install -g example; fi",
            "uv --directory /tmp tool install example",
            "npm --loglevel silent install -g example",
            "cat <<'EOF'\ndata\nEOF\nnpm install -g example",
        ])

    def test_project_and_read_only_commands(self):
        self.assert_allowed([
            "npm install example", "pnpm add example", "uv pip install example",
            "uv sync", "uv python install", "uv tool list", "npm list -g",
            "npx --version", "uvx --help", "npm init -y",
            "npm test -- -g", "npm install --global=false example",
            "npx example@1.2.3", "uvx example==1.2.3", "git status",
            "echo 'npm install -g example'",
            "uv run python - <<'PY'\nprint(\"don't execute npm install -g\")\nPY\n",
        ])

    def test_exact_one_shot_packages_and_all_explicit_packages(self):
        self.assert_denied(ONE_SHOT, [
            "npx example", "npx example@latest", "npx example@^1.2.3",
            "npx example@1", "npx @scope/example", "npm exec example",
            "npm exec --package=example@1.2.3 --package=other -- example",
            "npx -p example@1.2.3 -p other example",
            "pnpm dlx example", "pnpx example", "yarn dlx example",
            "yarn dlx -p example@1.2.3 -p other example",
            "uvx example", "uvx example@latest", "uvx --from 'example>=1' example",
            "uv tool run --from example example", "uvx example==1.*",
            "uvx --with other example==1.2.3",
            "uv run --with other python -V", "npm create example@latest",
        ])
        self.assert_allowed([
            "npx example@1.2.3", "npx @scope/example@1.2.3-rc.1",
            "npx -p example@1.2.3 -p other@2.3.4 example",
            "npm exec --package=example@1.2.3 -- example --min-release-age=0",
            "npm exec -- example@1.2.3", "pnpm dlx example@1.2.3",
            "pnpx example@1.2.3", "yarn dlx -p example@1.2.3 example",
            "uvx example==1.2.3", "uvx --from example==1.2.3 example --exclude-newer=false",
            "uv tool run --from 'example[extra]==1.2.3rc1' example",
            "uv run --with example==1.2.3 python -V", "npm create example@1.2.3",
        ])

    def test_weaker_cli_environment_and_export_overrides(self):
        self.assert_denied(WEAKER, [
            "npm install --min-release-age=2", "npm install --min-release-age 0",
            "NPM_CONFIG_MIN_RELEASE_AGE=1 npm install",
            "env npm_config_min_release_age=0 npx example@1.2.3",
            "export NPM_CONFIG_MIN_RELEASE_AGE=1; npm install",
            "NPM_CONFIG_MIN_RELEASE_AGE=1; npm install",
            "pnpm add example --config.minimumReleaseAge=4319",
            "NPM_CONFIG_MINIMUM_RELEASE_AGE=0 pnpm install",
            "YARN_NPM_MINIMAL_AGE_GATE=1d yarn install",
            "uv pip install example --exclude-newer false",
            "UV_EXCLUDE_NEWER='1 day' uv sync",
            "uv run --exclude-newer PT24H python -V",
            "uvx --exclude-newer P2D example==1.2.3",
            "bash -lc 'UV_EXCLUDE_NEWER=false uv sync'",
        ])
        self.assert_allowed([
            "npm install --min-release-age 3", "pnpm add example --config.minimumReleaseAge=4320",
            "YARN_NPM_MINIMAL_AGE_GATE=72h yarn install", "uv sync --exclude-newer PT72H",
            "uv pip install example --exclude-newer '1 week'",
        ])

    def test_inherited_environment_and_case_sensitive_paths(self):
        self.environment["UV_EXCLUDE_NEWER"] = "false"
        self.assert_denied(WEAKER, ["uv sync"])
        self.assert_allowed(["env -u UV_EXCLUDE_NEWER uv sync"])
        config = self.write("UPPER/uv.toml", 'exclude-newer = "1 day"\n')
        self.assert_denied(WEAKER, [f"uv sync --config-file '{config}'"])

    def test_project_overrides_and_tool_working_directory(self):
        for name, content, command in [
            (".npmrc", "min-release-age=1\n", "npm install"),
            ("pnpm-workspace.yaml", "minimumReleaseAge: 1\n", "pnpm install"),
            (".yarnrc.yml", 'npmMinimalAgeGate: "1h"\n', "yarn install"),
            ("uv.toml", 'exclude-newer = "1 day"\n', "uv sync"),
            ("pyproject.toml", '[tool.uv]\nexclude-newer = "1 day"\n', "uv sync"),
        ]:
            with self.subTest(name=name):
                path = self.cwd / name
                path.write_text(content)
                self.assert_denied(WEAKER, [command])
                for routed in [f"cd '{self.cwd}' && {command}", f"{command} --directory '{self.cwd}'"]:
                    self.assertIn(WEAKER, self.check(routed, self.home) or "")
                path.unlink()

    def test_uv_reads_project_age_policy_from_tool_uv_only(self):
        (self.cwd / "pyproject.toml").write_text('[project]\nname = "example"\nexclude-newer = "1 day"\n')
        self.assert_allowed(["uv sync"])
        (self.cwd / "pyproject.toml").write_text('[tool.uv]\nexclude-newer = "1 day"\n')
        self.assert_denied(WEAKER, ["uv sync"])

    def test_uvx_ignores_project_config(self):
        (self.cwd / "pyproject.toml").write_text('[tool.uv]\nexclude-newer = "1 day"\n')
        self.assert_denied(WEAKER, ["uv sync"])
        self.assert_allowed(["uvx example==1.2.3"])

    def test_uv_toml_overrides_pyproject_tool_uv(self):
        (self.cwd / "pyproject.toml").write_text('[tool.uv]\nexclude-newer = "1 day"\n')
        self.assert_denied(WEAKER, ["uv sync"])
        (self.cwd / "uv.toml").write_text('exclude-newer = "3 days"\n')
        self.assert_allowed(["uv sync"])

    def test_uv_pip_reads_the_pip_namespace(self):
        (self.cwd / "uv.toml").write_text('exclude-newer = "3 days"\n[pip]\nexclude-newer = "1 day"\n')
        self.assert_allowed(["uv sync"])
        self.assert_denied(WEAKER, ["uv pip install example"])

    def test_config_disabling_or_relocation_does_not_remove_age_requirement(self):
        empty = self.write("empty.toml", "")
        self.assert_denied(UNCONFIGURED, ["uv sync --no-config", "UV_NO_CONFIG=1 uv sync",
                                          f"uv sync --config-file '{empty}'", "npm install --userconfig /dev/null"])
        self.assert_allowed(["uv sync --no-config --exclude-newer '3 days'"])

    def test_age_exemptions_and_absolute_dates(self):
        self.assert_denied(EXEMPTION, [
            "npm install --min-release-age-exclude example",
            "pnpm install --config.minimumReleaseAgeExclude=example",
            "YARN_NPM_PREAPPROVED_PACKAGES=example yarn install",
        ])
        self.assert_denied(WEAKER, [
            "npm install --before 2999-01-01",
            "uv sync --exclude-newer-package example=false",
            "uv sync --exclude-newer-package example='1 day'",
        ])
        self.assert_allowed([
            "uv sync --exclude-newer-package example='1 week'",
            "npm install --before 2020-01-01",
            "uv sync --exclude-newer 2020-01-01T00:00:00Z",
        ])
        self.write("config/uv/uv.toml", 'exclude-newer = "3 days"\nexclude-newer-package = { example = false }\n')
        self.assert_denied(WEAKER, ["uv sync"])

    def test_multiline_yaml_exemptions_and_unsupported_policy_fail_closed(self):
        for content in ["minimumReleaseAge: 4320\nminimumReleaseAgeExclude:\n  - example\n",
                        "{minimumReleaseAge: 0}\n", "minimumReleaseAge: 4320\nminimumReleaseAge: 0\n"]:
            self.write("config/pnpm/config.yaml", content)
            with self.subTest(content=content):
                payload = {"tool_name": "Bash", "cwd": str(self.cwd), "tool_input": {"command": "pnpm install"}}
                self.assertEqual(self.hook(payload, self.environment)["permissionDecision"], "deny")

    def test_python_execution_and_package_commands(self):
        self.assert_allowed(["python -V", "python3 -V", "python3.12 script.py", "python2.7 script.py",
                             "/usr/bin/python3 -V", "/opt/homebrew/bin/python3 -V", "env python3 -V",
                             "command python3 -V", "sudo python3 -V", "env -S 'python3 -V'",
                             "bash -lc 'python3 -V'", "python3 -c 'print(1)'",
                             "python3 - <<'PY'\nprint(1)\nPY\n", ".venv/bin/pip list",
                             "./venv/bin/python -m pip install x", "uv pip list"])
        self.assert_denied(PYTHON, ["pip --version", "pip3 list", "pip3.12 install x", "/usr/bin/pip3 list",
                                    "sudo pip list", "env -S 'pip list'", "bash -lc 'pip list'",
                                    "python -m pip list", "python -mpip list", "python -Im pip list",
                                    "python -m ensurepip", "python setup.py install", "python setup.py develop",
                                    "python -u setup.py install", "python -I setup.py install",
                                    "python setup.py --quiet install", "uv pip list --break-system-packages"])
        self.assert_denied("local artifact", ["python3 -m mlx_lm.server --model publisher/model"])
        custom = self.write("custom-env/pyvenv.cfg", "home = /example\n")
        self.assert_allowed([f"{custom.parent}/bin/python -m pip list"])

    def test_variable_cd_tracks_unknown_directory(self):
        self.assert_allowed(['cd "$W" && git status', 'cd $W; ls', 'cd $W && python3 x.py',
                             'cd "$W" && .venv/bin/pip list',
                             f'cd $W && cd {self.cwd} && uv sync',
                             'cd $W && cd ~ && uv sync',
                             f'cd $W && uv --directory {self.cwd} sync',
                             'cd "$W" && uvx example==1.2.3'])
        self.assert_denied(UNKNOWN_CWD, ['cd "$W" && npm install', "cd $W && bash -lc 'uv sync'",
                                         'cd $W && cd relative && uv sync',
                                         'cd $W && uv --directory relative sync',
                                         'cd $W && python -m mlx_lm.generate --model ./model'])

    def test_process_patterns_after_options_only(self):
        self.assert_denied(PROCESS, [
            'pkill -f "^bun tools/check/load.ts$" -U $(id -u)',
            'pkill -f -- "^bun tools/check/load.ts$" -U $(id -u)',
            'sudo pkill -f "^bun tools/check/load.ts$" -U $(id -u)',
            'env pkill -f "^bun tools/check/load.ts$" -U $(id -u)',
            "sh -c 'pkill -f \"^bun tools/check/load.ts$\" -U $(id -u)'",
            "bash -lc 'pkill -f \"^bun tools/check/load.ts$\" -U $(id -u)'",
            'echo $(pkill -f "^bun tools/check/load.ts$" -U $(id -u))',
            'pattern="^bun tools/check/load.ts$"; pkill -f "$pattern" -U $(id -u)',
            'pkill -f "src/server.ts" -P $(cat .srv.pid) 2>/dev/null',
            "pkill -9 -f 'simlock lease.*' -U $(id -u) -n 2>/dev/null",
            'P=$(pgrep -f "test-worker.*" -n); echo $P',
            "pgrep -x git -l",
            "/usr/bin/pgrep -f one two",
        ])
        self.assert_allowed([
            'pkill -U $(id -u) -f "^bun tools/check/load.ts$"',
            'pkill -TERM -f "ios-board.ts $O/data"',
            "pkill -9 -f /tmp/thr_x/Electron.app",
            'pgrep -x "iPhone Mirroring" >/dev/null && echo running',
            'until ! pgrep -f "$S/review.py" > /dev/null; do sleep 1; done',
            'pgrep -fl "collect/main.ts" 2>&1 | head',
            "pgrep -d, -lf 'wjrj|simlock'",
            "W=$(/usr/bin/pgrep -P $C | head -1)",
            "git commit -m 'pkill -f x -U 501'",
            "echo 'pkill -f x -U 501'",
            "rg -F 'pkill -f x -U 501' notes.md",
            "cat <<'EOF'\npkill -f x -U 501\nEOF",
        ])

    def test_process_denial_reaches_both_agents(self):
        for tool, field in [("Bash", "command"), ("exec_command", "cmd")]:
            output = self.hook({"tool_name": tool, "tool_input": {field: "pkill -f load.ts -U 501"}})
            self.assertEqual(output["permissionDecision"], "deny")
            self.assertIn(PROCESS, output["permissionDecisionReason"])

    def test_valid_shell_is_checked_not_refused(self):
        commands = [
            "git commit -m 'Document heredocs\n\nStart one with cat <<EOF on its own line.\nEnd it with EOF.'",
            "base=${file#src/}; git commit -m 'Move $base\n\nKeep the old name.'",
            "printf '%s\\n' $'don\\'t stop'",
        ]
        self.assert_allowed(commands)
        self.assert_denied(GLOBAL, [f"{command}\nnpm install -g example" for command in commands])

    def test_commands_in_every_construct_are_checked(self):
        global_install = "npm install -g example"
        self.assert_denied(GLOBAL, [
            f"({global_install})", f"echo $({global_install})", f'echo "$({global_install})"',
            f"X=$({global_install})", f"echo x > $({global_install})", f"cat <({global_install})",
            f"{{ {global_install}; }}", f"f() {{ {global_install}; }}; f",
            f"while {global_install}; do :; done", f"until {global_install}; do :; done",
            f"if {global_install}; then :; fi", f"for i in $({global_install}); do :; done",
            f"case x in x) {global_install};; esac", f"case $({global_install}) in x) :;; esac",
            f"[[ $({global_install}) ]]", f"echo $(( $({global_install}) + 1 ))",
            f"time {global_install}", f"! {global_install}", f"echo x | {global_install}",
            f"bash -lc '{global_install}'", f"env -S '{global_install}'",
            f"cat <<EOF\n$({global_install})\nEOF", f"echo ok && {global_install}",
        ])
        self.assert_allowed([
            f"cat <<'EOF'\n{global_install}\nEOF", f"echo '{global_install}'", f'echo "{global_install}"',
            f"echo '$({global_install})'", f'echo "\\$({global_install})"', f"echo ok # {global_install}",
        ])

    def test_directory_changes_stay_inside_their_scope(self):
        (self.cwd / ".npmrc").write_text("min-release-age=1\n")
        self.assert_denied(WEAKER, [
            "npm install", f"(cd '{self.home}') && npm install", f"echo $(cd '{self.home}') && npm install",
            f"echo x | (cd '{self.home}') && npm install", f"f() {{ cd '{self.home}'; }}; npm install",
        ])
        self.assert_allowed([f"cd '{self.home}' && npm install", f"(cd '{self.home}' && npm install)"])

    def test_zsh_syntax_is_checked_not_refused(self):
        commands = ["for f in a b; do set -- ${(z)f}; echo ${=f}; done", "files=(${(f)\"$(ls)\"}); echo ${#files[@]}"]
        self.assert_allowed(commands)
        self.assert_denied(GLOBAL, [f"{command}; npm install -g example" for command in commands])

    def test_command_text_is_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "marker"
            self.check(f"echo $(touch {marker})")
            self.assertFalse(marker.exists())

    def test_denial_wire_format_for_both_shell_inputs(self):
        for tool, field in [("Bash", "command"), ("Monitor", "command"), ("exec_command", "cmd")]:
            output = self.hook({"tool_name": tool, "tool_input": {field: "hf download publisher/model"}})
            self.assertEqual(output["hookEventName"], "PreToolUse")
            self.assertEqual(output["permissionDecision"], "deny")

    def test_websocket_monitor_without_command_is_allowed(self):
        payload = {"tool_name": "Monitor", "tool_input": {"ws": {"url": "wss://example.com"}, "description": "events"}}
        self.assertIsNone(self.hook(payload))

    def test_allow_does_not_override_normal_permissions(self):
        for tool, field in [("Bash", "command"), ("Monitor", "command"), ("exec_command", "cmd")]:
            payload = {"tool_name": tool, "tool_input": {field: "hf download publisher/model --revision " + "a" * 40}}
            self.assertIsNone(self.hook(payload))

    def test_policy_denials_and_cwd_in_native_payload(self):
        (self.cwd / "uv.toml").write_text('exclude-newer = "1 day"\n')
        for command in ["pip list", "npx example", "uv sync"]:
            payload = {"tool_name": "Bash", "cwd": str(self.cwd), "tool_input": {"command": command}}
            self.assertEqual(self.hook(payload, self.environment)["permissionDecision"], "deny")

    def test_codex_workdir_selects_project_policy(self):
        (self.cwd / "uv.toml").write_text('exclude-newer = "1 day"\n')
        other = self.home / "other"
        other.mkdir()
        def run(workdir, cwd):
            payload = {"tool_name": "exec_command", "cwd": str(cwd), "tool_input": {"cmd": "uv sync", "workdir": str(workdir)}}
            return self.hook(payload, self.environment)
        self.assertIn(WEAKER, run(self.cwd, other)["permissionDecisionReason"])
        self.assertIsNone(run(other, self.cwd))


if __name__ == "__main__":
    unittest.main()

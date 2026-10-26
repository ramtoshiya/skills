import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/ramtoshiya/hooks/global-package-guard.py"
spec = importlib.util.spec_from_file_location("global_package_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


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

    def check(self, command):
        return guard.blocked(command, self.cwd, self.environment)

    def test_model_acquisition_requires_immutable_revision(self):
        revision = "a" * 40
        for command in [
            "hf download publisher/model", "huggingface-cli download publisher/model --revision main",
            "hf download publisher/model --revision v1.0", "hf download publisher/model --revision abcdef0",
            "hf download publisher/model --revision", "hf download publisher/model --revision '$REV'",
            f"hf download publisher/model --revision main --revision {revision}",
            f"hf download publisher/model -- --revision {revision}",
            "env HF_REVISION=main hf download publisher/model",
            "bash -lc 'hf download publisher/model'", "ollama pull model:latest",
            "ollama run model:7b", "ollama create model -f Modelfile",
            "uv run hf download publisher/model --revision main",
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.check(command))
        for command in [
            f"hf download publisher/model --revision {revision}",
            f"huggingface-cli download publisher/model weights.safetensors --revision={revision}",
            "hf cache ls", "hf --help", "hf download --help", "ollama pull --help",
            "ollama list", "ollama show model",
            "echo 'hf download publisher/model'",
        ]:
            with self.subTest(command=command):
                self.assertFalse(self.check(command))

    def test_model_loading_uses_local_artifacts_and_loopback(self):
        (self.cwd / "model").mkdir()
        for command in [
            "omlx serve --model-dir ./model --host 127.0.0.1",
            "uv run python -m mlx_lm.server --model ./model --host=::1",
            "uv run mlx_vlm.generate --model ./model --prompt test",
            "vllm serve ./model --host localhost",
            "llama-server -m ./model --host 127.0.0.1",
            "uv run python -m mlx_lm.convert --hf-path ./model",
        ]:
            with self.subTest(command=command):
                self.assertFalse(self.check(command))
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
                self.assertIn(message, guard.reason(command, self.cwd, self.environment))

    def test_global_mutations(self):
        for command in [
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
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.check(command))

    def test_project_and_read_only_commands(self):
        for command in [
            "npm install example", "pnpm add example", "uv pip install example",
            "uv sync", "uv python install", "uv tool list", "npm list -g",
            "npx --version", "uvx --help", "npm init -y",
            "npm test -- -g", "npm install --global=false example",
            "npx example@1.2.3", "uvx example==1.2.3", "git status",
            "echo 'npm install -g example'",
            "uv run python - <<'PY'\nprint(\"don't execute npm install -g\")\nPY\n",
        ]:
            with self.subTest(command=command):
                self.assertFalse(self.check(command))

    def test_exact_one_shot_packages_and_all_explicit_packages(self):
        for command in [
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
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.check(command))
        for command in [
            "npx example@1.2.3", "npx @scope/example@1.2.3-rc.1",
            "npx -p example@1.2.3 -p other@2.3.4 example",
            "npm exec --package=example@1.2.3 -- example --min-release-age=0",
            "npm exec -- example@1.2.3", "pnpm dlx example@1.2.3",
            "pnpx example@1.2.3", "yarn dlx -p example@1.2.3 example",
            "uvx example==1.2.3", "uvx --from example==1.2.3 example --exclude-newer=false",
            "uv tool run --from 'example[extra]==1.2.3rc1' example",
            "uv run --with example==1.2.3 python -V", "npm create example@1.2.3",
        ]:
            with self.subTest(command=command):
                self.assertFalse(self.check(command))

    def test_weaker_cli_environment_and_export_overrides(self):
        for command in [
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
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.check(command))
        for command in [
            "npm install --min-release-age 3", "pnpm add example --config.minimumReleaseAge=4320",
            "YARN_NPM_MINIMAL_AGE_GATE=72h yarn install", "uv sync --exclude-newer PT72H",
            "uv pip install example --exclude-newer '1 week'",
        ]:
            with self.subTest(command=command):
                self.assertFalse(self.check(command))

    def test_inherited_environment_and_case_sensitive_paths(self):
        self.environment["UV_EXCLUDE_NEWER"] = "false"
        self.assertTrue(self.check("uv sync"))
        self.assertFalse(self.check("env -u UV_EXCLUDE_NEWER uv sync"))
        config = self.write("UPPER/uv.toml", 'exclude-newer = "1 day"\n')
        self.assertTrue(self.check(f"uv sync --config-file '{config}'"))

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
                self.assertTrue(self.check(command))
                self.assertTrue(guard.blocked(f"cd '{self.cwd}' && {command}", self.home, self.environment))
                self.assertTrue(guard.blocked(f"{command} --directory '{self.cwd}'", self.home, self.environment))
                path.unlink()

    def test_uv_config_precedence_tool_config_and_pip_namespace(self):
        (self.cwd / "pyproject.toml").write_text('[project]\nname = "example"\nexclude-newer = "1 day"\n')
        self.assertFalse(self.check("uv sync"))
        (self.cwd / "pyproject.toml").write_text('[tool.uv]\nexclude-newer = "1 day"\n')
        self.assertTrue(self.check("uv sync"))
        self.assertFalse(self.check("uvx example==1.2.3"))  # Tool commands ignore project config.
        (self.cwd / "uv.toml").write_text('exclude-newer = "3 days"\n[pip]\nexclude-newer = "1 day"\n')
        self.assertFalse(self.check("uv sync"))  # uv.toml takes precedence over pyproject.toml.
        self.assertTrue(self.check("uv pip install example"))

    def test_config_disabling_or_relocation_does_not_remove_age_requirement(self):
        empty = self.write("empty.toml", "")
        for command in ["uv sync --no-config", "UV_NO_CONFIG=1 uv sync",
                        f"uv sync --config-file '{empty}'", "npm install --userconfig /dev/null"]:
            with self.subTest(command=command):
                self.assertTrue(self.check(command))
        self.assertFalse(self.check("uv sync --no-config --exclude-newer '3 days'"))

    def test_age_exemptions_and_absolute_dates(self):
        for command in [
            "npm install --min-release-age-exclude example",
            "npm install --before 2999-01-01",
            "pnpm install --config.minimumReleaseAgeExclude=example",
            "YARN_NPM_PREAPPROVED_PACKAGES=example yarn install",
            "uv sync --exclude-newer-package example=false",
            "uv sync --exclude-newer-package example='1 day'",
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.check(command))
        self.assertFalse(self.check("uv sync --exclude-newer-package example='1 week'"))
        self.assertFalse(self.check("npm install --before 2020-01-01"))
        self.assertFalse(self.check("uv sync --exclude-newer 2020-01-01T00:00:00Z"))
        self.write("config/uv/uv.toml", 'exclude-newer = "3 days"\nexclude-newer-package = { example = false }\n')
        self.assertTrue(self.check("uv sync"))

    def test_multiline_yaml_exemptions_and_unsupported_policy_fail_closed(self):
        for content in ["minimumReleaseAge: 4320\nminimumReleaseAgeExclude:\n  - example\n",
                        "{minimumReleaseAge: 0}\n", "minimumReleaseAge: 4320\nminimumReleaseAge: 0\n"]:
            self.write("config/pnpm/config.yaml", content)
            with self.subTest(content=content):
                try:
                    self.assertTrue(self.check("pnpm install"))
                except ValueError:
                    pass  # The wire adapter turns parse failures into a denial.

    def test_every_bare_python_and_pip_command_is_blocked(self):
        for command in [
            "python -V", "python3 -V", "python3.15 script.py", "python2.7 script.py",
            "pip list", "pip3 install example", "pip3.15 --version",
            "/usr/bin/python3 -V", "/opt/homebrew/bin/pip3 list",
            "command python3 -V", "env python3 -V", "sudo -u someone pip3 list",
            "/usr/bin/env -S 'python3 -V'", "env --split-string='pip3 list'",
            "python3 - <<'PY'\nprint('hello')\nPY\n", "bash -lc 'python3 -V'",
            "source .venv/bin/activate && python3 -V",
        ]:
            with self.subTest(command=command):
                self.assertTrue(self.check(command))
        for command in ["uv run python -V", "uv pip list", ".venv/bin/python -V",
                        "./venv/bin/pip list", "/tmp/project/.venv/bin/python3.15 -V",
                        "echo 'python3 -V'", "cat <<'EOF'\npython3 -V\nEOF\n"]:
            with self.subTest(command=command):
                self.assertFalse(self.check(command))
        custom = self.write("custom-env/pyvenv.cfg", "home = /example\n")
        self.assertFalse(self.check(f"{custom.parent}/bin/python -V"))

    def test_command_text_is_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "marker"
            self.check(f"echo $(touch {marker})")
            self.assertFalse(marker.exists())

    def test_denial_wire_format_for_both_shell_inputs(self):
        for tool, field in [("Bash", "command"), ("Monitor", "command"), ("exec_command", "cmd")]:
            payload = {"tool_name": tool, "tool_input": {field: "hf download publisher/model"}}
            result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0)
            output = json.loads(result.stdout)["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "PreToolUse")
            self.assertEqual(output["permissionDecision"], "deny")

    def test_websocket_monitor_without_command_is_allowed(self):
        payload = {"tool_name": "Monitor", "tool_input": {"ws": {"url": "wss://example.com"}, "description": "events"}}
        result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_allow_does_not_override_normal_permissions(self):
        for tool, field in [("Bash", "command"), ("Monitor", "command"), ("exec_command", "cmd")]:
            payload = {"tool_name": tool, "tool_input": {field: "hf download publisher/model --revision " + "a" * 40}}
            result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")

    def test_policy_denials_and_cwd_in_native_payload(self):
        (self.cwd / "uv.toml").write_text('exclude-newer = "1 day"\n')
        for command in ["python3 -V", "npx example", "uv sync"]:
            payload = {"tool_name": "Bash", "cwd": str(self.cwd), "tool_input": {"command": command}}
            result = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(payload), text=True,
                                    capture_output=True, env=self.environment)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()

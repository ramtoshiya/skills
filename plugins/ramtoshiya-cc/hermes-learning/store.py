"""Find the Hermes learning store and a command that runs a script under the Hermes interpreter.

Standard library only: the hook and the MCP server launcher import it before Hermes is on the path.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_STORE = "~/.hermes/profiles/coder"
SKILLS_PLUGIN = "claude-skills-plugin"
DEFAULT_HERMES = "~/.hermes/hermes-agent/.hermes/bin/hermes"
SENTINEL = "hermes_learning_entry"
ENTRY = f"runpy.run_module({SENTINEL!r}, run_name='__main__', alter_sys=True)"


class Unavailable(Exception):
    """Hermes or the learning store is missing. The message names what is missing."""


def in_coder_runtime() -> bool:
    """The Hermes coder runtime starts Claude Code inside a Hermes gateway, whose marker every child inherits.
    That runtime injects memory and runs learning itself."""
    return os.environ.get("_HERMES_GATEWAY") == "1"


def store() -> Path:
    path = Path(os.environ.get("HERMES_LEARNING_HOME") or DEFAULT_STORE).expanduser()
    if not path.is_dir():
        raise Unavailable(f"the Hermes learning store {path} does not exist. Create the Hermes profile, "
                          "or set HERMES_LEARNING_HOME to an existing profile directory")
    return path


def hermes_command(script: Path, *args: str) -> list[str]:
    """Hermes's own launch command (interpreter, bootstrap, selected dependencies) with *script* as the entry."""
    hermes = shutil.which("hermes") or str(Path(DEFAULT_HERMES).expanduser())
    if not os.access(hermes, os.X_OK):
        raise Unavailable(f"Hermes is not installed: no `hermes` on PATH or at {DEFAULT_HERMES}")
    printed = subprocess.run([hermes, "--print-runtime-command", "--module", SENTINEL],
                             capture_output=True, text=True, timeout=60)
    try:
        argv = json.loads(printed.stdout)
    except ValueError:
        argv = None
    if not (isinstance(argv, list) and len(argv) == 4 and argv[2] == "-c" and argv[3].endswith(ENTRY)):
        raise Unavailable(f"`{hermes} --print-runtime-command` did not print the launch command this plugin "
                          f"reads: {(printed.stdout or printed.stderr).strip()[:300]}")
    code = argv[3][:-len(ENTRY)] + f"runpy.run_path({str(script)!r}, run_name='__main__')"
    return [*argv[:3], code, *args]

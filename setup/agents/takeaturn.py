"""Install the takeaturn CLI at the pinned commit into ~/.local/bin, or report whether it is there."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

MODULE = "github.com/ramtoshiya/takeaturn"
COMMIT = "1635f6a1161844054136abf89ac8b2df2ee3ef85"
GO = "go@1.27.4"


def target():
    return Path.home() / ".local/bin/takeaturn"


def installed_commit():
    try:
        result = subprocess.run([str(target()), "version"], capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=30)
        return json.loads(result.stdout)["version"].rsplit("-", 1)[-1]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None


def status():
    found = installed_commit()
    if found and len(found) == 12 and COMMIT.startswith(found):
        return {"host": "takeaturn", "component": "cli", "status": "ok", "detail": f"{COMMIT[:12]} at {target()}"}
    now = f"is at {found}" if found else "is missing"
    return {"host": "takeaturn", "component": "cli", "status": "drift",
            "detail": f"{target()} {now}, and the pin is {COMMIT[:12]}. Run `mise run takeaturn:install`"}


def install():
    if status()["status"] == "ok":
        print(f"takeaturn {COMMIT[:12]} is already installed at {target()}")
        return 0
    target().parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GOBIN": str(target().parent), "GOPRIVATE": MODULE, "GOTOOLCHAIN": "local",
           "GOFLAGS": "-modcacherw", "GIT_TERMINAL_PROMPT": "0"}
    command = ["mise", "exec", GO, "--", "go", "install", f"{MODULE}@{COMMIT}"]
    if shutil.which("mise") is None or subprocess.run(command, env=env, stdin=subprocess.DEVNULL).returncode:
        print(f"Installing takeaturn failed: `{' '.join(command)}` needs mise, network access, "
              f"and read access to the private repository {MODULE}", file=sys.stderr)
        return 1
    row = status()
    print(row["detail"], file=sys.stdout if row["status"] == "ok" else sys.stderr)
    return 0 if row["status"] == "ok" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "install"])
    args = parser.parse_args()
    if args.command == "install":
        return install()
    print(json.dumps([status()]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Build the hook binary from its Go source and report whether the checkout's copy matches it."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "plugins/ramtoshiya/hooks"
OUTPUTS = ("plugins/ramtoshiya/hooks/ramtoshiya-hooks", "plugins/ramtoshiya-cc/hooks/ramtoshiya-hooks")


class BuildError(RuntimeError):
    pass


def go(root):
    try:
        found = subprocess.run(["mise", "-C", str(root), "which", "go"], capture_output=True, text=True)
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    except OSError:
        pass
    path = shutil.which("go")
    if path is None:
        raise BuildError("Go is not installed. Run mise install --locked in the repository.")
    return path


def compile(root, destination):
    environment = {**os.environ, "CGO_ENABLED": "0", "GOTOOLCHAIN": "local"}
    command = [go(root), "build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-o", str(destination), "."]
    result = subprocess.run(command, cwd=root / SOURCE, env=environment, capture_output=True, text=True)
    if result.returncode:
        raise BuildError(f"go build failed in {root / SOURCE}:\n{result.stdout}{result.stderr}".rstrip())


def temporary(output):
    handle, name = tempfile.mkstemp(prefix=".ramtoshiya-hooks.", dir=output.parent)
    os.close(handle)
    return Path(name)


def build(root):
    root = Path(root)
    changed = False
    for relative in OUTPUTS:
        output = root / relative
        built = temporary(output)
        try:
            compile(root, built)
            if not output.is_file() or output.read_bytes() != built.read_bytes():
                os.replace(built, output)
                changed = True
        finally:
            built.unlink(missing_ok=True)
    return changed


def status(root):
    root = Path(root)
    states = set()
    with tempfile.TemporaryDirectory() as directory:
        built = Path(directory) / "ramtoshiya-hooks"
        for relative in OUTPUTS:
            output = root / relative
            if not output.is_file():
                states.add("absent")
                continue
            compile(root, built)
            states.add("ok" if output.read_bytes() == built.read_bytes() else "drift")
    return "absent" if "absent" in states else "drift" if "drift" in states else "ok"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "status"))
    action = parser.parse_args().action
    try:
        if action == "build":
            build(ROOT)
        else:
            print(status(ROOT))
    except BuildError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()

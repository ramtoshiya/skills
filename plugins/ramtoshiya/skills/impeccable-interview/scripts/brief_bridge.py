#!/usr/bin/env python3
"""Plan and save one managed interview block through an installed Impeccable CLI."""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


BEGIN = "<!-- impeccable-interview:start -->"
END = "<!-- impeccable-interview:end -->"
HEADING = "## Interview brief {:#interview-brief}"
FIELDS = {"version", "slug", "primary_target", "related_targets"}


class BridgeError(Exception):
    pass


def digest(path):
    if not path.exists():
        return None
    if not path.is_file():
        raise BridgeError(f"Expected a file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(engine, project, *args, missing_ok=False):
    result = subprocess.run(
        [str(engine), *args], cwd=project, capture_output=True, text=True,
        timeout=30, env={**os.environ, "DO_NOT_TRACK": "1"},
    )
    if result.returncode and not (missing_ok and result.returncode == 2 and not result.stdout):
        raise BridgeError(f"Impeccable refused {args[0]}: {result.stderr or result.stdout}")
    return result


def validate_target(target):
    if target.startswith("route:/"):
        route = target[6:]
        if "?" in route or "#" in route or "//" in route or ".." in route.split("/"):
            raise BridgeError("Use a normalized route:/ target without query or fragment")
        if route != "/" and route.endswith("/"):
            raise BridgeError("Remove the route's trailing slash")
    elif (
        not target or Path(target).is_absolute() or ":" in target
        or ".." in Path(target).parts or "\\" in target
        or Path(target).as_posix() != target
    ):
        raise BridgeError("POC targets must be normalized project-relative files or route:/ paths")


def surface_path(engine, project, target):
    value = command(engine, project, "surface-brief", "path", target).stdout.strip()
    path = project / value
    if not value or "\n" in value or path.is_symlink():
        raise BridgeError("Invalid or symlinked surface path")
    resolved = path.resolve()
    surface_dir = (project / ".impeccable" / "surfaces").resolve()
    if not surface_dir.is_relative_to(project) or resolved.parent != surface_dir:
        raise BridgeError("Surface path escapes the project's surface directory")
    return resolved


def render(meta, body):
    def encoded(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    lines = ["---", "version: 1"]
    lines.extend(f"{key}: {encoded(meta[key])}" for key in ("slug", "primary_target", "related_targets"))
    return "\n".join(lines) + "\n---\n\n" + body.strip() + "\n"


def parse(text):
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise BridgeError("Unsupported surface frontmatter")
    header, body = text[4:].split("\n---\n", 1)
    meta = {}
    for line in header.splitlines():
        key, separator, value = line.partition(": ")
        if not separator or key in meta:
            raise BridgeError("Unsupported or duplicate surface metadata")
        meta[key] = json.loads(value)
    if set(meta) != FIELDS or meta["version"] != 1:
        raise BridgeError("Unknown surface metadata or schema, refusing to rewrite it")
    if not isinstance(meta["slug"], str) or not isinstance(meta["primary_target"], str):
        raise BridgeError("Invalid surface identity")
    if not isinstance(meta["related_targets"], list) or not all(isinstance(x, str) for x in meta["related_targets"]):
        raise BridgeError("Invalid related targets")
    if render(meta, body) != text:
        raise BridgeError("Noncanonical surface format, refusing implicit normalization")
    return meta, body.strip()


def inspect(engine, project, target):
    validate_target(target)
    directory = project / ".impeccable" / "surfaces"
    if not directory.resolve().is_relative_to(project):
        raise BridgeError("Surface directory escapes the project")
    if any(p.is_symlink() for p in directory.glob("*.md")):
        raise BridgeError("Symlinked briefs are outside this POC's write contract")
    candidate = surface_path(engine, project, target)
    result = command(engine, project, "surface-brief", "read", target, missing_ok=True)
    if result.returncode:
        if candidate.exists():
            raise BridgeError("An existing brief could not be read")
        meta = {"version": 1, "slug": candidate.stem, "primary_target": target, "related_targets": []}
        return candidate, meta, "", None
    meta, body = parse(result.stdout)
    canonical = surface_path(engine, project, meta["primary_target"])
    if not canonical.is_file() or canonical.read_bytes().decode("utf-8") != result.stdout:
        raise BridgeError("CLI resolution differs from canonical storage, refusing migration")
    return canonical, meta, body, digest(canonical)


def merge(body, draft):
    draft = draft.strip()
    if not draft or BEGIN in draft or END in draft or HEADING in draft:
        raise BridgeError("Draft must contain only the interview content, not bridge markers or its heading")
    if re.search(r"^#{1,6}\s+Direction contract\b", draft, re.MULTILINE | re.IGNORECASE):
        raise BridgeError("The interview cannot author a Direction contract")
    counts = (body.count(BEGIN), body.count(END))
    block = f"{BEGIN}\n{HEADING}\n\n{draft}\n{END}"
    if counts == (0, 0):
        if HEADING in body or re.search(r"^## Interview brief\b", body, re.MULTILINE):
            raise BridgeError("An unmarked interview brief needs explicit manual adoption")
        return (body + "\n\n" if body else "") + block
    if counts != (1, 1) or body.index(BEGIN) > body.index(END):
        raise BridgeError("Malformed or duplicate interview markers")
    start, end = body.index(BEGIN), body.index(END) + len(END)
    region = body[start:end]
    if re.search(r"^#{1,6}\s+Direction contract\b", region, re.MULTILINE | re.IGNORECASE):
        raise BridgeError("Interview markers overlap a Direction contract")
    if (
        not region.startswith(f"{BEGIN}\n{HEADING}\n\n")
        or not region.endswith(f"\n{END}")
        or (start > 0 and body[start - 1] != "\n")
        or (end < len(body) and body[end] != "\n")
    ):
        raise BridgeError("Missing canonical interview boundary, refusing to replace existing content")
    return body[:start] + block + body[end:]


def prepare(args):
    project, engine = Path(args.project).resolve(), Path(args.engine).resolve()
    if not project.is_dir() or not engine.is_file() or not os.access(engine, os.X_OK):
        raise BridgeError("Supply an existing project and trusted installed native CLI executable")
    out = Path(args.out).resolve()
    if out.is_relative_to(project):
        raise BridgeError("Store the plan outside the project")
    version = command(engine, project, "--version").stdout.strip()
    path, meta, body, before = inspect(engine, project, args.target)
    draft = Path(args.draft).read_text(encoding="utf-8")
    proposed = render(meta, merge(body, draft))
    contexts = {project / "PRODUCT.md", project / "DESIGN.md"}
    contexts.update(Path(p).resolve() for p in args.context_file)
    plan = {
        "schema": 1, "project": str(project), "engine": str(engine), "cli_version": version,
        "target": meta["primary_target"], "surface_path": str(path), "before_sha256": before,
        "context": {str(p): digest(p) for p in sorted(contexts)}, "draft": draft,
        "proposed_sha256": hashlib.sha256(proposed.encode()).hexdigest(),
    }
    with out.open("x", encoding="utf-8") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    original = path.read_bytes().decode("utf-8") if before is not None else ""
    print("".join(difflib.unified_diff(original.splitlines(True), proposed.splitlines(True), fromfile=str(path), tofile=str(path))), end="")
    print(f"Plan: {out}\nNo project files written. Review the diff before apply.")


def apply(args):
    if not args.approved:
        raise BridgeError("Apply requires --approved after the caller obtains authorization for the change")
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if plan["schema"] != 1:
        raise BridgeError("Unsupported plan schema")
    project, engine = Path(plan["project"]), Path(plan["engine"])
    if command(engine, project, "--version").stdout.strip() != plan["cli_version"]:
        raise BridgeError("Impeccable changed since preparation")
    for name, expected in plan["context"].items():
        if digest(Path(name)) != expected:
            raise BridgeError(f"Context changed since preparation: {name}")
    path, meta, body, current = inspect(engine, project, plan["target"])
    if str(path) != plan["surface_path"]:
        raise BridgeError("Resolved target changed since preparation")
    if current == plan["proposed_sha256"]:
        print(json.dumps({"status": "unchanged", "surface_path": str(path)}))
        return
    if current != plan["before_sha256"]:
        raise BridgeError("Surface changed since preparation, prepare and review a new plan")
    proposed_body = merge(body, plan["draft"])
    expected = render(meta, proposed_body)
    if hashlib.sha256(expected.encode()).hexdigest() != plan["proposed_sha256"]:
        raise BridgeError("Plan content no longer matches its proposed digest")
    with tempfile.TemporaryDirectory(prefix="impeccable-interview-body-") as scratch:
        body_file = Path(scratch) / "body.md"
        body_file.write_text(proposed_body, encoding="utf-8")
        command(engine, project, "surface-brief", "write", meta["primary_target"], str(body_file), *meta["related_targets"])
    if path.read_bytes() != expected.encode():
        raise BridgeError("CLI write did not match the plan. Inspect the file, do not retry or roll back blindly")
    readback = command(engine, project, "surface-brief", "read", meta["primary_target"]).stdout
    if readback != expected:
        raise BridgeError("Readback differs from the plan. Inspect the saved brief")
    print(json.dumps({"status": "saved", "surface_path": str(path), "target": meta["primary_target"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="Read context and print a proposed diff, without changing the project")
    prepare_parser.add_argument("--project", required=True)
    prepare_parser.add_argument("--engine", required=True, help="Trusted installed native CLI executable, not an installer")
    prepare_parser.add_argument("--target", required=True)
    prepare_parser.add_argument("--draft", required=True)
    prepare_parser.add_argument("--out", required=True)
    prepare_parser.add_argument("--context-file", action="append", default=[])
    apply_parser = commands.add_parser("apply", help="Apply a reviewed plan through the official surface-brief writer")
    apply_parser.add_argument("--plan", required=True)
    apply_parser.add_argument("--approved", action="store_true")
    args = parser.parse_args()
    try:
        prepare(args) if args.command == "prepare" else apply(args)
    except (BridgeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

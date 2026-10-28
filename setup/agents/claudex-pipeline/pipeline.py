#!/usr/bin/env python3
"""Install the private role root and validate bounded pipeline control records."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

ROLES = {
    "explorer", "builder", "reviewer", "security-reviewer", "runner",
    "reconciliation-builder", "worklog-reporter",
}
WRITERS = {"builder", "reconciliation-builder"}
MANIFEST = ".claudex-owned.json"
LIMIT = 32768
SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
MODEL = re.compile(r"gpt-[0-9]+(?:\.[0-9]+)?-(?:sol|terra|luna)\Z")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,239}\Z")


class Rejected(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Rejected(message)


def read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(LIMIT + 1)
    require(len(data) <= LIMIT, "JSON exceeds control limit")
    return json.loads(data)


def keys(value, names):
    require(isinstance(value, dict) and set(value) == set(names.split()),
            "unexpected or missing fields")


def identifier(value):
    require(isinstance(value, str) and str(uuid.UUID(value)) == value,
            "expected canonical UUID")


def reference(value):
    require(isinstance(value, str) and REF.fullmatch(value) is not None
            and ".." not in value.split("/") and not value.startswith("/")
            and "://" not in value, "invalid opaque evidence reference")


def validate_control(value):
    keys(value, "version issue_id attempt_id role base_sha candidate_sha contract_digest cycle strategy_change payload_ref evidence_refs")
    require(type(value["version"]) is int and value["version"] == 1, "unknown version")
    for field in ("issue_id", "attempt_id"):
        identifier(value[field])
    require(value["role"] in ROLES, "unknown role")
    for field in ("base_sha", "candidate_sha"):
        require(isinstance(value[field], str) and SHA.fullmatch(value[field]), "invalid SHA")
    require(isinstance(value["contract_digest"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["contract_digest"]), "invalid contract digest")
    require(type(value["cycle"]) is int and 0 <= value["cycle"] <= 3, "repair limit exceeded")
    require(value["strategy_change"] is None or value["strategy_change"] in
            ("model", "worker", "approach", "environment"), "invalid strategy change")
    require(value["cycle"] < 3 or value["strategy_change"] is not None,
            "cycle three requires a changed strategy")
    reference(value["payload_ref"])
    refs = value["evidence_refs"]
    require(isinstance(refs, list) and len(refs) <= 16, "too many evidence refs")
    for ref in refs:
        reference(ref)
    return value


def validate_receipt(value, control=None):
    keys(value, "version issue_id attempt_id role candidate_sha session_id worker_id actual_model actual_effort effort_source status evidence_refs summary_ref")
    require(type(value["version"]) is int and value["version"] == 1, "unknown version")
    for field in ("issue_id", "attempt_id", "session_id"):
        identifier(value[field])
    require(value["role"] in ROLES, "unknown role")
    require(isinstance(value["candidate_sha"], str) and SHA.fullmatch(value["candidate_sha"]), "invalid SHA")
    require(isinstance(value["worker_id"], str) and re.fullmatch(r"a[0-9a-f]{8,64}", value["worker_id"]), "invalid native worker ID")
    require(value["actual_model"] is None or (isinstance(value["actual_model"], str)
            and MODEL.fullmatch(value["actual_model"])), "use a full supported model ID or null")
    require(value["actual_effort"] is None or value["actual_effort"] in
            ("off", "minimal", "low", "medium", "high", "xhigh", "max"), "invalid effort")
    require((value["actual_effort"] is None) == (value["effort_source"] is None),
            "effort needs a trusted evidence reference")
    if value["effort_source"] is not None:
        reference(value["effort_source"])
    require(value["status"] in ("pass", "needs_work", "blocked", "probe"), "invalid status")
    require(isinstance(value["evidence_refs"], list) and len(value["evidence_refs"]) <= 16, "too many refs")
    for ref in value["evidence_refs"]:
        reference(ref)
    reference(value["summary_ref"])
    if control is not None:
        validate_control(control)
        require(all(value[key] == control[key] for key in
                    ("issue_id", "attempt_id", "role", "candidate_sha")), "stale or mismatched receipt")
    return value


def admit_model(model, receipt=None, work_kind="reasoning"):
    require(isinstance(model, str) and MODEL.fullmatch(model), "use a full supported model ID")
    require(work_kind in ("bounded", "reasoning"), "unknown work kind")
    if model.endswith(("-terra", "-luna")):
        require(receipt is not None, "actual effort evidence required, use Sol or direct drafting")
        validate_receipt(receipt)
        allowed = {"max"}
        if model.endswith("-luna") and work_kind == "bounded":
            allowed |= {"off", "minimal", "low"}
        require(receipt["actual_model"] == model and receipt["actual_effort"] in allowed
                and receipt["effort_source"] is not None,
                "unconfirmed required effort, use Sol or direct drafting")
    return model


def parse_worklog(text):
    require(isinstance(text, str) and len(text.encode()) <= 2048, "worklog exceeds limit")
    labels = ("Completed work", "Current activity", "Next step", "Blocker")
    lines = text.strip().splitlines()
    require(len(lines) == len(labels), "expected exactly four worklog fields")
    fields = {}
    for label, line in zip(labels, lines):
        prefix = f"- {label}: "
        require(line.startswith(prefix), "missing, duplicate or reordered worklog field")
        value = line[len(prefix):]
        require(value.strip() == value and 0 < len(value) <= 300, "expected short nonempty field")
        require(not re.search(
            r"[{}\[\]<>`#]|sentinel|provenance|session[ _-]?id|worker[ _-]?id|"
            r"actual[ _-]?(?:model|effort)|evidence[ _-]?ref|summary[ _-]?ref|"
            r"\b(?:model|effort)\b|gpt-\d|ROLE_OK|<!--", value, re.IGNORECASE),
            "machine metadata or markup in worklog")
        fields[label.lower()] = value
    return fields


def git_bytes(repo, *arguments):
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    data = subprocess.check_output(["git", "-C", str(repo), *arguments], env=environment)
    require(len(data) <= LIMIT, "Git inventory exceeds limit")
    return data


def runtime_path(name):
    return name in (".claude", ".multica", "CLAUDE.md") or name.startswith((".claude/", ".multica/"))


def capture_baseline(repo):
    repo = repo.resolve()
    require(git_bytes(repo, "rev-parse", "--show-toplevel").decode().strip() == str(repo),
            "baseline requires repository root")
    require(not git_bytes(repo, "diff", "HEAD", "--raw")
            and not git_bytes(repo, "diff", "--cached", "--raw"), "dirty tracked/index state")
    untracked = git_bytes(repo, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    require(all(runtime_path(name) for name in untracked if name), "unexpected untracked product content")
    names = set(filter(None, git_bytes(repo, "ls-files", "--cached", "-z").decode().split("\0")))
    names.update(filter(None, untracked))
    # Include ignored startup files too. A runtime directory is not a blanket exemption.
    for name in (".claude", ".multica", "CLAUDE.md"):
        path = repo / name
        if path.is_dir() and not path.is_symlink():
            names.add(name)
            for directory, directories, files in os.walk(path, followlinks=False):
                for child in directories + files:
                    names.add((Path(directory) / child).relative_to(repo).as_posix())
                    require(len(names) <= 2048, "baseline inventory exceeds limit")
        elif path.exists() or path.is_symlink():
            names.add(name)
    require(len(names) <= 2048, "baseline inventory exceeds limit")
    inventory = {}
    total = 0
    for name in sorted(names):
        path = repo / name
        # Never follow a symlink ancestor into a different tree.
        require(not any(parent.is_symlink() for parent in path.parents if parent != repo),
                "symlink ancestor in baseline")
        mode = path.lstat().st_mode
        if path.is_symlink():
            digest = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
        elif path.is_dir():
            digest = None
        else:
            require(path.is_file(), "unsupported baseline entry")
            size = path.stat().st_size
            total += size
            require(total <= 32 * 1024 * 1024, "baseline content exceeds limit")
            digest = fingerprint(path)
        inventory[name] = {"mode": mode, "digest": digest}
    index = Path(git_bytes(repo, "rev-parse", "--path-format=absolute", "--git-path", "index").decode().strip())
    value = {
        "version": 1,
        "head": git_bytes(repo, "rev-parse", "HEAD").decode().strip(),
        "branch": git_bytes(repo, "rev-parse", "--abbrev-ref", "HEAD").decode().strip(),
        "status": git_bytes(repo, "status", "--porcelain=v1", "--untracked-files=all").decode(),
        "index": fingerprint(index),
        "worktrees": git_bytes(repo, "worktree", "list", "--porcelain").decode(),
        "runtime_paths": sorted(name for name in inventory if runtime_path(name)),
        "inventory": inventory,
    }
    require(len(json.dumps(value).encode()) <= LIMIT, "baseline record exceeds limit")
    return value


def verify_baseline(repo, baseline):
    require(capture_baseline(repo) == baseline, "repository baseline changed")


def atomic_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    require(len(data) <= LIMIT, "JSON exceeds control limit")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def safe_path(root, relative):
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts, "unsafe owned path")
    path = root / relative
    for ancestor in (path, *path.parents):
        require(not ancestor.is_symlink(), "symlink conflict")
    return path


def fingerprint(path):
    require(path.is_file() and not path.is_symlink(), "expected regular owned file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(source):
    names = ["pipeline.py", "skill/SKILL.md"] + [
        f".claude/agents/claudex-{role}.md" for role in sorted(ROLES)
    ]
    return {name: safe_path(source, name).read_bytes() for name in names}


def validate_package(source):
    names = set()
    for role in ROLES:
        text = (source / f".claude/agents/claudex-{role}.md").read_text()
        parts = text.split("---\n", 2)
        require(len(parts) == 3 and parts[0] == "", "missing frontmatter")
        # This package uses a strict YAML subset: mapping keys with JSON values.
        # Keeping the subset closed avoids a third-party installer dependency.
        meta = {}
        for line in parts[1].splitlines():
            key, separator, raw = line.partition(":")
            require(separator and re.fullmatch(r"[A-Za-z]+", key)
                    and key not in meta, "invalid frontmatter mapping")
            meta[key] = json.loads(raw.strip())
        require(meta["name"] == f"claudex-{role}" and meta["name"] not in names, "invalid or duplicate name")
        names.add(meta["name"])
        require(isinstance(meta["description"], str) and meta["description"], "missing description")
        require("model" not in meta and "effort" not in meta, "role must not pin model/effort")
        expected = {"Read", "Glob", "Grep"}
        if role in WRITERS:
            expected |= {"Edit", "Write"}
            require(meta.get("isolation") == "worktree", "writer needs native isolation")
        if role == "worklog-reporter":
            expected = set()
        require(set(meta["tools"]) == expected, "unexpected role capability")
        require({"Bash", "Agent", "Task", "ToolSearch"} <= set(meta["disallowedTools"]), "worker can escape tool boundary")
        for section in ("control-input", "boundaries", "output"):
            require(f"{{:#{section}}}" in parts[2], "missing role contract section")
    sources(source)


def reconcile(source, destination, operation):
    validate_package(source)
    require(destination.is_absolute(), "destination must be absolute")
    safe_path(destination, MANIFEST)
    desired = sources(source)
    manifest_path = destination / MANIFEST
    old = read_json(manifest_path) if manifest_path.exists() else {"version": 1, "files": {}}
    keys(old, "version files")
    require(old["version"] == 1 and isinstance(old["files"], dict), "invalid ownership manifest")
    require(set(old["files"]) <= set(desired), "unexpected owned path, preserve and review the manifest")
    for relative, digest in old["files"].items():
        require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), "invalid owned digest")
        path = safe_path(destination, relative)
        require(path.exists() and fingerprint(path) == digest, f"local conflict: {relative}")
    # Preflight the whole transaction before the first write or deletion.
    for relative, data in desired.items():
        path = safe_path(destination, relative)
        if path.exists() and relative not in old["files"]:
            require(fingerprint(path) == hashlib.sha256(data).hexdigest(), f"unowned conflict: {relative}")
    if operation == "status":
        require(manifest_path.exists() and set(old["files"]) == set(desired), "package is not managed")
        require(all(old["files"][name] == hashlib.sha256(data).hexdigest()
                    for name, data in desired.items()), "package is stale")
        return
    if operation == "uninstall":
        for relative in old["files"]:
            safe_path(destination, relative).unlink()
        if manifest_path.exists():
            manifest_path.unlink()
        return
    for relative in set(old["files"]) - set(desired):
        safe_path(destination, relative).unlink()
    for relative, data in desired.items():
        path = safe_path(destination, relative)
        if path.exists() and path.read_bytes() == data:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    new = {"version": 1, "files": {name: hashlib.sha256(data).hexdigest() for name, data in desired.items()}}
    if new != old or not manifest_path.exists():
        atomic_json(manifest_path, new)


def save_active(repo, value):
    keys(value, "version control receipt_refs blocker")
    require(type(value["version"]) is int and value["version"] == 1, "unknown version")
    control = validate_control(value["control"])
    require(isinstance(value["receipt_refs"], list) and len(value["receipt_refs"]) <= 16, "too many receipts")
    for ref in value["receipt_refs"]:
        reference(ref)
    if value["blocker"] is not None:
        keys(value["blocker"], "actor_ref condition_ref evidence_ref")
        for ref in value["blocker"].values():
            reference(ref)
    common = Path(subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True).strip())
    for sha in (control["base_sha"], control["candidate_sha"]):
        subprocess.run(["git", "-C", str(repo), "cat-file", "-e", sha + "^{commit}"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    relative = f"claudex-pipeline/v1/issues/{control['issue_id']}/active.json"
    path = safe_path(common, relative)
    atomic_json(path, value)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "status", "uninstall", "validate-package", "validate-control", "validate-receipt", "save-active", "select-model", "validate-worklog", "capture-baseline", "verify-baseline"))
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--destination", type=Path, default=Path.home() / ".claude/claudex-pipeline")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--model")
    parser.add_argument("--work-kind", choices=("bounded", "reasoning"), default="reasoning")
    args = parser.parse_args()
    try:
        if args.operation in ("install", "status", "uninstall"):
            reconcile(args.source, args.destination, args.operation)
        elif args.operation == "validate-package":
            validate_package(args.source)
        elif args.operation == "select-model":
            admit_model(args.model, read_json(args.file) if args.file else None, args.work_kind)
        elif args.operation in ("validate-worklog", "capture-baseline", "verify-baseline"):
            require(args.file is not None, "--file is required")
            if args.operation == "capture-baseline":
                require(not args.file.exists(), "baseline file already exists")
                atomic_json(args.file, capture_baseline(args.repo))
            elif args.operation == "verify-baseline":
                verify_baseline(args.repo, read_json(args.file))
            else:
                with args.file.open("rb") as stream:
                    text = stream.read(2049)
                require(len(text) <= 2048, "worklog exceeds limit")
                parse_worklog(text.decode())
        else:
            require(args.file is not None, "--file is required")
            value = read_json(args.file)
            if args.operation == "save-active":
                save_active(args.repo, value)
            elif args.operation == "validate-control":
                validate_control(value)
            else:
                require(args.control is not None, "--control is required to bind a receipt")
                validate_receipt(value, read_json(args.control))
        print(f"{args.operation}: ok")
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Do not print input values, provider errors, environment, or transcripts.
        detail = str(error) if isinstance(error, Rejected) else type(error).__name__
        print(f"{args.operation}: rejected ({detail})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

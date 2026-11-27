#!/usr/bin/env python3
"""List and check a repository's owner decision records, or set them up.

Usage: decisions.py init | list [--all] | check
Run from the repository root. Needs only Python 3.9 or newer and Git.
"""
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DECISIONS_DIR = "docs/decisions"
RULES_DIR = ".claude/rules"
DECISION_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
TITLE = re.compile(r"^# (.+)$", re.M)
SUPERSEDES = re.compile(r"^Supersedes: (.+)$", re.M)
UNTIL = re.compile(r"^Until: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) (KST|[+-]\d{2}:\d{2})$", re.M)
LINK = re.compile(r"\]\(([^)\s#]+\.md)(?:#[^)]*)?\)")
SECTION = "## Owner decisions"
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def decision_links(file, text):
    found = []
    for match in LINK.finditer(text):
        target = os.path.normpath(os.path.join(os.path.dirname(file), match.group(1)))
        if os.path.dirname(target) == DECISIONS_DIR and os.path.basename(target) != "README.md":
            found.append((target, match.start()))
    return found


def citations(file, text):
    return [(Path(target).stem, offset) for target, offset in decision_links(file, text)]


def parse_until(text):
    match = UNTIL.search(text)
    if match is None:
        return None
    offset = "+09:00" if match.group(2) == "KST" else match.group(2)
    sign = 1 if offset[0] == "+" else -1
    zone = timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6])))
    return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=zone)


def read_decisions(root):
    folder = root / DECISIONS_DIR
    decisions = []
    if not folder.is_dir():
        return decisions
    for path in sorted(folder.iterdir()):
        if not DECISION_FILE.match(path.name):
            continue
        file = f"{DECISIONS_DIR}/{path.name}"
        text = path.read_text(encoding="utf-8")
        supersedes = SUPERSEDES.search(text)
        title = TITLE.search(text)
        decisions.append({
            "id": path.stem,
            "file": file,
            "title": title.group(1) if title else path.stem,
            "supersedes": [cid for cid, _ in citations(file, supersedes.group(1))] if supersedes else [],
            "until": parse_until(text),
        })
    return decisions


def active(decision, superseded, now):
    return decision["id"] not in superseded and (decision["until"] is None or decision["until"] > now)


def repository_files(root):
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root, capture_output=True, text=True,
    )
    if listed.returncode == 0:
        return [file for file in listed.stdout.splitlines() if (root / file).is_file()]
    found = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = [name for name in dirs if name not in (".git", "node_modules")]
        found.extend(os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/") for name in names)
    return found


def locate(text, offset):
    before = text[:offset].split("\n")
    return len(before), len(before[-1]) + 1


def check(root, now):
    files = repository_files(root)
    decisions = read_decisions(root)
    superseded = {cid for decision in decisions for cid in decision["supersedes"]}
    cited = set()
    findings = []
    for file in files:
        if file.startswith(f"{DECISIONS_DIR}/") and file.count("/") == 2:
            name = os.path.basename(file)
            if name != "README.md" and not DECISION_FILE.match(name):
                findings.append((file, 1, 1, "decisions/name", f"{name} is not named YYYY-MM-DD-short-slug.md"))
        if not file.endswith(".md"):
            continue
        text = (root / file).read_text(encoding="utf-8", errors="replace")
        for target, offset in decision_links(file, text):
            if not (root / target).is_file():
                line, column = locate(text, offset)
                findings.append((file, line, column, "decisions/reference", f"{target} does not exist"))
        if file.startswith(f"{RULES_DIR}/"):
            for cid, offset in citations(file, text):
                cited.add(cid)
                if cid in superseded:
                    line, column = locate(text, offset)
                    findings.append((file, line, column, "decisions/superseded-citation", f"{cid} is superseded by a later decision"))
    for decision in decisions:
        if active(decision, superseded, now) and decision["id"] not in cited:
            findings.append((decision["file"], 1, 1, "decisions/uncited", f"no page in {RULES_DIR}/ cites this active decision"))
    return sorted(findings)


FIXES = {
    "decisions/name": "Name the record after the date of the user's first quoted words and a slug of its content.",
    "decisions/reference": "Link to an existing record. `decisions.py list --all` lists them.",
    "decisions/uncited": f"Write the decision's current rule into the {RULES_DIR}/ page of its topic, with a link to the record.",
    "decisions/superseded-citation": "Restate the rule from the record that supersedes this one, and link to that record instead.",
}


def init(root):
    created = []
    script = root / "tools/decisions/decisions.py"
    if not script.exists():
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).resolve(), script)
        script.chmod(0o755)
        created.append(str(script.relative_to(root)))
    for source, target in (("README.md", f"{DECISIONS_DIR}/README.md"), ("process.md", f"{RULES_DIR}/process.md")):
        path = root / target
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATES / source, path)
            created.append(target)
    agents = root / "AGENTS.md"
    text = agents.read_text(encoding="utf-8") if agents.exists() else f"# {root.name}\n"
    if SECTION not in text:
        agents.write_text(text.rstrip("\n") + "\n\n" + (TEMPLATES / "agents-section.md").read_text(encoding="utf-8"), encoding="utf-8")
        created.append("AGENTS.md")
    claude = root / "CLAUDE.md"
    if not claude.exists():
        claude.write_text("@AGENTS.md\n", encoding="utf-8")
        created.append("CLAUDE.md")
    elif "@AGENTS.md" not in claude.read_text(encoding="utf-8"):
        print("CLAUDE.md does not import AGENTS.md. Add an `@AGENTS.md` line so Claude Code loads the section.")
    for item in created:
        print(f"created or updated {item}")
    return 0


def main(argv):
    root = Path.cwd()
    command = argv[1] if len(argv) > 1 else ""
    if command == "init":
        return init(root)
    if command == "list":
        decisions = read_decisions(root)
        superseded = {cid for decision in decisions for cid in decision["supersedes"]}
        now = datetime.now(timezone.utc)
        for decision in decisions:
            is_active = active(decision, superseded, now)
            if is_active or "--all" in argv:
                print(f"{decision['file']}  {decision['title']}{'' if is_active else '  (inactive)'}")
        return 0
    if command == "check":
        findings = check(root, datetime.now(timezone.utc))
        for file, line, column, rule, message in findings:
            print(f"{file}:{line}:{column}  {rule}  {message}\n  fix: {FIXES[rule]}")
        return 1 if findings else 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

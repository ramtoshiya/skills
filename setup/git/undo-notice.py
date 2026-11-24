"""Git post-commit hook: name earlier commits that the new commit switches back.

Agents in separate sessions can undo each other's recent decisions without
noticing, and the next session switches them back again. After each commit,
this compares the commit with the last week of commits to the same files and
prints each one that it reverses: lines that commit added are removed here,
and lines it removed come back. Commits from the last two hours are skipped,
because those are usually the same session fixing its own work.
"""

import subprocess
import sys
from dataclasses import dataclass, field

SINCE = "7.days"
SAME_SESSION_SECONDS = 2 * 3600
MARK = "@@undo-notice "


@dataclass
class Commit:
    sha: str
    time: int
    subject: str
    added: set = field(default_factory=set)
    removed: set = field(default_factory=set)


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def meaningful(text):
    return sum(c.isalnum() for c in text) >= 3


def parse(log):
    commits, path = [], None
    for line in log.splitlines():
        if line.startswith(MARK):
            sha, time, subject = (line[len(MARK):] + "  ").split(" ", 2)
            commits.append(Commit(sha, int(time), subject.strip()))
        elif line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("--- ") or not commits or path is None:
            continue
        elif line[:1] in ("+", "-") and meaningful(text := line[1:].strip()):
            (commits[-1].added if line[0] == "+" else commits[-1].removed).add((path, text))
    return commits


def log(*args):
    return parse(git("log", "--no-merges", "-p", "-U0", "--no-ext-diff", "--no-color",
                     f"--format={MARK}%h %ct %s", *args))


def reversed_by(new, old):
    back = new.removed & old.added
    restored = new.added & old.removed
    if len(back) >= 2 and restored and min(len(back), len(restored)) >= 0.5 * min(len(old.added), len(old.removed)):
        return back
    return None


def main():
    head = log("-1", "HEAD")
    if not head or not git("rev-parse", "--verify", "--quiet", "HEAD^"):
        return
    new = head[0]
    files = sorted({path for path, _ in new.removed})
    if not files:
        return
    for old in log(f"--since={SINCE}", "HEAD^", "--", *files):
        if new.time - old.time < SAME_SESSION_SECONDS:
            continue
        back = reversed_by(new, old)
        if back:
            paths = ", ".join(sorted({path for path, _ in back}))
            print(f"undo-notice: this commit switches back {old.sha} \"{old.subject}\" "
                  f"({len(back)} of its added lines removed, in {paths}). "
                  f"If that change was deliberate, read `git show {old.sha}` and settle the "
                  f"disagreement instead of switching it back.", file=sys.stderr)


if __name__ == "__main__":
    main()

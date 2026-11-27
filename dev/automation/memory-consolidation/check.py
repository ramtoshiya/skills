"""Daily check of the Hermes learning store. Starts a consolidation thread only when there is work.

Usage: check.py [--mark <until>]
There is work when memory or a learned skill changed since the last consolidation finished, or when the user
wrote to a bb thread since then. Otherwise it prints nothing, so the bb automation records a silent tick. The
daily schedule keeps runs at least a day apart. --mark records the store as consolidated and the user's messages
up to <until> (epoch milliseconds) as read. The consolidation thread runs it as its last step, so a thread that
stops early leaves the changes and the messages for the next day's check.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
REPO = HERE.parents[2]
PLUGIN = REPO / "plugins/ramtoshiya-cc/hermes-learning"
CLI = PLUGIN / "hermes-learning"
NEWEST_MODEL = REPO / "plugins/ramtoshiya/skills/worker-routing/scripts/newest-model"
sys.path.insert(0, str(PLUGIN))
from hook import learned_skills  # noqa: E402

# Hermes's default limits. The learning store's profile does not override them.
LIMITS = {"memory": ("MEMORY.md", 2200), "user": ("USER.md", 1375)}
CONSOLIDATE_AT = 0.8
TARGET = 0.6
TIMEZONE = "Asia/Seoul"
MARK = "consolidated.json"
FIRST_WINDOW_MS = 24 * 3600 * 1000
MESSAGE_CHARS = 2000
REPLY_CHARS = 1000
CONSOLIDATION_TITLE = "Hermes memory consolidation"


def store() -> Path:
    return Path(os.environ.get("HERMES_LEARNING_HOME") or "~/.hermes/profiles/coder").expanduser()


def usage(home: Path) -> dict:
    found = {}
    for target, (name, limit) in LIMITS.items():
        path = home / "memories" / name
        found[target] = {"chars": len(path.read_text(encoding="utf-8").strip()) if path.is_file() else 0,
                         "limit": limit}
    return found


def digest(files) -> str:
    hashed = hashlib.sha256()
    for path, relative in files:
        hashed.update(f"{relative}\0".encode() + path.read_bytes() + b"\0")
    return hashed.hexdigest()


def fingerprint(home: Path) -> dict:
    """A digest of each memory target and each learned skill folder, without hidden files such as usage counts."""
    memories = {target: digest([(home / "memories" / name, name)] if (home / "memories" / name).is_file() else [])
                for target, (name, _) in LIMITS.items()}
    skills = {}
    for name, folder in learned_skills(home).items():
        files = sorted(path for path in folder.rglob("*") if path.is_file()
                       and not any(part.startswith(".") for part in path.relative_to(folder).parts))
        skills[name] = digest((path, path.relative_to(folder).as_posix()) for path in files)
    return {"memory": memories, "skills": skills}


def marked(home: Path) -> dict:
    path = home / MARK
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"memory": {}, "skills": {}}


def changes(before: dict, now: dict) -> dict:
    return {"memory": sorted(t for t in now["memory"] if now["memory"][t] != before["memory"].get(t)),
            "skills": sorted(n for n in now["skills"].keys() | before["skills"].keys()
                             if now["skills"].get(n) != before["skills"].get(n))}


def bb(*args) -> str:
    return subprocess.run([os.environ.get("BB_CLI", "bb"), *args], capture_output=True, text=True,
                          check=True).stdout


def user_text(data: dict) -> str:
    """The text of a turn the user typed. bb marks a message from another thread with its sender, and a
    thread's first message can be an agent's or an automation's brief, so only the user's later messages count."""
    if data.get("initiator") != "user" or data.get("senderThreadId") or data.get("source") != "tell":
        return ""
    return "\n".join(part.get("text", "") for part in data.get("input") or [] if part.get("type") == "text").strip()


def thread_messages(thread: dict, since: int, until: int) -> list:
    events = json.loads(bb("thread", "log", thread["id"], "--json", "--all") or "[]")
    found, reply = [], ""
    for event in events:
        data = event.get("data") or {}
        item = data.get("item") or {}
        if event["type"] == "item/completed" and item.get("type") == "agentMessage":
            reply = item.get("text") or ""
        elif event["type"] == "client/turn/requested" and since < event["createdAt"] <= until:
            text = user_text(data)
            if text:
                found.append({"thread": thread["id"], "title": thread.get("title"), "msg": event["seq"],
                              "at": datetime.fromtimestamp(event["createdAt"] / 1000, ZoneInfo(TIMEZONE))
                              .strftime("%Y-%m-%d %H:%M"),
                              "agent_before": reply[-REPLY_CHARS:], "user": text[:MESSAGE_CHARS]})
    return found


def user_messages(since: int, until: int) -> list:
    """The user's messages in bb threads that no other thread started, oldest thread first."""
    threads = json.loads(bb("thread", "list", "--include-archived", "--include-hidden", "--json"))
    wanted = sorted((thread for thread in threads if not thread.get("parentThreadId")
                     and thread["updatedAt"] > since
                     and not (thread.get("title") or "").startswith(CONSOLIDATION_TITLE)),
                    key=lambda thread: thread["createdAt"])
    return [message for thread in wanted for message in thread_messages(thread, since, until)]


def mark(home: Path, until: int) -> None:
    temporary = home / f".{MARK}.tmp"
    temporary.write_text(json.dumps({**fingerprint(home), "messagesUntil": until}, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(home / MARK)
    print(f"Marked {home} as consolidated")


def main():
    home = store()
    if sys.argv[1:2] == ["--mark"]:
        return mark(home, int(sys.argv[2]))
    before = marked(home)
    until = int(time.time() * 1000)
    changed = changes(before, fingerprint(home))
    messages = user_messages(before.get("messagesUntil") or until - FIRST_WINDOW_MS, until)
    state = {"store": str(home), "usage": usage(home), "changed": changed}
    if not changed["memory"] and not changed["skills"] and not messages:
        return
    model = subprocess.run([str(NEWEST_MODEL), "sonnet"], capture_output=True, text=True, check=True).stdout.strip()
    prompt = ((HERE / "prompt.md").read_text(encoding="utf-8")
              .replace("{{CLI}}", f"HERMES_LEARNING_HOME={home} {CLI}")
              .replace("{{MARK}}", f"HERMES_LEARNING_HOME={home} {sys.executable} -I {Path(__file__).resolve()} "
                                   f"--mark {until}")
              .replace("{{TARGET}}", f"{int(TARGET * 100)}%")
              .replace("{{CONSOLIDATE_AT}}", f"{int(CONSOLIDATE_AT * 100)}%")
              + f"\n## State {{:#state}}\n\n```json\n{json.dumps(state, indent=2)}\n```\n"
              + f"\n## The user's messages {{:#messages}}\n\n```json\n"
              f"{json.dumps(messages, indent=1, ensure_ascii=False)}\n```\n")
    today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    with tempfile.TemporaryDirectory() as folder:
        prompt_file = Path(folder) / "prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        # The checkout's existing environment. Without one bb creates a worktree, which this thread never uses.
        shown = json.loads(bb("thread", "spawn", "--project", os.environ["BB_PROJECT_ID"], "--environment", str(REPO),
                              "--permission-mode", "full",
                              "--provider", "claude-code", "--model", model, "--reasoning-level", "high",
                              "--title", f"Hermes memory consolidation {today}", "--prompt-file", str(prompt_file),
                              "--json"))
    print(f"Started {shown.get('id') or shown['thread']['id']}: changed memory {changed['memory'] or 'none'}, "
          f"skills {changed['skills'] or 'none'}, user messages {len(messages)}")


if __name__ == "__main__":
    sys.exit(main())

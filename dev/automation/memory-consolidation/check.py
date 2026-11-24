"""Daily check of the Hermes learning store's memory. Starts a consolidation thread only when there is work.

Usage: check.py
There is work when a target is at CONSOLIDATE_AT of its limit or more, or when a review fork staged a memory
write, which happens when a lesson needs an entry removed or rewritten. Otherwise it prints nothing, so the bb
automation records a silent tick.
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
REPO = HERE.parents[2]
CLI = REPO / "plugins/ramtoshiya-cc/hermes-learning/hermes-learning"
NEWEST_MODEL = REPO / "plugins/ramtoshiya/skills/worker-routing/scripts/newest-model"
# Hermes's default limits. The coder profile does not override them.
LIMITS = {"memory": ("MEMORY.md", 2200), "user": ("USER.md", 1375)}
CONSOLIDATE_AT = 0.8
TARGET = 0.6
TIMEZONE = "Asia/Seoul"


def store() -> Path:
    return Path(os.environ.get("HERMES_LEARNING_HOME") or "~/.hermes/profiles/coder").expanduser()


def usage(home: Path) -> dict:
    found = {}
    for target, (name, limit) in LIMITS.items():
        path = home / "memories" / name
        found[target] = {"chars": len(path.read_text(encoding="utf-8").strip()) if path.is_file() else 0,
                         "limit": limit}
    return found


def staged(home: Path) -> list:
    folder = home / "pending" / "memory"
    return sorted(path.stem for path in folder.glob("*.json")) if folder.is_dir() else []


def bb(*args) -> str:
    return subprocess.run([os.environ.get("BB_CLI", "bb"), *args], capture_output=True, text=True,
                          check=True).stdout


def main():
    home = store()
    state = {"store": str(home), "usage": usage(home), "staged": staged(home)}
    full = [t for t, u in state["usage"].items() if u["chars"] >= CONSOLIDATE_AT * u["limit"]]
    if not full and not state["staged"]:
        return
    model = subprocess.run([str(NEWEST_MODEL), "sonnet"], capture_output=True, text=True, check=True).stdout.strip()
    prompt = ((HERE / "prompt.md").read_text(encoding="utf-8")
              .replace("{{CLI}}", f"HERMES_LEARNING_HOME={home} {CLI}")
              .replace("{{TARGET}}", f"{int(TARGET * 100)}%")
              + f"\n## State {{:#state}}\n\n```json\n{json.dumps(state, indent=2)}\n```\n")
    today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    with tempfile.TemporaryDirectory() as folder:
        prompt_file = Path(folder) / "prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        shown = json.loads(bb("thread", "spawn", "--project", os.environ["BB_PROJECT_ID"], "--permission-mode", "full",
                              "--provider", "claude-code", "--model", model, "--reasoning-level", "high",
                              "--title", f"Hermes memory consolidation {today}", "--prompt-file", str(prompt_file),
                              "--json"))
    print(f"Started {shown.get('id') or shown['thread']['id']}: over {CONSOLIDATE_AT:.0%} {full or 'none'}, "
          f"staged {len(state['staged'])}")


if __name__ == "__main__":
    sys.exit(main())

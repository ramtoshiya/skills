from __future__ import annotations

import json
from pathlib import Path

CACHE_READ_WEIGHT = 0.1
PURPOSES = ("coding", "review", "title", "aux")


def cost(row: dict) -> float:
    return row["fresh_input"] + CACHE_READ_WEIGHT * row["cache_read"]


def summarize(rows: list[dict]) -> list[dict]:
    conversations: dict[str, dict] = {}
    for row in rows:
        entry = conversations.setdefault(row.get("conversation") or "", {
            "conversation": row.get("conversation") or "", "first": row["ts"], "models": [],
            **{purpose: {"requests": 0, "fresh_input": 0, "cache_read": 0, "output": 0, "cost": 0.0}
               for purpose in PURPOSES}})
        if row["model"] not in entry["models"]:
            entry["models"].append(row["model"])
        totals = entry[row["purpose"]]
        totals["requests"] += 1
        for field in ("fresh_input", "cache_read", "output"):
            totals[field] += row[field]
        totals["cost"] += cost(row)
    for entry in conversations.values():
        coding = entry["coding"]["cost"]
        entry["a"] = round(entry["review"]["cost"] / coding, 3) if coding else None
    return sorted(conversations.values(), key=lambda entry: entry["first"])


def table(summary: list[dict]) -> str:
    def k(value: float) -> str:
        return f"{value / 1000:.1f}k"

    lines = ["conversation          models              coding: n  fresh  cache  out   review: n  fresh  cache  out"
             "   title: n  cost       a"]
    for entry in summary:
        coding, review, title = entry["coding"], entry["review"], entry["title"]
        lines.append(
            f"{(entry['conversation'] or '(no session)')[:20]:<21} {','.join(entry['models'])[:19]:<19} "
            f"{coding['requests']:>9} {k(coding['fresh_input']):>6} {k(coding['cache_read']):>6} {k(coding['output']):>5}"
            f" {review['requests']:>10} {k(review['fresh_input']):>6} {k(review['cache_read']):>6} {k(review['output']):>5}"
            f" {title['requests']:>9} {k(title['cost'] + entry['aux']['cost']):>5}"
            f" {'-' if entry['a'] is None else entry['a']:>7}")
    return "\n".join(lines)


def usage_file() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home()) / "claude-code-runtime" / "usage.jsonl"


def arguments(parser) -> None:
    parser.add_argument("action", choices=["usage", "reload"])
    parser.add_argument("--json", action="store_true", help="print the usage summary as JSON")


def command(args) -> int:
    if args.action == "reload":
        from hermes_cli.plugins_activation import reload_running_gateway
        print(json.dumps(reload_running_gateway()))
        return 0
    path = usage_file()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.is_file() else []
    summary = summarize(rows)
    print(json.dumps(summary, indent=1) if args.json else table(summary))
    return 0


def register(ctx) -> None:
    ctx.register_cli_command("claude-code", "Token use of the claude-code-runtime provider, and plugin reload",
                             arguments, command)

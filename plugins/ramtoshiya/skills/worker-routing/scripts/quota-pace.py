from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SIDES = ("claude", "codex")
WEEK = timedelta(days=7)
LOOKBACK = timedelta(hours=24)
MIN_SPAN = timedelta(hours=6)
RESET_JITTER = timedelta(minutes=2)
ROUNDING = 1.0
KEEP = timedelta(days=8)
HISTORY_SCHEMA = 2
HISTORY_METRICS = {
    "895bb5f0186a2900bda8665dac046ba0cca7c482d5a59b80f3f02405b7da3aec": "claude",
    "codex-weekly": "codex",
}
QUOTIO_CLI = (
    "quotio-cli",
    "~/.local/bin/quotio-cli",
    "/Applications/Quotio.app/Contents/Helpers/quotio-cli",
    "/Applications/Quotio Beta.app/Contents/Helpers/quotio-cli",
)
OFFER_SCOPES = {
    "claude-weekly": "Claude weekly limit. The reset keeps the existing weekly schedule",
    "claude-fable": "Claude Fable models only. Does not restore the weekly limit",
}


@dataclass(frozen=True)
class Sample:
    at: datetime
    used: float
    resets_at: datetime


@dataclass(frozen=True)
class Reading:
    weekly: Sample
    fable_resets_at: datetime | None = None


@dataclass(frozen=True)
class Limit:
    since: datetime
    until: datetime | None


@dataclass
class Side:
    status: str
    used: float | None = None
    resets_at: str | None = None
    limit_resets_at: str | None = None
    pace_per_hour: float | None = None
    pace_hours: float | None = None
    pace_source: str | None = None
    projected_at_reset: float | None = None
    runs_out_at: str | None = None
    note: str | None = None


def parse_time(value) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def same_window(a: Sample, b: Sample) -> bool:
    return abs(a.resets_at - b.resets_at) <= RESET_JITTER


def readings_from_bb(data, now) -> dict[str, list[Reading]]:
    found: dict[str, list[Reading]] = {side: [] for side in SIDES}
    names = {"claude-code": "claude", "codex": "codex"}
    for machine in data.get("machines") or []:
        for provider in machine.get("providers") or []:
            side = names.get(provider.get("providerId"))
            usage = provider.get("usage") or {}
            if side is None or usage.get("status") != "ok":
                continue
            windows = {w.get("label"): w for w in usage.get("windows") or []}
            weekly = windows.get("Weekly limit") or {}
            if weekly.get("usedPercent") is None or not weekly.get("resetsAt"):
                continue
            fable = (windows.get("Weekly · Fable") or {}).get("resetsAt")
            found[side].append(Reading(
                Sample(now, float(weekly["usedPercent"]), parse_time(weekly["resetsAt"])),
                parse_time(fable) if fable else None,
            ))
    return found


def readings_from_quotio(data, now) -> dict[str, list[Reading]]:
    found: dict[str, list[Reading]] = {side: [] for side in SIDES}
    providers = {account.get("id"): account.get("provider_id") for account in data.get("accounts") or []}
    for usage in data.get("usage") or []:
        side = providers.get(usage.get("account_id"))
        if side not in SIDES:
            continue
        metrics = {m.get("display_name"): m for m in usage.get("metrics") or []}
        weekly = metrics.get("Weekly") or {}
        used = (weekly.get("quota") or {}).get("used_percent")
        if used is None or not weekly.get("resets_at"):
            continue
        fable = (metrics.get("Fable") or {}).get("resets_at")
        found[side].append(Reading(
            Sample(now, float(used), parse_time(weekly["resets_at"])),
            parse_time(fable) if fable else None,
        ))
    return found


def current_readings(text: str, now) -> tuple[dict[str, Reading], list[str]]:
    notes = []
    if not text.strip():
        return {}, []
    try:
        data = json.loads(text)
    except ValueError:
        return {}, ["Standard input is not lookup JSON. Run the lookup alone to see its output."]
    found = readings_from_bb(data, now) if "machines" in data else readings_from_quotio(data, now)
    current = {}
    for side, readings in found.items():
        if len(readings) == 1:
            current[side] = readings[0]
        elif readings:
            notes.append(f"The lookup returned {len(readings)} {side} accounts. Their readings are ignored.")
    return current, notes


def read_quotio(sides: list[str], now) -> tuple[dict[str, Reading], str | None]:
    cli = next(filter(None, (shutil.which(os.path.expanduser(c)) for c in QUOTIO_CLI)), None)
    if cli is None:
        return {}, f"quotio-cli was not found, so {', '.join(sides)} has no reading"
    providers = [flag for side in sides for flag in ("--provider", side)]
    try:
        result = subprocess.run(
            [cli, "usage", *providers, "--no-saved-accounts", "--format", "json"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {}, f"quotio-cli failed with {type(error).__name__}, so {', '.join(sides)} has no reading"
    readings, _ = current_readings(result.stdout, now)
    found = {side: readings[side] for side in sides if side in readings}
    missing = [side for side in sides if side not in found]
    if missing:
        return found, f"quotio-cli exited {result.returncode} without a reading for {', '.join(missing)}"
    return found, None


def history_samples(path: Path, now) -> tuple[dict[str, dict[int, list[Sample]]], str | None]:
    if not path.exists():
        return {}, "Quotio history store not found"
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as error:
        return {}, f"Quotio history store could not be opened: {error}"
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != HISTORY_SCHEMA:
            return {}, f"Quotio history schema version {version} is not supported"
        rows = connection.execute(
            "SELECT s.metric, s.account, s.metadata, o.payload FROM history_series s "
            "JOIN history_observations o ON o.series = s.id "
            f"WHERE s.metric IN ({','.join('?' * len(HISTORY_METRICS))})",
            tuple(HISTORY_METRICS),
        ).fetchall()
    except sqlite3.Error as error:
        return {}, f"Quotio history store could not be read: {error}"
    finally:
        connection.close()
    accounts: dict[str, int] = {}
    samples: dict[str, dict[int, list[Sample]]] = {side: {} for side in SIDES}
    for metric, account, metadata, payload in rows:
        try:
            if json.loads(metadata).get("display_name") != "Weekly":
                continue
            observation = json.loads(payload)
        except ValueError:
            continue
        used = (observation.get("quota") or {}).get("used_percent")
        if used is None or not observation.get("fetched_at") or not observation.get("resets_at"):
            continue
        sample = Sample(parse_time(observation["fetched_at"]), float(used), parse_time(observation["resets_at"]))
        if now - KEEP <= sample.at <= now:
            key = accounts.setdefault(account, len(accounts))
            samples[HISTORY_METRICS[metric]].setdefault(key, []).append(sample)
    for by_account in samples.values():
        for series in by_account.values():
            series.sort(key=lambda s: s.at)
    return samples, None


def state_path() -> Path:
    root = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(root) / "ramtoshiya" / "quota-samples.json"


def load_state(path: Path) -> dict[str, list[Sample]]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {side: [] for side in SIDES}
    return {
        side: [Sample(parse_time(at), float(used), parse_time(resets)) for at, used, resets in raw.get(side, [])]
        for side in SIDES
    }


def save_state(path: Path, state: dict[str, list[Sample]], now) -> None:
    kept = {
        side: [[iso(s.at), s.used, iso(s.resets_at)] for s in samples if s.at >= now - KEEP]
        for side, samples in state.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(kept))
    temporary.replace(path)


def pick_account(by_account: dict[int, list[Sample]], current: Sample | None, now) -> tuple[list[Sample], str | None]:
    recent = {key: series for key, series in by_account.items() if series[-1].at >= now - LOOKBACK}
    if len(recent) > 1 and current is not None:
        recent = {
            key: series for key, series in recent.items()
            if same_window(series[-1], current) and abs(series[-1].used - current.used) <= ROUNDING
        }
    if len(recent) > 1:
        return [], "Quotio history has several accounts in use for this side"
    return next(iter(recent.values()), []), None


def current_window(samples: list[Sample]) -> list[Sample]:
    window = samples[-1:]
    for sample in reversed(samples[:-1]):
        if not same_window(sample, window[0]) or sample.used > window[0].used + ROUNDING:
            break
        window.insert(0, sample)
    return window


def recent_pace(samples: list[Sample], now) -> tuple[float, float] | None:
    recent = [s for s in current_window(samples) if s.at >= now - LOOKBACK]
    if len(recent) < 2 or recent[-1].at - recent[0].at < MIN_SPAN:
        return None
    hours = (recent[-1].at - recent[0].at).total_seconds() / 3600
    return max(0.0, recent[-1].used - recent[0].used) / hours, hours


def recovered(samples: list[Sample], reading: Sample, since: datetime) -> bool:
    if reading.at <= since:
        return False
    if reading.resets_at - WEEK > since:
        return True
    before = [s for s in samples if s.at <= since]
    return bool(before) and same_window(before[-1], reading) and reading.used < before[-1].used - ROUNDING


def forecast(reading: Sample | None, sources: list[tuple[str, list[Sample]]], limit: Limit | None, now) -> Side:
    if limit is not None and limit.until is not None:
        return Side(
            "limited", used=reading.used if reading else None,
            resets_at=iso(reading.resets_at) if reading else None, limit_resets_at=iso(limit.until),
            note=f"A usage limit was hit at {iso(limit.since)}. The error named its reset at {iso(limit.until)}",
        )
    if reading is None and limit is not None:
        return Side("limited", note=f"A usage limit was hit at {iso(limit.since)} and no reading since shows the quota renewed")
    if reading is None:
        return Side("no-reading", note="No current weekly reading")
    side = Side("unknown", used=reading.used, resets_at=iso(reading.resets_at))
    known = sorted((s for _, samples in sources for s in samples if s.at < reading.at), key=lambda s: s.at)
    if reading.used >= 100:
        side.status, side.note = "limited", "The weekly reading is at 100%"
        return side
    if limit is not None and not recovered(known, reading, limit.since):
        side.status = "limited"
        side.note = f"A usage limit was hit at {iso(limit.since)} and no reading since shows the quota renewed"
        return side
    if reading.resets_at <= now:
        side.note = "The reading's scheduled reset has passed"
        return side
    for name, samples in sources:
        pace = recent_pace([s for s in samples if s.at < reading.at] + [reading], now)
        if pace is not None:
            break
    else:
        side.note = "No recent pace: fewer than 6 hours of samples from the current window in the last 24 hours"
        return side
    per_hour, hours = pace
    hours_left = (reading.resets_at - now).total_seconds() / 3600
    side.pace_per_hour, side.pace_hours, side.pace_source = round(per_hour, 2), round(hours, 1), name
    side.projected_at_reset = round(reading.used + per_hour * hours_left, 1)
    if side.projected_at_reset >= 100:
        side.status = "runs-out"
        side.runs_out_at = iso(now + timedelta(hours=(100 - reading.used) / per_hour))
    else:
        side.status = "fits"
    return side


def choose(prefer: str, eligible: list[str], sides: dict[str, Side], work: float, spill: bool):
    home = prefer if prefer in eligible else eligible[0]
    open_sides = [s for s in eligible if sides[s].status != "limited"]
    if home in open_sides:
        if spill and sides[home].status == "runs-out":
            for alternative in open_sides:
                projected = sides[alternative].projected_at_reset
                if alternative != home and sides[alternative].status == "fits" and projected + work < 100:
                    return alternative, (
                        f"{home} runs out at {sides[home].runs_out_at}, before its reset at {sides[home].resets_at}. "
                        f"{alternative} projects {projected}% at its reset"
                    )
            return home, f"{home} projects running out, and no other eligible side projects room through its reset"
        return home, f"{home} is the default side and has capacity"
    observed = [s for s in open_sides if sides[s].used is not None]
    if observed:
        alternative = observed[0]
        return alternative, (
            f"{home} is limited. {alternative} reads {sides[alternative].used}%, status {sides[alternative].status}"
        )
    return None, (
        f"{home} is limited, and no other eligible side has a current reading below 100%. "
        "Report the outage, the scheduled resets, and the reset options"
    )


def read_codex_credits() -> tuple[list[dict], str | None]:
    requests = [
        {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "quota-pace", "version": "1"}}},
        {"method": "initialized"},
        {"id": 2, "method": "account/rateLimits/read", "params": None},
    ]
    try:
        process = subprocess.Popen(
            ["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True,
        )
    except OSError as error:
        return [], f"codex app-server could not start: {error}"
    timer = threading.Timer(30, process.kill)
    timer.start()
    result = None
    try:
        process.stdin.write("".join(json.dumps(r) + "\n" for r in requests))
        process.stdin.flush()
        for line in process.stdout:
            message = json.loads(line)
            if message.get("id") == 2:
                result = message.get("result")
                break
    except (OSError, ValueError):
        pass
    finally:
        timer.cancel()
        process.kill()
        process.wait()
    if result is None:
        return [], "codex app-server returned no rate limit read"
    summary = result.get("rateLimitResetCredits") or {}
    credits = [c for c in summary.get("credits") or [] if c.get("status") == "available"]
    options = [
        {
            "scope": "Codex weekly full reset" if c.get("resetType") == "codexRateLimits" else f"Codex {c.get('resetType')}",
            "claim_by": iso(parse_time(c["expiresAt"])) if c.get("expiresAt") else "no deadline",
        }
        for c in credits
    ]
    missing = (summary.get("availableCount") or 0) - len(options)
    if missing > 0:
        options.append({"scope": f"{missing} more Codex reset credits without details", "claim_by": "unknown"})
    return options, None


def reset_options(eligible, sides, readings, offers, now) -> dict:
    report: dict = {"note": "Only a person redeems a reset. Never redeem one for them."}
    for side in eligible:
        f = sides[side]
        if f.status not in ("limited", "runs-out"):
            continue
        weekly_reset = parse_time(f.resets_at) if f.resets_at else None
        scheduled = f.limit_resets_at or f.resets_at
        reset = parse_time(scheduled) if scheduled else None
        entry: dict = {"scheduled_reset": scheduled or "unknown, no current reading"}
        if reset is not None:
            start = now if f.status == "limited" else max(now, parse_time(f.runs_out_at))
            outage_hours = max(0.0, (reset - start).total_seconds() / 3600)
            entry["outage_hours_before_reset"] = round(outage_hours, 1)
            if f.pace_per_hour is not None:
                entry["expected_use_in_outage"] = round(min(100.0, f.pace_per_hour * outage_hours), 1)
        if side == "codex":
            options, error = read_codex_credits()
            for option in options:
                option["if_claimed_now_lasts_until"] = iso(now + WEEK)
                option["schedule"] = "Claiming restarts the weekly window, so the next reset moves to that time"
            entry["credits"] = options
            if error:
                entry["credits_error"] = error
        else:
            fable = readings["claude"].fable_resets_at if "claude" in readings else None
            entry["credits"] = [
                {
                    "scope": OFFER_SCOPES[kind],
                    "claim_by": iso(claim_by),
                    "if_claimed_now_lasts_until": (
                        iso(fable) if kind == "claude-fable" and fable
                        else iso(weekly_reset) if weekly_reset else "the weekly reset, unknown without a reading"
                    ),
                }
                for kind, claim_by in offers
            ]
            if not offers:
                entry["credits_note"] = (
                    "Claude offers are not machine-readable. Ask the user for each offer's scope and claim deadline"
                )
        report[side] = entry
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pick the side for new workers from recent weekly quota use.")
    parser.add_argument("--prefer", choices=SIDES, required=True)
    parser.add_argument("--eligible", required=True)
    parser.add_argument("--limited", action="append", default=[], metavar="SIDE=TIME[/RESET]")
    parser.add_argument("--work", type=float, default=0.0, metavar="PERCENT")
    parser.add_argument("--no-spill", action="store_true")
    parser.add_argument("--offer", action="append", default=[], metavar="KIND=CLAIM_BY")
    args = parser.parse_args(argv)
    eligible = [s for s in args.eligible.split(",") if s]
    if not eligible or any(s not in SIDES for s in eligible):
        parser.error("--eligible takes claude, codex, or both, separated by a comma")
    now = datetime.now(timezone.utc)
    limited = {}
    for item in args.limited:
        side, _, times = item.partition("=")
        if side not in SIDES:
            parser.error("--limited takes SIDE=TIME or SIDE=TIME/RESET")
        since, _, until = times.partition("/")
        limit = Limit(parse_time(since), parse_time(until) if until else None)
        if limit.until is None or limit.until > now:
            limited[side] = limit
    offers = []
    for item in args.offer:
        kind, _, claim_by = item.partition("=")
        if kind not in OFFER_SCOPES:
            parser.error(f"--offer kinds are {', '.join(OFFER_SCOPES)}")
        offers.append((kind, parse_time(claim_by)))

    readings, notes = current_readings(sys.stdin.read(), now)
    missing = [side for side in eligible if side not in readings]
    if missing:
        found, quotio_note = read_quotio(missing, now)
        readings.update(found)
        if quotio_note:
            notes.append(quotio_note)
    history, history_note = history_samples(
        Path.home() / "Library/Application Support/quotio/accounts.history/quota.sqlite", now
    )
    if history_note:
        notes.append(history_note)
    path = state_path()
    state = load_state(path)

    sides = {}
    for side in SIDES:
        current = readings.get(side)
        series, account_note = pick_account(history.get(side, {}), current.weekly if current else None, now)
        if account_note:
            notes.append(account_note)
        sources = [("quotio history", series), ("samples from earlier runs", state[side])]
        sides[side] = forecast(current.weekly if current else None, sources, limited.get(side), now)
        if current:
            state[side].append(current.weekly)
    if readings:
        save_state(path, state, now)

    target, why = choose(args.prefer, eligible, sides, args.work, not args.no_spill)
    report = {"route": {"side": target, "why": why}, "sides": {k: asdict(v) for k, v in sides.items()}}
    if target is None or any(sides[s].status in ("limited", "runs-out") for s in eligible):
        report["reset_options"] = reset_options(eligible, sides, readings, offers, now)
    if notes:
        report["notes"] = notes
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

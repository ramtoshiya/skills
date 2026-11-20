import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[3] / "plugins/ramtoshiya/skills/worker-routing/scripts/quota-pace.py"
CLAUDE_METRIC = "895bb5f0186a2900bda8665dac046ba0cca7c482d5a59b80f3f02405b7da3aec"
METRICS = {"claude": CLAUDE_METRIC, "codex": "codex-weekly"}
NOW = datetime.now(timezone.utc)

FAKE_CODEX = """#!/usr/bin/env python3
import json, os, sys
for line in sys.stdin:
    message = json.loads(line)
    with open(os.environ["FAKE_CODEX_LOG"], "a") as log:
        log.write(message["method"] + "\\n")
    if message.get("id") == 1:
        print(json.dumps({"id": 1, "result": {}}), flush=True)
    if message.get("id") == 2:
        print(json.dumps({"id": 2, "result": json.load(open(os.environ["FAKE_CODEX_RESPONSE"]))}), flush=True)
"""

FAKE_QUOTIO = """#!/usr/bin/env python3
import os, sys
if not os.path.exists(os.environ["FAKE_QUOTIO_RESPONSE"]):
    sys.exit(1)
print(open(os.environ["FAKE_QUOTIO_RESPONSE"]).read())
"""


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def ago(hours):
    return NOW - timedelta(hours=hours)


def later(hours):
    return NOW + timedelta(hours=hours)


def bb_usage(**sides):
    providers = []
    for side, (used, resets) in sides.items():
        windows = [{"label": "Weekly limit", "usedPercent": used, "resetsAt": iso(resets)}]
        if side == "claude":
            windows.append({"label": "Weekly · Fable", "usedPercent": 1, "resetsAt": iso(resets + timedelta(hours=1))})
        providers.append({
            "providerId": "claude-code" if side == "claude" else "codex",
            "usage": {"status": "ok", "accountEmail": "person@example.com", "windows": windows},
        })
    return json.dumps({"machines": [{"id": "host", "providers": providers}]})


class QuotaPaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.home = self.tmp / "home"
        self.store = self.home / "Library/Application Support/quotio/accounts.history/quota.sqlite"
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        codex = bin_dir / "codex"
        codex.write_text(FAKE_CODEX)
        codex.chmod(0o755)
        quotio = bin_dir / "quotio-cli"
        quotio.write_text(FAKE_QUOTIO)
        quotio.chmod(0o755)
        self.quotio_response = self.tmp / "quotio.json"
        self.codex_log = self.tmp / "codex.log"
        self.codex_response = self.tmp / "codex.json"
        self.codex_response.write_text(json.dumps({"rateLimitResetCredits": {"availableCount": 0, "credits": []}}))
        self.env = {
            **os.environ, "HOME": str(self.home), "XDG_STATE_HOME": str(self.tmp / "state"),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_CODEX_LOG": str(self.codex_log), "FAKE_CODEX_RESPONSE": str(self.codex_response),
            "FAKE_QUOTIO_RESPONSE": str(self.quotio_response),
        }
        self.series = 0

    def history(self, side, resets_at, used_by_hours_ago, account="account-one", display_name="Weekly"):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.store)
        connection.executescript(
            "PRAGMA user_version = 2;"
            "CREATE TABLE IF NOT EXISTS history_series (id TEXT PRIMARY KEY, host TEXT NOT NULL, account TEXT NOT NULL,"
            " epoch TEXT NOT NULL, metric TEXT NOT NULL, metadata TEXT NOT NULL, UNIQUE(host, account, epoch, metric));"
            "CREATE TABLE IF NOT EXISTS history_observations (sequence INTEGER PRIMARY KEY, series TEXT NOT NULL,"
            " at INTEGER NOT NULL, payload TEXT NOT NULL, UNIQUE(series, at));"
        )
        self.series += 1
        series = f"series-{self.series}"
        connection.execute(
            "INSERT INTO history_series VALUES (?, 'host', ?, ?, ?, ?)",
            (series, account, f"epoch-{self.series}", METRICS[side], json.dumps({"display_name": display_name})),
        )
        for hours, used in used_by_hours_ago.items():
            at = ago(hours)
            payload = {"fetched_at": iso(at), "resets_at": iso(resets_at), "quota": {"used_percent": used}}
            connection.execute(
                "INSERT INTO history_observations (series, at, payload) VALUES (?, ?, ?)",
                (series, int(at.timestamp() * 1e9), json.dumps(payload)),
            )
        connection.commit()
        connection.close()

    def run_pace(self, usage, *args):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args], input=usage, env=self.env,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assertNear(self, text, expected):
        self.assertLess(abs(datetime.fromisoformat(text) - expected), timedelta(minutes=1))

    def codex_methods(self):
        return self.codex_log.read_text().split() if self.codex_log.exists() else []

    def test_projected_runout_at_75_percent_moves_new_work_to_a_side_with_room(self):
        self.history("codex", later(48), {23.5: 27, 12: 51, 0.1: 75})
        self.history("claude", later(48), {23.5: 20, 0.1: 22})
        report = self.run_pace(bb_usage(codex=(75, later(48)), claude=(22, later(48))),
                               "--prefer", "codex", "--eligible", "claude,codex")
        self.assertEqual(report["sides"]["codex"]["status"], "runs-out")
        self.assertEqual(report["sides"]["claude"]["status"], "fits")
        self.assertEqual(report["route"]["side"], "claude")
        runs_out = datetime.fromisoformat(report["sides"]["codex"]["runs_out_at"])
        self.assertAlmostEqual((runs_out - NOW).total_seconds() / 3600, 12.5, delta=0.5)

    def test_spillover_counts_the_estimated_cost_of_the_work(self):
        self.history("codex", later(48), {23.5: 27, 0.1: 75})
        self.history("claude", later(48), {23.5: 20, 0.1: 22})
        report = self.run_pace(bb_usage(codex=(75, later(48)), claude=(22, later(48))),
                               "--prefer", "codex", "--eligible", "claude,codex", "--work", "80")
        self.assertEqual(report["route"]["side"], "codex")

    def test_small_task_at_94_percent_shortly_before_reset_stays_on_its_side(self):
        self.history("codex", later(3), {23.5: 88, 0.1: 94})
        report = self.run_pace(bb_usage(codex=(94, later(3)), claude=(10, later(100))),
                               "--prefer", "codex", "--eligible", "claude,codex")
        self.assertEqual(report["sides"]["codex"]["status"], "fits")
        self.assertEqual(report["route"]["side"], "codex")
        self.assertNotIn("reset_options", report)

    def test_cold_start_routes_by_default_without_a_percent_cutoff(self):
        report = self.run_pace(bb_usage(codex=(95, later(50)), claude=(10, later(50))),
                               "--prefer", "codex", "--eligible", "claude,codex")
        self.assertEqual(report["sides"]["codex"]["status"], "unknown")
        self.assertEqual(report["route"]["side"], "codex")
        self.assertIn("Quotio history store not found", report["notes"])

    def test_cold_start_uses_readings_kept_from_earlier_runs(self):
        state = self.tmp / "state/ramtoshiya/quota-samples.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"codex": [[iso(ago(8)), 70, iso(later(50))]], "claude": []}))
        report = self.run_pace(bb_usage(codex=(86, later(50)), claude=(10, later(50))),
                               "--prefer", "codex", "--eligible", "claude,codex")
        codex = report["sides"]["codex"]
        self.assertEqual(codex["pace_source"], "samples from earlier runs")
        self.assertEqual(codex["pace_per_hour"], 2.0)
        self.assertEqual(codex["status"], "runs-out")
        saved = json.loads(state.read_text())
        self.assertEqual([used for _, used, _ in saved["codex"]], [70, 86])

    def test_lookup_error_text_routes_by_default(self):
        report = self.run_pace("Error: RPC unavailable", "--prefer", "codex", "--eligible", "claude,codex")
        self.assertEqual(report["route"]["side"], "codex")
        self.assertEqual(report["sides"]["codex"]["status"], "no-reading")

    def test_pace_starts_at_a_scheduled_reset(self):
        self.history("claude", ago(10), {20: 80, 11: 90})
        self.history("claude", later(158), {9: 0, 0.1: 9})
        report = self.run_pace(bb_usage(claude=(9, later(158))), "--prefer", "claude", "--eligible", "claude")
        claude = report["sides"]["claude"]
        self.assertAlmostEqual(claude["pace_hours"], 9, delta=0.2)
        self.assertAlmostEqual(claude["pace_per_hour"], 1.0, delta=0.05)

    def test_pace_starts_at_a_counter_drop_within_the_same_schedule(self):
        reset = later(100)
        self.history("claude", reset, {20: 60, 10: 70, 8: 0, 0.1: 4})
        report = self.run_pace(bb_usage(claude=(4, reset)), "--prefer", "claude", "--eligible", "claude")
        claude = report["sides"]["claude"]
        self.assertAlmostEqual(claude["pace_hours"], 8, delta=0.2)
        self.assertAlmostEqual(claude["pace_per_hour"], 0.5, delta=0.02)

    def test_claude_reset_jitter_keeps_one_window(self):
        reset = later(100)
        for h in range(20):
            self.history("claude", reset + timedelta(microseconds=(h % 2) * 900000), {20 - h: 10 + h})
        report = self.run_pace(bb_usage(claude=(30, reset)), "--prefer", "claude", "--eligible", "claude")
        self.assertAlmostEqual(report["sides"]["claude"]["pace_hours"], 20, delta=0.2)

    def test_same_account_series_with_one_reset_are_joined(self):
        reset = later(60)
        self.history("codex", reset, {12: 10, 6.5: 20})
        self.history("codex", reset + timedelta(seconds=1), {6: 21})
        self.history("codex", reset, {0.1: 30})
        report = self.run_pace(bb_usage(codex=(30, reset)), "--prefer", "codex", "--eligible", "codex")
        self.assertAlmostEqual(report["sides"]["codex"]["pace_hours"], 12, delta=0.2)

    def test_two_active_accounts_use_the_one_that_matches_the_reading(self):
        reset = later(60)
        self.history("codex", reset, {12: 10, 0.1: 22}, account="raw-id-a")
        self.history("codex", later(20), {12: 40, 0.1: 80}, account="raw-id-b")
        report = self.run_pace(bb_usage(codex=(22, reset)), "--prefer", "codex", "--eligible", "codex")
        self.assertEqual(report["sides"]["codex"]["pace_per_hour"], 1.0)
        output = json.dumps(report)
        for private in ("raw-id-a", "raw-id-b", "person@example.com"):
            self.assertNotIn(private, output)

    def test_ambiguous_accounts_give_no_pace(self):
        reset = later(60)
        self.history("codex", reset, {12: 10, 0.1: 22}, account="raw-id-a")
        self.history("codex", reset, {12: 10, 0.1: 22}, account="raw-id-b")
        report = self.run_pace(bb_usage(codex=(22, reset)), "--prefer", "codex", "--eligible", "codex")
        self.assertEqual(report["sides"]["codex"]["status"], "unknown")
        self.assertIn("Quotio history has several accounts in use for this side", report["notes"])

    def test_unsupported_history_schema_is_reported_and_skipped(self):
        self.history("codex", later(60), {12: 10, 0.1: 22})
        connection = sqlite3.connect(self.store)
        connection.execute("PRAGMA user_version = 3")
        connection.close()
        report = self.run_pace(bb_usage(codex=(22, later(60))), "--prefer", "codex", "--eligible", "codex")
        self.assertEqual(report["sides"]["codex"]["status"], "unknown")
        self.assertIn("Quotio history schema version 3 is not supported", report["notes"])

    def test_one_limited_side_falls_back_to_the_other_even_with_unknown_pace(self):
        report = self.run_pace(bb_usage(codex=(100, later(30)), claude=(50, later(90))),
                               "--prefer", "codex", "--eligible", "claude,codex")
        self.assertEqual(report["sides"]["codex"]["status"], "limited")
        self.assertEqual(report["sides"]["claude"]["status"], "unknown")
        self.assertEqual(report["route"]["side"], "claude")
        self.assertNear(report["reset_options"]["codex"]["scheduled_reset"], later(30))

    def test_both_limited_reports_options_and_never_redeems(self):
        self.codex_response.write_text(json.dumps({"rateLimitResetCredits": {"availableCount": 3, "credits": [
            {"id": "credit-a", "resetType": "codexRateLimits", "status": "available",
             "grantedAt": 1, "expiresAt": int(later(240).timestamp())},
            {"id": "credit-b", "resetType": "codexRateLimits", "status": "redeemed", "grantedAt": 1, "expiresAt": None},
            {"id": "credit-c", "resetType": "codexRateLimits", "status": "available", "grantedAt": 1, "expiresAt": None},
        ]}}))
        claim_by = iso(later(72))
        report = self.run_pace(
            bb_usage(codex=(100, later(30)), claude=(100, later(90))),
            "--prefer", "codex", "--eligible", "claude,codex",
            "--offer", f"claude-weekly={claim_by}", "--offer", f"claude-fable={claim_by}",
        )
        self.assertIsNone(report["route"]["side"])
        self.assertEqual(self.codex_methods(), ["initialize", "initialized", "account/rateLimits/read"])
        codex = report["reset_options"]["codex"]
        self.assertEqual([c["claim_by"] for c in codex["credits"]],
                         [iso(later(240).replace(microsecond=0)), "no deadline", "unknown"])
        self.assertNear(codex["credits"][0]["if_claimed_now_lasts_until"], later(168))
        claude = report["reset_options"]["claude"]
        weekly, fable = claude["credits"]
        self.assertNear(weekly["if_claimed_now_lasts_until"], later(90))
        self.assertIn("Does not restore the weekly limit", fable["scope"])
        self.assertNear(fable["if_claimed_now_lasts_until"], later(91))
        self.assertNotIn("credit-a", json.dumps(report))

    def test_claude_offers_are_unknown_rather_than_absent(self):
        report = self.run_pace(bb_usage(claude=(100, later(90))), "--prefer", "claude", "--eligible", "claude")
        self.assertIn("not machine-readable", report["reset_options"]["claude"]["credits_note"])

    def test_both_projected_to_run_out_stay_on_the_default_side(self):
        self.history("codex", later(48), {23.5: 27, 0.1: 75})
        self.history("claude", later(48), {23.5: 20, 0.1: 60})
        report = self.run_pace(bb_usage(codex=(75, later(48)), claude=(60, later(48))),
                               "--prefer", "codex", "--eligible", "claude,codex")
        self.assertEqual(report["sides"]["claude"]["status"], "runs-out")
        self.assertEqual(report["route"]["side"], "codex")

    def test_projection_alone_does_not_switch_to_a_side_with_unknown_pace(self):
        self.history("codex", later(48), {23.5: 27, 0.1: 75})
        report = self.run_pace(bb_usage(codex=(75, later(48)), claude=(5, later(48))),
                               "--prefer", "codex", "--eligible", "claude,codex")
        self.assertEqual(report["route"]["side"], "codex")

    def test_ineligible_alternative_leaves_the_role_blocked(self):
        report = self.run_pace(bb_usage(codex=(5, later(48)), claude=(100, later(48))),
                               "--prefer", "codex", "--eligible", "claude")
        self.assertIsNone(report["route"]["side"])
        self.assertEqual(list(report["reset_options"]), ["note", "claude"])
        self.assertEqual(self.codex_methods(), [])

    def test_limit_error_keeps_a_side_off_until_its_quota_renews(self):
        reset = later(40)
        self.history("codex", reset, {10: 90, 1: 97})
        since = iso(ago(0.5))
        args = ("--prefer", "codex", "--eligible", "claude,codex", "--limited", f"codex={since}")
        report = self.run_pace(bb_usage(codex=(97, reset), claude=(5, later(48))), *args)
        self.assertEqual(report["sides"]["codex"]["status"], "limited")
        self.assertEqual(report["route"]["side"], "claude")
        reanchored = self.run_pace(bb_usage(codex=(0, later(168)), claude=(5, later(48))), *args)
        self.assertEqual(reanchored["route"]["side"], "codex")

    def test_limit_errors_without_readings_keep_both_sides_off(self):
        since = iso(ago(0.5))
        report = self.run_pace("", "--prefer", "codex", "--eligible", "claude,codex",
                               "--limited", f"codex={since}", "--limited", f"claude={since}")
        self.assertIsNone(report["route"]["side"])
        self.assertEqual(report["sides"]["codex"]["status"], "limited")

    def test_limit_error_without_an_alternate_reading_leaves_the_role_blocked(self):
        report = self.run_pace(bb_usage(codex=(97, later(40))), "--prefer", "codex", "--eligible", "claude,codex",
                               "--limited", f"codex={iso(ago(0.5))}")
        self.assertEqual(report["sides"]["claude"]["status"], "no-reading")
        self.assertIsNone(report["route"]["side"])
        self.assertNear(report["reset_options"]["codex"]["scheduled_reset"], later(40))

    def test_full_default_without_an_alternate_reading_leaves_the_role_blocked(self):
        report = self.run_pace(bb_usage(codex=(100, later(30))), "--prefer", "codex", "--eligible", "claude,codex")
        self.assertIsNone(report["route"]["side"])

    def test_a_saved_sample_is_not_a_current_reading_after_a_limit(self):
        state = self.tmp / "state/ramtoshiya/quota-samples.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"claude": [[iso(ago(0.1)), 32, iso(later(90))]], "codex": []}))
        report = self.run_pace(bb_usage(codex=(100, later(30))), "--prefer", "codex", "--eligible", "claude,codex")
        self.assertIsNone(report["route"]["side"])

    def test_quotio_cli_supplies_a_missing_alternate_reading(self):
        self.quotio_response.write_text(json.dumps({
            "accounts": [{"id": "raw-id-q", "provider_id": "claude", "email": "person@example.com"}],
            "usage": [{"account_id": "raw-id-q", "metrics": [
                {"display_name": "Weekly", "quota": {"used_percent": 40}, "resets_at": iso(later(90))},
            ]}],
        }))
        report = self.run_pace(bb_usage(codex=(97, later(40))), "--prefer", "codex", "--eligible", "claude,codex",
                               "--limited", f"codex={iso(ago(0.5))}")
        self.assertEqual(report["sides"]["claude"]["used"], 40)
        self.assertEqual(report["route"]["side"], "claude")
        output = json.dumps(report)
        for private in ("raw-id-q", "person@example.com"):
            self.assertNotIn(private, output)

    def test_empty_input_reads_fractional_utc_quotio_timestamps(self):
        state = self.tmp / "state/ramtoshiya/quota-samples.json"
        state.parent.mkdir(parents=True)
        for timestamp, expected in (
            ("2026-11-26T16:59:59.97185+00:00", "2026-11-26T16:59:59Z"),
            ("2026-11-26T17:00:00.474Z", "2026-11-26T17:00:00Z"),
            ("2026-11-26T18:00:00.1+01:00", "2026-11-26T17:00:00Z"),
            ("2026-11-26T17:00:00.123456789Z", "2026-11-26T17:00:00Z"),
            ("2026-11-26T17:00:00Z", "2026-11-26T17:00:00Z"),
        ):
            with self.subTest(timestamp=timestamp):
                self.quotio_response.write_text(json.dumps({
                    "accounts": [{"id": "fixture", "provider_id": "claude"}],
                    "usage": [{"account_id": "fixture", "metrics": [
                        {"display_name": "Weekly", "quota": {"used_percent": 40}, "resets_at": timestamp},
                    ]}],
                }))
                state.write_text(json.dumps({"claude": [[iso(ago(8).replace(microsecond=0)), 30,
                                                         "2026-11-26T17:00:00Z"]], "codex": []}))
                report = self.run_pace("", "--prefer", "claude", "--eligible", "claude,codex")
                self.assertEqual(report["sides"]["claude"]["used"], 40)
                self.assertEqual(report["sides"]["claude"]["resets_at"], expected)
                self.assertEqual(report["route"]["side"], "claude")

    def test_a_shorter_limit_holds_until_the_reset_time_the_error_named(self):
        usage = bb_usage(claude=(30, later(90)), codex=(10, later(40)))
        args = ("--prefer", "claude", "--eligible", "claude,codex")
        held = self.run_pace(usage, *args, "--limited", f"claude={iso(ago(1))}/{iso(later(2))}",
                             "--offer", f"claude-weekly={iso(later(72))}")
        self.assertEqual(held["sides"]["claude"]["status"], "limited")
        self.assertEqual(held["route"]["side"], "codex")
        claude = held["reset_options"]["claude"]
        self.assertNear(claude["scheduled_reset"], later(2))
        self.assertNear(claude["credits"][0]["if_claimed_now_lasts_until"], later(90))
        reopened = self.run_pace(usage, *args, "--limited", f"claude={iso(ago(5))}/{iso(ago(0.1))}")
        self.assertEqual(reopened["route"]["side"], "claude")

    def test_claude_reset_on_the_same_schedule_counts_as_renewal(self):
        reset = later(40)
        self.history("claude", reset, {10: 90, 1: 99})
        args = ("--prefer", "claude", "--eligible", "claude", "--limited", f"claude={iso(ago(0.5))}")
        report = self.run_pace(bb_usage(claude=(0, reset)), *args)
        self.assertEqual(report["route"]["side"], "claude")


if __name__ == "__main__":
    unittest.main()

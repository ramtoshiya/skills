# Quota lookup {:#quota-lookup}

Read the weekly quota before each batch of new workers, and pipe it into `quota-pace.py`, as
[Route and quota](../SKILL.md) describes. Do not print the lookup output. It names the account.

## Current reading {:#current-reading}

In BB, prefer the enabled Provider usage plugin. Its read-only RPC runs collection on the selected
machine rather than inside the agent's command sandbox. Read `bb status --json` and use
`thread.environment.hostId` as `<machine-id>` below:

```sh
usage=$(bb plugin rpc call bb--provider-usage getUsage --input-file /dev/stdin --json <<'JSON'
{"force":false,"machineIds":["<machine-id>"],"providerIds":["claude-code"],"maxAgeMs":300000}
JSON
)
printf '%s' "$usage" | uv run --no-project --managed-python --python '>=3.11' python \
  <skill-dir>/scripts/quota-pace.py --eligible <sides>
```

The script reads the `Weekly limit` window of `claude-code` when `usage.status` is `ok`. BB reports
no GPT usage while its `codex` provider is disabled, so the script reads the `codex` side itself:
it asks the installed `codex app-server` for `account/rateLimits/read` and takes the 10080-minute
window's `usedPercent` and `resetsAt`. The `claudex` proxy uses the same Codex account. If the
piped lookup does include a `codex` reading, the script uses that one. Claude's percentage is a rounded reading. Use a provider usage-limit error to confirm
that Claude stopped accepting work. Do not combine accounts from other machines. The RPC can
be callable even when `bb plugin rpc list` does not advertise it. Do not enable or install a
plugin just for this lookup.

When `codex app-server` reports only other windows, such as a 30-day one, and no other source has a
weekly reading, the plan gives the `codex` side no worker pool. The side's status is `no-pool`, and its
note names the plan and its windows. This is not a lookup failure. Flexible work stays on Claude, and a
role that only `codex` can run gets a `null` `route.side`. The side returns once the account has a
weekly window.

For a Claude reading that the piped output lacks, or when `codex app-server` returns no weekly window,
the script runs `quotio-cli usage --provider <side> --no-saved-accounts --format json` itself. It joins
`usage[].account_id` to `accounts[].id`, reads the `Weekly` metric, and never prints the output.
Outside BB, or when the RPC fails, run the script with no input (`</dev/null`). It reads the `codex`
side from `codex app-server` and the `claude` side this way. It looks for `quotio-cli` on PATH, at `~/.local/bin/quotio-cli`, and at
`Contents/Helpers/quotio-cli` in `/Applications/Quotio.app` and `/Applications/Quotio Beta.app`.
When it finds none, or the command returns no figure for a side, that side has no reading and a
note says which. A side without a reading is never the fallback for a limited side.

A note that `quotio-cli` was not found does not prove that Quotio is absent. Name the Quotio app
and this repository's `docs/setup.md` only when the launcher or app is actually missing. When the
note names an exit status, run the same command alone and keep its output private. If it reported
a cache, authentication, network, or provider error, report that category. For an explicit
sandbox denial, use BB's host-side lookup first. If it cannot supply the figure, request the
narrowly scoped access needed for one retry through the host's normal permission mechanism. Do not disable the sandbox globally or retry a denied permission.
If access is unavailable, pipe in any valid figures and let the script report the rest.

## Pace {:#pace}

`quota-pace.py` projects each side's use at its scheduled reset from the recent pace: the rise in
weekly use over the last 24 hours of the current window. It needs at least 6 hours of samples.
A window starts at a scheduled reset or at a drop in the count, so the pace never spans either.
With less history the side's status is `unknown`, and only its current reading counts.

The script reads samples from two places, and writes only the second:

- Quotio's history store, `~/Library/Application Support/quotio/accounts.history/quota.sqlite`,
  opened read-only. The script reads schema version 2 and reports any other version. It uses the
  Weekly series and the one account in use. When several accounts are in use, it uses the one
  whose latest sample matches the current reading, and otherwise reports the history as ambiguous.
- Its own file, `$XDG_STATE_HOME/ramtoshiya/quota-samples.json`, or
  `~/.local/state/ramtoshiya/quota-samples.json`. It keeps each current reading for 8 days, without
  account names, so later runs have a pace when Quotio's history is missing.

## Pinned demand {:#pinned-demand}

For flexible work, `--eligible claude,codex` without `--prefer`, the report adds `claude_demand`.
It splits Claude's demand into work pinned to Claude and flexible work, because pinned demand alone
can use up Claude's week.

- The script reads Claude Code transcripts, `~/.claude/projects/**/*.jsonl` or
  `$CLAUDE_CONFIG_DIR/projects/**/*.jsonl`, from the last 7 days. Each assistant message carries
  `message.model` and `message.usage`. Messages are counted once by `message.id` and `requestId`.
  Models that do not start with `claude-opus`, `claude-fable`, `claude-sonnet`, or `claude-haiku`,
  such as claudex's GPT models, are not Claude quota and are skipped.
- Tokens are weighted roughly like API price: input 1, cache write 1.25, cache read 0.1, output 5,
  times a model factor of 1 for Opus and Fable, 0.6 for Sonnet, and 0.2 for Haiku. Opus and Fable
  messages are pinned. Sonnet and Haiku messages are flexible. Transcripts do not record the row,
  so Opus work from the oracle row that ran on Claude also counts as pinned. That overstates
  pinned demand and sends more flexible work to `codex`, which protects judgment work.
- `units_per_point` converts weighted units to Claude weekly percent-points. The script fits it
  over the last 7 days of Quotio's Claude Weekly history: all Claude units in the history's span
  divided by the points used in it, counting each new window or counter drop from zero. `fit`
  describes the data. The fit needs at least 24 hours and 10 points.
- `pinned_pace_24h` and `pinned_pace_7d` are pinned units per hour over each span, in points.
  `pinned_pace_per_hour` is the larger one, so a window that just reset is not read as empty.
  Without a fit, `pinned_pace_per_hour` is the pinned share of the last 24 hours of Claude units
  times Claude's own pace, and `note` says so. Without that pace either, it is unknown.
- `spare` is Claude's remaining points minus `pinned_pace_per_hour` times the hours to its reset:
  room that would otherwise expire unused at the reset.

The Codex side's `credits_counted` is the number of available full Codex reset credits that can be
claimed before Codex would run out. Each one counts as 100 points of room when the script decides
whether Codex has room. The script only counts them. A person decides whether to redeem one.

## Reset options {:#reset-options}

When an eligible side is limited or projected to run out, the report adds `reset_options` for it:
the scheduled reset, the hours of outage before it, and the use expected in those hours at the
recent pace. The credits come from these sources:

- Codex: the script asks the installed `codex app-server` for `account/rateLimits/read` and lists
  each available credit's scope and claim deadline. Claiming a Codex credit restarts the weekly
  window, so its quota lasts 7 days from the claim and the next reset moves. If the report has
  `credits_error`, read `usage[].codex_reset_credits.credits[].expires_at` from the Quotio CLI
  output instead.
- Claude: no supported interface lists Claude's offers. Do not read them from the browser or from
  stored credentials. When the user names an offer, pass `--offer claude-weekly=<claim deadline>`
  or `--offer claude-fable=<claim deadline>`. A Claude weekly reset keeps the existing schedule,
  so its quota lasts only until the scheduled reset. A Fable offer restores only the Fable window,
  not the weekly limit. Without an offer the report says Claude's offers are unknown, not absent.

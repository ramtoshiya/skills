# Quota lookup {:#quota-lookup}

Read the weekly quota before each batch of new workers, and pipe it into `quota-pace.py`, as
[Route and quota](../SKILL.md) describes. Do not print the lookup output. It names the account.

## Current reading {:#current-reading}

In BB, prefer the enabled Provider usage plugin. Its read-only RPC runs collection on the selected
machine rather than inside the agent's command sandbox. Read `bb status --json` and use
`thread.environment.hostId` as `<machine-id>` below:

```sh
usage=$(bb plugin rpc call bb--provider-usage getUsage --input-file /dev/stdin --json <<'JSON'
{"force":false,"machineIds":["<machine-id>"],"providerIds":["claude-code","codex"],"maxAgeMs":300000}
JSON
)
printf '%s' "$usage" | uv run --no-project --managed-python --python '>=3.11' python \
  <skill-dir>/scripts/quota-pace.py --prefer <side> --eligible <sides>
```

The script reads the `Weekly limit` window of `claude-code` and `codex` when `usage.status` is
`ok`. Urgent work reads the `Weekly · Fable` window itself to tell whether the Fable window is
exhausted. Do not combine accounts from other machines. The RPC can be callable even when
`bb plugin rpc list` does not advertise it. Do not enable or install a plugin just for this lookup.

For each eligible side that the piped output lacks, the script runs
`quotio-cli usage --provider <side> --no-saved-accounts --format json` itself. It joins
`usage[].account_id` to `accounts[].id`, reads the `Weekly` metric, and never prints the output.
Outside BB, or when the RPC fails, run the script with no input (`</dev/null`) and it reads every
eligible side this way. It looks for `quotio-cli` on PATH, at `~/.local/bin/quotio-cli`, and at
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

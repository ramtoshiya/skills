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
`bb plugin rpc list` does not advertise it. If it is unavailable or a side has no weekly figure,
use Quotio for that side. Do not enable or install a plugin just for this lookup.

Outside BB, or as that fallback, capture
`quotio-cli usage --provider claude --provider codex --no-saved-accounts --format json` and pipe it
into the script the same way. Keep stderr and the exit status separate. Valid figures still count
when another provider makes the command exit nonzero. The script joins `usage[].account_id` to
`accounts[].id` and reads the `Weekly` metric.

A failed lookup does not mean the CLI is missing. Check `command -v quotio-cli`, not `quotio`.
On macOS, also check `~/.local/bin/quotio-cli` and the `Contents/Helpers/quotio-cli` executable in
`/Applications/Quotio.app` and `/Applications/Quotio Beta.app`. Use an existing compatible helper by
absolute path when PATH is the only problem. Name the Quotio app and this repository's
`docs/setup.md` only when the launcher or app is actually missing.

If the command ran but reported a cache, authentication, network, or provider error, report that
category instead. For an explicit sandbox denial, use BB's host-side lookup first. If it cannot
supply the figure, request the narrowly scoped access needed for one retry through the host's
normal permission mechanism. Do not disable the sandbox globally or retry a denied permission.
If access is unavailable, keep any valid figures and use the route-file fallback for the rest.

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

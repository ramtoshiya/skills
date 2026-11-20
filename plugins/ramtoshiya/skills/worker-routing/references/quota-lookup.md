# Quota lookup {:#quota-lookup}

Read the weekly quota once per session, before routing the first worker, as
[Route and quota](../SKILL.md) describes.

In BB, prefer the enabled Provider usage plugin. Its read-only RPC runs collection on the selected
machine rather than inside the agent's command sandbox. Read `bb status --json` and use
`thread.environment.hostId` as `<machine-id>` below:

```sh
bb plugin rpc call bb--provider-usage getUsage --input-file /dev/stdin --json <<'JSON'
{"force":false,"machineIds":["<machine-id>"],"providerIds":["claude-code","codex"],"maxAgeMs":300000}
JSON
```

In `machines[].providers[]`, use `usage.windows[]` only when `usage.status` is `ok`. The overall
weekly window is labeled `Weekly limit`, and its `usedPercent` is the used percentage. Ignore
model-specific windows such as `Weekly · Fable` for routing. Urgent work reads that window to tell
whether the Fable window is exhausted. Map `claude-code` to the Claude side and `codex`
to both GPT routes. Do not combine accounts from other machines. The RPC can be callable even when
`bb plugin rpc list` does not advertise it. If it is unavailable or a side has no weekly figure,
use Quotio for that side. Do not enable or install a plugin just for this lookup.

Outside BB, or as that fallback, run
`quotio-cli usage --provider claude --provider codex --no-saved-accounts --format json`. Keep stdout
and stderr separate and preserve the exit status. Do not truncate the JSON or pipe it through a
command that hides the lookup's failure. In schema version 2, join `usage[].account_id` to
`accounts[].id` for the provider, then read `metrics[]` with `display_name` equal to `Weekly` and
`quota.used_percent` present. Use valid figures even when another provider makes the command exit
nonzero. Ignore accounts with no weekly metric. Do not print account identities or the full report.

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

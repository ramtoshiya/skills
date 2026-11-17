---
name: worker-routing
description: >-
  Shared model, effort, provider, quota, retry, and escalation policy. Read when a
  skill or session mode explicitly names this policy. Loading it does not activate
  lead mode or its shipping and review workflow.
user-invocable: false
---

# Worker routing

The session that delegates owns the work and chooses each worker's row. Read the
route once per session and carry its state through compaction. This policy does
not change the calling workflow's roles, candidate count, or model-family
requirements.

## Choose the model {:#models}

Pass the row's model and effort every time you start a worker: `model` and `effort` on an Agent
call, and the matching options of a thread tool as [Worker route](#worker-route) describes. Without
them, an Agent subagent on another model runs at that model's saved effort, which may be `low`, and
a BB worker runs on your own model and effort.

| `model` `effort` | Work |
| --- | --- |
| `haiku` `low` | Nothing to decide: an edit the brief spells out, a rename or one pattern across files, a search with a fixed source and scope, a direct lookup |
| `haiku` `high` | Reading a large file or log closely and reporting what it says. Split input over about 100K tokens across several workers |
| `sonnet` `high` | The default for implementation: the brief states the behavior and acceptance criteria, the change stays inside one component, and no design decision is open. Also sorting and summarizing results against fixed criteria |
| `opus` `high` | Top-tier work: design questions and memos, reviews, changes across components or boundaries such as a file format or persisted state, concurrency, recovery, security, and debugging an unknown cause |

Use `fable` in place of `opus` only when the user asks for it. Under claudex these aliases select
its GPT tiers, so the same table applies.

When a piece of work fits no row, split it instead of picking a combination in between. Work that
mixes design decisions with many mechanical edits becomes an `opus` `high` design unit and a
`sonnet` `high` or `haiku` `low` implementation unit.

A worker that stopped or failed reruns on the same row by default. Read its thread first, with
`t3_thread_read` for a `delegate_task` worker or `bb thread log <id>` for a BB worker, not only the
reply it returned. Fix what stopped it, or say in the new brief how to get past it.

Step up one row only when the worker's own work shows that the task outgrew its row: it produced a
design that misses the requirement, or its checks kept failing while it kept changing the code. Say
which one you saw. A worker that stopped before either happened has shown nothing about its row,
whatever its reason. `haiku` moves to `sonnet` `high`, and `sonnet` `high` moves to `opus`
`high`. If `opus` `high` outgrows its row, split the work or change the approach. Never step up to
`fable`.

After two materially identical failures without progress, change the approach or name the missing
capability.

## Worker route {:#worker-route}

Before the first spawn, find out which tools your session has. A thread tool starts a worker as a
separate agent thread on any provider the host offers.

| Host | How to tell | Thread tool |
| --- | --- | --- |
| T3 | `delegate_task` is in your tool list | `delegate_task`, as [T3 workers](#t3-workers) describes |
| BB | `BB_THREAD_ID` is set in your shell | `bb thread spawn`, as [BB workers](#bb-workers) describes |
| Any other host | Neither of the above | None |

Start the workers the model table puts on Claude with the Agent tool. When your session has no Agent
tool, start them with the thread tool instead. T3 removes the Agent tool when a provider instance
bans Claude Code's own subagent tools at launch. BB removes it while its Claude Code provider
setting `subagentsDisabled` is on. When neither tool is available, the worker cannot start on
Claude, so follow the calling workflow's fallback.

Without a thread tool, every worker runs on Claude, so skip the route file and the quota below.
Otherwise, read `~/.config/ramtoshiya/lead-route.json` once at the start. Its `workers` value is
`claude`, `codex` or `claudex`. A missing file or any other value means `claude`. Then read the
weekly quota once as [Quota lookup](#quota-lookup) describes. The `codex` and `claudex` routes share
the Codex quota.

Switch to the other side when the current route's weekly use is 90% or more, or when a worker fails
with a usage-limit error. `claude` moves to `codex`, and `codex` or `claudex` moves to `claude`. A
side that returned a usage-limit error stays off for the rest of the session, whatever the file or
the quota says. If both sides are at 90% or more, keep the file's route. Say in your report when you
switch. If quota lookup still returns no weekly figure, report the specific failure once and route
by the file and the usage-limit rule alone. When you compact, write the route you are on, the weekly
figures, their source, and any side that is off into the handoff note.

On the `codex` or `claudex` route, start these workers with the thread tool on the route's provider.

| Row | GPT model and effort |
| --- | --- |
| `haiku` `low` | The newest Luna model, `low` |
| `haiku` `high` | The newest Luna model, `high` |
| `sonnet` `high` | The newest Terra model, `high` |

On both GPT routes, Luna workers use only `low` or `high` effort as the table specifies, and
Terra workers use only `high`.

The `opus` rows, child leads, and your own judgement stay on Claude. Step-ups follow the rows,
except that a Terra worker that outgrew its row reruns on the same provider with the newest Sol
model at `high`, so the step-up stays on the route's quota.

When the calling workflow needs a seat outside the Claude family, such as a cross-model judge, start
it with the thread tool on the GPT route's provider, or on Codex when the route is `claude`. Give it
the model the table above names for its row, or the newest Sol model at the row's effort for an
`opus` row. Without a thread tool, or while a usage-limit error keeps the `codex` and `claudex` side
off, the seat cannot run, so follow the calling workflow's fallback.

### Quota lookup {:#quota-lookup}

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
model-specific windows such as `Weekly · Fable`. Map `claude-code` to the Claude side and `codex`
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

### T3 workers {:#t3-workers}

On the `codex` or `claudex` route, use the provider instance named for the route in
`orchestrator_capabilities`, and set the reasoning effort option it lists. On the `codex` route,
use a Codex instance named for workers instead when it lists one. Such an instance can leave out
what only the user's own sessions need, such as a memory plugin that injects summaries of earlier
sessions.

Whenever you start a Claude worker or child lead with `delegate_task`, for a missing Agent tool or
any other reason, use a Claude instance named for workers when `orchestrator_capabilities` lists
one, and the Claude instance you run on otherwise. Like the Codex instance for workers, it can leave
out what only the user's own sessions need, such as a memory plugin. Use the model
`orchestrator_capabilities` lists for the row, and set its effort option to the row's effort on
every call, because a `delegate_task` child inherits options only when its instance and model both
match the parent's.

Use `mode: "wait"` when your next step needs the result, and `mode: "async"` otherwise. If a wait
times out, follow the `next` it returns. Do not poll. Leave `runtimeMode` unset.

### BB workers {:#bb-workers}

Start each worker as a child of your thread:

```sh
bb thread spawn --project "$BB_PROJECT_ID" --parent-self --title "<role>" \
  --provider <provider> --model <model-id> --reasoning-level <effort> \
  --environment "$BB_ENVIRONMENT_ID" --prompt-file - <<'BRIEF'
<brief>
BRIEF
```

- `--provider` is `claude-code` for a worker on Claude, and `codex` or `claudex` for a GPT worker
  on that route.
- For `--model`, run `bb provider models <provider>` once per session and take the highest-numbered
  ID of the row's family. The families are Haiku, Sonnet, Opus, and Fable on `claude-code`, and
  Luna, Terra, and Sol on `codex` and `claudex`. Skip variant IDs with a suffix such as `[1m]`.
- `--reasoning-level` is the row's effort. Confirm that `bb provider models <provider> --json` lists
  it in the model's `supportedReasoningEfforts`. BB drops a level the model does not list, and the
  worker then runs at its own default.
- `--environment "$BB_ENVIRONMENT_ID"` shares your checkout, including uncommitted changes. Use it
  for read-only roles and for workers whose files no other writer touches at the same time. When
  workers edit overlapping files in parallel, or the calling workflow asks for isolation, commit
  what they need and pass `--new-environment worktree --base-branch "$(git branch --show-current)"`
  instead. Merge such a worker's commits into your branch before you archive it. Always pass one of
  these flags. Without one, the worker gets a fresh worktree of the project's default branch, which
  has neither your branch nor your uncommitted changes.

BB has no read-only permission mode, and a worker inherits your permission mode. Keep a read-only
role read-only through its brief. Say that it must not edit files, commit, or change anything
outside its reply. After it finishes, run `git status` to confirm that the checkout did not change.

Wait for workers through parent notifications. When a worker's turn completes, fails, or stops on a
question or an approval, BB sends a `[bb system]` message to your thread. The message steers into
your running turn, or starts a new turn when you are idle. Do other work meanwhile. When the next
step needs a result and no other work is left, end your turn with one line that names the workers
you are waiting for. Do not loop on `bb thread show` or `bb thread wait`.

When your own thread is a BB child, ending a turn reports that turn to your parent as your result.
`bb status` then shows a `Parent` and `Parent notifications: auto`. Keep the turn open instead. Run
`bb thread wait <worker-id> --timeout <limit>` in the foreground, with a limit below your shell
tool's timeout. Run it again only when it exits with code 2, which means it timed out.

The `[bb system]` message quotes the worker's final reply up to 4,000 characters, and ends a longer
reply with `[... output truncated ...]`. Read the whole reply with `bb thread output <id>`.

Archive each worker with `bb thread archive <id>` once you have read its reply, merged its commits,
and need nothing more from it. Archiving keeps the worker's history, removes it from the thread
list, and archives the workers it started. A worker in your environment leaves that environment in
place. A worktree worker's checkout is removed five minutes after archiving, and its branch stays.

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

Pass both `model` and `effort` on every Agent call. Without them, a subagent on another model runs
at that model's saved effort, which may be `low`.

| `model` `effort` | Work |
| --- | --- |
| `haiku` `low` | Nothing to decide: an edit the brief spells out, a rename or one pattern across files, a search with a fixed source and scope, a direct lookup |
| `haiku` `max` | Reading a large file or log closely and reporting what it says. Split input over about 100K tokens across several workers |
| `sonnet` `max` | The default for implementation: the brief states the behavior and acceptance criteria, the change stays inside one component, and no design decision is open. Also sorting and summarizing results against fixed criteria |
| `opus` `high` | Top-tier work expected to finish within about 30 minutes: one design question, a short judgement, the review of a small or medium diff |
| `opus` `xhigh` | Longer top-tier work: a design memo, a change across components or across a boundary such as a file format or persisted state, concurrency, recovery, security, debugging an unknown cause, a consequential review |

Use `fable` in place of `opus` only when the user asks for it. Under claudex these aliases select
its GPT tiers, so the same table applies.

When a piece of work fits no row, split it instead of picking a combination in between. Work that
mixes design decisions with many mechanical edits becomes an `opus` `xhigh` design unit and a
`sonnet` `max` or `haiku` `low` implementation unit.

A worker that stopped or failed reruns on the same row by default. Read its thread first, with
`t3_thread_read` for a `delegate_task` worker, not only the reply it returned. Fix what stopped it,
or say in the new brief how to get past it.

Step up one row only when the worker's own work shows that the task outgrew its row: it produced a
design that misses the requirement, or its checks kept failing while it kept changing the code. Say
which one you saw. A worker that stopped before either happened has shown nothing about its row,
whatever its reason. `haiku` moves to `sonnet` `max`. `sonnet` `max` and `opus` `high` move to
`opus` `xhigh`. Never step up to `fable`.

After two materially identical failures without progress, change the approach or name the missing
capability.

## Worker route {:#worker-route}

In T3, the `haiku` and `sonnet` rows can run on GPT through `delegate_task` instead of the Agent
tool. Outside T3, use the Agent tool.

At the start, read `~/.config/ramtoshiya/lead-route.json` once. Its `workers` value is `claude`,
`codex` or `claudex`. A missing file or any other value means `claude`. Then read the weekly quota
once with `quotio-cli usage --provider claude --provider codex --no-saved-accounts --format json`.
Take the used percentage of the metric named `Weekly` and ignore accounts that report none. The
command exits with an error when one account fails but still prints the others, so use any `Weekly`
figure it prints. The `codex` and `claudex` routes share the Codex quota.

Switch to the other side when the current route's weekly use is 90% or more, or when a worker fails
with a usage-limit error. `claude` moves to `codex`, and `codex` or `claudex` moves to `claude`. A
side that returned a usage-limit error stays off for the rest of the session, whatever the file or
the quota says. If both sides are at 90% or more, keep the file's route. Say in your report when you
switch. If `quotio-cli` is missing or prints no `Weekly` figure, say so once, name the Quotio app
that ships it and the `docs/setup.md` of this skill's repository that puts it on PATH, and route by
the file and the usage-limit rule alone. When you compact, write the route you are on, the weekly
figures, and any side that is off into the handoff note.

On the `codex` or `claudex` route, start these workers with `delegate_task` on the provider instance
named for the route in `orchestrator_capabilities`, and set the reasoning effort option it lists.
On the `codex` route, use a Codex instance named for workers instead when it lists one. Such an
instance can leave out what only the user's own sessions need, such as a memory plugin that injects
summaries of earlier sessions.

| Row | GPT model and effort |
| --- | --- |
| `haiku` `low` | The newest Luna model, `low` |
| `haiku` `max` | The newest Luna model, `max` |
| `sonnet` `max` | The newest Terra model, `max` |

On both GPT routes, Luna workers use only `low` or `max` effort as the table specifies, and
Terra workers use only `max`.

The `opus` rows, child leads, and your own judgement stay on Claude through the Agent tool.
Step-ups follow the rows, except that a Terra worker that outgrew its row reruns on the same
instance with the newest Sol model at `high`, so the step-up stays on the route's quota.

When your session has no Agent tool because the host banned Claude Code's own subagent tools, start
every worker the table puts on Claude with `delegate_task` instead. Use the model
`orchestrator_capabilities` lists for the row, and its effort option set to the row's effort. Set
the effort on every call, because a `delegate_task` child inherits options only when its instance
and model both match the parent's.

Whenever you start a Claude worker or child lead with `delegate_task`, for this or any other reason,
use a Claude instance named for workers when `orchestrator_capabilities` lists one, and the Claude
instance you run on otherwise. Like the Codex instance for workers, it can leave out what only the
user's own sessions need, such as a memory plugin.

Use `mode: "wait"` when your next step needs the result, and `mode: "async"` otherwise. If a wait
times out, follow the `next` it returns. Do not poll. Leave `runtimeMode` unset.

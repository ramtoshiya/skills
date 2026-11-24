---
name: worker-routing
description: >-
  Shared model, effort, provider, quota, urgency, retry, and escalation policy for
  starting workers. Read before the first worker spawn, and again when a task
  becomes urgent.
user-invocable: false
---

# Worker routing

The session that delegates owns the work and chooses each worker's row. Read this
policy once per session and carry its state through compaction. It does not change
the calling workflow's roles, candidate count, or model-family requirements.

## Newest model {:#newest-model}

Every model you pass when you start a worker is the output of this skill's script.
It sits in `scripts/` next to this file:

```sh
<skill-dir>/scripts/newest-model <family> [<provider>]
```

- Worker families are `sonnet`, `opus`, and `fable` on `claude-code`, and `terra`
  and `sol` on `codex` and `claudex`. The provider defaults to `claude-code`
  for Claude families and `codex` for GPT families.
- Pass the output as it is. Never type a model ID yourself or copy one from memory,
  an earlier brief, or a catalog listing. For Claude it prints the family alias,
  which resolves to the family's newest model.
- Exit 1 with empty output means the provider offers no model of that family, such
  as Terra on `claudex`. Start that worker on `codex`. Exit 2 means the catalog
  could not be read. Report that and do not guess an ID.

## Choose the row {:#models}

Use a search, lint, check, or script when it can answer the question. Do small
tasks yourself when your role permits. Choose a row below when work needs a worker.

Pass the row's model and effort every time you start a worker: `model` and `effort`
on an Agent call, and `--model` and `--reasoning-level` on `bb nest spawn`.
Without them, an Agent subagent on another model runs at that model's saved effort,
which may be `low`, and a BB worker runs on your own model and effort.

| Row | On the `codex` side | Work |
| --- | --- | --- |
| `sonnet` `high` | `terra` `high` | The default for implementation: the brief states the behavior and acceptance criteria, the change stays inside one component, and no design decision is open. Also sorting and summarizing results against fixed criteria, and reads that need interpretation, including explanations, research, calculations, and reconciling mismatches, even when read-only. Split input over about 100K tokens across several workers |
| `opus` `high` | Stays on Claude | Top-tier work: design questions and memos, reviews, changes across components or boundaries such as a file format or persisted state, concurrency, recovery, security, and debugging an unknown cause |

Use `fable` in place of `opus` only when the user asks for it or the work is urgent,
as [Urgency](#urgency) describes. Under claudex these aliases select its GPT tiers,
so the same table applies. When a piece of work fits no row, split it instead of
picking a combination in between. Work that mixes design decisions with many
mechanical edits becomes an `opus` `high` design unit and a `sonnet` `high`
implementation unit.

When a worker stopped, failed, or seems to have outgrown its row, or a workflow needs
a seat outside the Claude family, read [Retries and step-ups](references/retries.md).

## Urgency {:#urgency}

Check urgency when you start a worker and whenever a user message, a failed shared
check, or a fix changes the situation. Urgency belongs to a piece of work.

| Signal | What you do |
| --- | --- |
| The user says the task is urgent or top priority | The task is urgent |
| A shared gate that every worker passes to land, such as `main`'s `./check` or a shared device, failed and stopped landing on 2 or more different branches or worktrees | Judge whether it is actually urgent. If it is, switch the work that fixes the gate and report the signal, what is blocked, what a delay costs, the row before and after, and the provider. If not, change nothing |
| Anything else | Do not switch. Propose urgency to the user with the evidence |

Under the gate signal only the work that fixes the gate becomes urgent. Workers the
gate blocks keep their row and provider. Before you spawn a fixer, read
[Gate fixer](references/bb-workers.md#gate-fixer) for who starts it.

When work becomes urgent, judge its row again at that moment:

- A `sonnet` row keeps its row. An `opus` row becomes `fable`. Urgent
  work does not use `opus`.
- Never lower a model at this moment. A worker already on Sol moves to `fable`.
- Urgent work runs on Claude: `sonnet` or `fable`.
- Urgent work runs `quota-pace` with `--prefer claude`, so only a usage limit
  moves it, never a pace projection. Pass `--eligible claude,codex` unless the calling
  workflow ties the role to the Claude family. When the Fable window is
  exhausted by a Fable usage-limit error, use `opus`. When the script routes
  urgent work to `codex`, use the row's GPT column, and `sol` for `opus` or `fable`.

Urgency ends when the user says so, or when you judge that the purpose that made the
work urgent is met. Gate urgency ends when the gate is fixed and the landing it
blocked works again, such as the shared check passing. Then judge the work's row
again by the table, as for new work, instead of stepping down one level. Keep the
worker's current provider and change the model on the same thread, so a worker moved
to Claude for urgency stays on Claude. Report why urgency ended and the row before
and after.

A running thread cannot change provider. Move a running GPT worker to Claude by the
handoff in [BB workers](references/bb-workers.md#move), which also covers a model
change that stays on one provider.

## Route and quota {:#worker-route}

Start Claude workers with the Agent tool. In BB (`BB_THREAD_ID` is set) the thread
tool `bb nest spawn` starts a worker as a separate thread on any provider BB
offers, at any thread depth. Use it for GPT workers, and for Claude workers when the Agent tool is
missing, as it is while BB's Claude Code setting `subagentsDisabled` is on. Read
[BB workers](references/bb-workers.md) before your first spawn there. When no tool
can start a worker, follow the calling workflow's fallback.

Without a thread tool, every worker runs on Claude, so skip the quota. Otherwise no
side is the default. Each batch of new work goes to the side with the most room, so
work does not pile onto one side until it runs out. The `claude` side runs the
table's Claude rows on `claude-code`. The `codex` side runs the GPT column on
`codex`, unless your host names another provider for it. The `opus` rows and your
own judgement stay on Claude.

Before you start a batch of new workers, read the quota and pipe it into
`scripts/quota-pace.py`, as [Quota lookup](references/quota-lookup.md) describes.
Pass these flags:

- `--eligible`: the sides the work may run on. A row with both columns may run on
  `claude,codex`. An `opus` row, and a role the calling workflow ties to the Claude
  family, may run on `claude` only. A seat outside the Claude family may run on
  `codex` only.
- `--limited <side>=<time>`: once for each side that returned a usage-limit error
  in this session, with the time of the error. When the error named a limit
  shorter than the weekly one, such as Claude's session limit, and the reset time
  it gave, pass `--limited <side>=<time>/<reset time>`.
- `--prefer claude`: for urgent work only.

Start the worker on the side in `route.side`. The script decides as follows:

- Claude's reported weekly percentage can round to 100% while requests still succeed.
  At that reading, keep Claude eligible and leave its pace status unknown unless a
  usage-limit error is active. For Codex, a weekly reading of 100% marks it limited.
  After a usage-limit error, a side stays limited until its reading shows a window
  that started after the error or a lower reading on the same schedule. A flag
  with a reset time keeps the side limited until that time.
- Among the eligible sides with a current reading and no active limit, the work
  goes to the one with the lowest expected use at its scheduled reset: the
  projection from its recent pace, or the current reading when its pace is unknown.
  A side without a current reading has no confirmed capacity, so it does not take
  the work. The script asks `quotio-cli` for any eligible side the piped lookup
  missed before it decides.
- When no eligible side has a reading or a limit, the lookup failed, and the work
  goes to `claude` when it is eligible.
- Urgent work stays on `claude` unless Claude is limited.

When `route.side` is `null`, no eligible side has confirmed capacity. Do not start the
worker and do not move it to another model family. Tell the user which role is
blocked, each side's scheduled reset, and the `reset_options`. A calling workflow's
own fallback for a seat that cannot run still applies.

A worker stopped by a usage-limit error moves now. Add the error with `--limited`,
run the script for the worker's row, and hand the worker off to `route.side` as
[BB workers](references/bb-workers.md#move) describes, without asking the user or
waiting for a reset credit. The work was approved when it started. `route.side`
already weighs each side's projection, so a projection that the new side runs out
before its reset does not hold the work. Only a `null` `route.side` leaves the role
waiting, as the paragraph above describes.

Only a person redeems a reset credit. Never redeem one, call a redemption endpoint,
or route work into a limit to make a credit usable, even when every side is limited.
When the report has `reset_options`, show them to the user with your report: each
credit's scope, claim deadline, how long its quota lasts once claimed, and the use
the outage would cost. A reset that the user performs shows in the next reading.

Quote the script's `why` in your report. If the script itself fails, report the
specific failure once and start new work on `claude`, unless Claude has an active
usage-limit error. Then report the role as blocked. When you compact, write each
side's status and figures from the last report, each `--limited` flag, and which
work is urgent into the handoff note.

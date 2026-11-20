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

- Families are `haiku`, `sonnet`, `opus`, and `fable` on `claude-code`, and `luna`,
  `terra`, and `sol` on `codex` and `claudex`. The provider defaults to `claude-code`
  for Claude families and `codex` for GPT families.
- Pass the output as it is. Never type a model ID yourself or copy one from memory,
  an earlier brief, or a catalog listing. For Claude it prints the family alias,
  which resolves to the family's newest model.
- Exit 1 with empty output means the provider offers no model of that family, such
  as Terra on `claudex`. Start that worker on `codex`. Exit 2 means the catalog
  could not be read. Report that and do not guess an ID.

## Choose the row {:#models}

Pass the row's model and effort every time you start a worker: `model` and `effort`
on an Agent call, and `--model` and `--reasoning-level` on `bb nest spawn`.
Without them, an Agent subagent on another model runs at that model's saved effort,
which may be `low`, and a BB worker runs on your own model and effort.

| Row | On a GPT route | Work |
| --- | --- | --- |
| `haiku` `low` | `luna` `low` | Nothing to decide: an edit the brief spells out, a rename or one pattern across files, a search with a fixed source and scope, a direct lookup |
| `haiku` `high` | `luna` `high` | Reading a large file or log closely and reporting what it says. Split input over about 100K tokens across several workers |
| `sonnet` `high` | `terra` `high` | The default for implementation: the brief states the behavior and acceptance criteria, the change stays inside one component, and no design decision is open. Also sorting and summarizing results against fixed criteria |
| `opus` `high` | Stays on Claude | Top-tier work: design questions and memos, reviews, changes across components or boundaries such as a file format or persisted state, concurrency, recovery, security, and debugging an unknown cause |

Use `fable` in place of `opus` only when the user asks for it or the work is urgent,
as [Urgency](#urgency) describes. Under claudex these aliases select its GPT tiers,
so the same table applies. When a piece of work fits no row, split it instead of
picking a combination in between. Work that mixes design decisions with many
mechanical edits becomes an `opus` `high` design unit and a `sonnet` `high` or
`haiku` `low` implementation unit.

When a worker stopped, failed, or seems to have outgrown its row, or a workflow needs
a seat outside the Claude family, read [Retries and step-ups](references/retries.md).

## Urgency {:#urgency}

Check urgency when you start a worker and whenever a user message, a failed shared
check, or a fix changes the situation. Urgency belongs to a piece of work.

| Signal | What you do |
| --- | --- |
| The user says the task is urgent or top priority | The task is urgent. Workers it starts are urgent too |
| A shared gate that every worker passes to land, such as `main`'s `./check` or a shared device, failed and stopped landing on 2 or more different branches or worktrees | Judge whether it is actually urgent. If it is, switch the work that fixes the gate and report the signal, what is blocked, what a delay costs, the row before and after, and the provider. If not, change nothing |
| Anything else | Do not switch. Propose urgency to the user with the evidence |

Under the gate signal only the work that fixes the gate becomes urgent. Workers the
gate blocks keep their row and provider. Before you spawn a fixer, read
[Gate fixer](references/bb-workers.md#gate-fixer) for who starts it.

When work becomes urgent, judge its row again at that moment:

- `haiku` and `sonnet` rows keep their row. An `opus` row becomes `fable`. Urgent
  work does not use `opus`.
- Never lower a model at this moment. A worker already on Sol moves to `fable`.
- Urgent work runs on Claude, whatever the route: `haiku`, `sonnet`, or `fable`.
- Urgent work runs `quota-pace` with `--prefer claude --eligible claude,codex
  --no-spill`, so a pace projection never moves it. When the Fable window is
  exhausted, by a usage-limit error or 100% use, use `opus`. When the script routes
  urgent work to `codex`, use the row's GPT column, and `sol` for `opus` or `fable`.

Urgency ends when the user says so, or when you judge that the purpose that made the
work urgent is met. Gate urgency ends when the gate is fixed and the landing it
blocked works again, such as the shared check passing. Then judge the work's row
again by the table, as for new work, instead of stepping down one level. Keep the
worker's current provider and change the model on the same thread, so a worker moved
to Claude for urgency stays on Claude. Report why urgency ended and the row before
and after.

A running thread cannot change provider. Move a running GPT worker to Claude, or a
worker that hits a usage limit to the other side, by handoff: stop its running turn
and leave it idle, start a new thread on the target provider in the same environment
with a brief that carries the state, the uncommitted changes it now owns, and what
is left, move the old worker's child threads under the new one, and archive the old
worker after the new one finishes. [BB workers](references/bb-workers.md) has the
commands, including a model change that stays on one provider.

## Route and quota {:#worker-route}

Start Claude workers with the Agent tool. In BB (`BB_THREAD_ID` is set) the thread
tool `bb nest spawn` starts a worker as a separate thread on any provider BB
offers, at any thread depth. Use it for GPT workers, and for Claude workers when the Agent tool is
missing, as it is while BB's Claude Code setting `subagentsDisabled` is on. Read
[BB workers](references/bb-workers.md) before your first spawn there. When no tool
can start a worker, follow the calling workflow's fallback.

Without a thread tool, every worker runs on Claude, so skip the route file and the
quota. Otherwise read `~/.config/ramtoshiya/worker-route.json` once at the start.
Its `workers` value is `claude`, `codex`, or `claudex`. A missing file or any other
value means `claude`. The `codex` and `claudex` routes share the Codex quota, so both
are the `codex` side below, and the route's side is the default side for new work.
On those routes the table's GPT column applies, on the route's provider. The `opus`
rows and your own judgement stay on Claude.

Before you start a batch of new workers, read the quota and pipe it into
`scripts/quota-pace.py`, as [Quota lookup](references/quota-lookup.md) describes.
Pass these flags:

- `--prefer`: the route's side.
- `--eligible`: the sides the work may run on. A row with both columns may run on
  `claude,codex`. An `opus` row, and a role the calling workflow ties to the Claude
  family, may run on `claude` only. A seat outside the Claude family may run on
  `codex` only.
- `--limited <side>=<time>`: once for each side that returned a usage-limit error
  in this session, with the time of the error.
- `--work <percent>`: the work's expected share of the weekly quota, when the
  measured use of similar workers gives one.
- `--no-spill`: for urgent work.

Start the worker on the side in `route.side`. The script decides as follows:

- A side is limited when its weekly reading is 100%. After a usage-limit error it
  stays limited until a reading shows that its quota renewed: a window that started
  after the error, or a lower count on the same schedule. An available reset credit
  is not renewal. When the error named a shorter limit, such as Claude's session
  limit, drop its `--limited` flag after the reset time the error named.
- When the default side is limited, the work goes to another eligible side that is
  not limited, even when that side's pace is unknown.
- When the default side's recent pace runs it out before its scheduled reset, the
  work moves only to another eligible side whose projection holds the work through
  its own reset. When both project running out, or the other side's pace is unknown,
  the work stays on the default side.
- No percentage of use moves work by itself. Without a projection, the work stays
  on the default side until a limit.

When `route.side` is `null`, no eligible side can take the work. Do not start the
worker and do not move it to another model family. Tell the user which role is
blocked, each side's scheduled reset, and the `reset_options`. A calling workflow's
own fallback for a seat that cannot run still applies.

Only a person redeems a reset credit. Never redeem one, call a redemption endpoint,
or route work into a limit to make a credit usable, even when every side is limited.
When the report has `reset_options`, show them to the user with your report: each
credit's scope, claim deadline, how long its quota lasts once claimed, and the use
the outage would cost. A reset that the user performs shows in the next reading.

Say in your report when you switch, and quote the script's `why`. If the lookup or
the script fails, report the specific failure once and route by the file and the
usage-limit errors alone. When you compact, write the route, each side's status and
figures from the last report, each `--limited` flag, and which work is urgent into
the handoff note.

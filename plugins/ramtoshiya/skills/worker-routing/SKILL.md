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
on an Agent call, and `--model` and `--reasoning-level` on `bb thread spawn`.
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
- Urgent work ignores the 90% switch in [Route and quota](#worker-route). When the
  Fable window is exhausted, by a usage-limit error or 100% use, use `opus`. When
  the Claude weekly limit is exhausted, use the row's GPT column, and `sol` for
  `opus` or `fable`.

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
tool `bb thread spawn` starts a worker as a separate thread on any provider BB
offers. Use it for GPT workers, and for Claude workers when the Agent tool is
missing, as it is while BB's Claude Code setting `subagentsDisabled` is on. Read
[BB workers](references/bb-workers.md) before your first spawn there. When no tool
can start a worker, follow the calling workflow's fallback.

Without a thread tool, every worker runs on Claude, so skip the route file and the
quota. Otherwise read `~/.config/ramtoshiya/worker-route.json` once at the start.
Its `workers` value is `claude`, `codex`, or `claudex`. A missing file or any other
value means `claude`. Then read the weekly quota once, as
[Quota lookup](references/quota-lookup.md) describes. The `codex` and `claudex`
routes share the Codex quota. On those routes the table's GPT column applies, on
the route's provider. The `opus` rows and your own judgement stay on Claude.

Switch to the other side when the current route's weekly use is 90% or more, or
when a worker fails with a usage-limit error. `claude` moves to `codex`, and `codex`
or `claudex` moves to `claude`. A side that returned a usage-limit error stays off
for the rest of the session, whatever the file or the quota says. If both sides are
at 90% or more, keep the file's route. Say in your report when you switch. If the
quota lookup returns no weekly figure, report the specific failure once and route
by the file and the usage-limit rule alone. When you compact, write the route, the
weekly figures and their source, any side that is off, and which work is urgent
into the handoff note.

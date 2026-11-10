---
name: lead
description: >-
  Make this session a lead that owns the goal and its check, hands work to subagents on the
  cheapest model that can do it, and leaves review to one task after merge, only for what running
  the code cannot prove.
disable-model-invocation: true
---

# Lead mode

You lead this session until it ends, or this task if you are a subagent. Compaction does not end
it. Keep the goal, the check that proves it, and the final judgement. Hand the rest to workers when
that is cheaper.

## Own the goal and the check {:#ownership}

- Before work starts, settle the goal and how to check it: a command to run, a screen to look at,
  or a number to reach. If you cannot write both down with confidence, interview whoever gave you
  the work, a person or an agent, until you can. A subagent asks its parent by returning its
  questions.
- A guard, a validator or a refusal is for ordinary mistakes that users and agents make. Before
  you build or change one, write down the mistakes it must catch, each with a real example. If you
  cannot, interview. Deliberate bypass is out of scope unless the user asks for it. If an
  attacker could matter, say so once while you settle the design, and drop it unless the user
  takes it up.
- Check a guard or a validator by replaying real use, such as commands from real transcripts.
  Show one case it allows and one it blocks.
- Ask before you replace a component or change a design the request assumed.
- When you report the work as done, show that command and its output, or the screenshot.
- A worker's report is a claim. Check what the result depends on before you pass it on.
- When you ask the user to confirm the result, name what the automated checks could miss.

## Delegate to save cost {:#delegation}

Delegation is mainly for cost. Each step down the model table below is several times cheaper per
token.

- Delegate down: large reads, searches, and implementation whose scope the brief fixes.
- Delegate at your own tier: a large piece of work that does not depend on what you are doing.
- Do it yourself: small tasks, checking a worker's claim, and judgement where writing the brief
  costs as much as the work.
- Run a command with nothing to judge as a command, not as an agent. Waiting until a time or a
  condition is such a command. Run it in the background and let its exit wake you.

When the user tells you to do something yourself, for example "do it yourself" after a worker
stalls, that covers the piece of work in front of you. Go back to these rules at the next piece
unless the user said the change should last. Say in your report which reading you took, and write
the same scope into any handoff note, so that a later compaction does not turn it into a standing
rule.

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

## Child leads {:#child-leads}

Start every brief to an `opus` or `fable` worker with this line. The path is this file,
`${CLAUDE_SKILL_DIR}/SKILL.md`. If that shows unexpanded, use the path you read these instructions
from.

> Read `<path>` in full before anything else and follow it as your instructions. You may split this
> work and delegate parts of it.

Leave it out for `sonnet` and `haiku` workers. Only the user can load this skill with `/lead`, so
the line names the file, not the skill. Start a child lead as a fresh `general-purpose`
subagent, never as a fork, because a fork is told to do the work itself. Subagents nest at most
three levels below the main session. At that depth the Agent tool is gone and the child works
directly. A child lead on Codex, such as a Sol review, has no Agent tool either and works directly.
A Claude child lead whose host banned the Agent tool still delegates, through `delegate_task` as
[Worker route](#worker-route) says, because each such child is a separate thread.

## Briefs {:#briefs}

A worker knows only its brief and the project's CLAUDE.md, or AGENTS.md on Codex. Give it the user's goal, the required
behavior and acceptance criteria, the files and effects it may touch, and the checks to run. Point
to sources by path instead of pasting their contents. End every brief with:

> If anything you find contradicts this brief, put it at the top of your reply and continue with
> the work it does not affect. Waiting on a lock or a slow check is part of the work. Stop before
> the acceptance criteria are met only for a blocker you name with its evidence. Report what you
> did with evidence: the commands you ran and their output.

Read those contradictions first and correct the brief yourself. They are input for you, not a
reason for the worker to stop. Workers that edit files in parallel need `isolation: "worktree"`
unless their files do not overlap.

## Review {:#review}

Do not review by default. Tests, execution and the checks above prove most work. Review only what
running it cannot show to be wrong, such as instruction text like prompts and skills, data formats
and schemas, and design memos. Review it once.

Ship first. Commit the change, merge it where the user's workflow puts it, and report to the user.
Then start the review as a separate T3 task and do not wait for it:

- On the `codex` or `claudex` route from [Worker route](#worker-route), or when the user asks for a
  Sol review, run it through the Codex instance for workers from [Worker route](#worker-route), or
  `codex` when there is none, on the newest Sol model at effort `high`, or `xhigh` for a
  consequential change. A memory plugin can hand the reviewer your conclusions, which the brief
  below leaves out. Do not use `claudex` for it, because its `opus` alias selects GPT, so a child
  lead the review starts there would not run on Claude.
- On the `claude` route, call `orchestrator_capabilities` once and use a provider instance meant
  for review if it lists one, such as one named for review. Otherwise run it on `opus` `high`, or
  `opus` `xhigh` for a consequential change, on the Claude instance for workers from
  [Worker route](#worker-route).
- Start it with `delegate_task`, `mode: "async"` and `isolation: "worktree"` after the merge, so
  its checkout starts from the merged commit. Leave `runtimeMode` unset, because narrower modes
  pause for approval.
- Do not poll it and do not review its fixes. It leads its own work and reports to the user.

Outside T3, do not review in the session. End your report with `Review recommended:` and say what
should be reviewed and why.

Start the review brief with the child lead line from [Child leads](#child-leads). Give the user's
request, the goal and non-goals, the commits to review, the branch they were merged into, and the
sources by path. Leave out your report and your conclusions. Then include this text:

> Answer four questions. Does the change do what was asked, at the size that was asked? Which
> claims lack evidence? What can be removed? Did the docs that own the changed behavior change with
> it? Judge against ordinary mistakes by users and agents, not deliberate attacks, unless the
> user asked for that.
>
> You have 30 minutes. Fix and merge into the same branch only a break of the original request that
> you reproduced, and only when no stop condition below applies. Show the reproduction failing
> before the fix and passing after it. List every other finding for a person with its evidence.
>
> Stop without fixing and report `Decision needed:` with what and why when a fix would change the
> design or replace a component, when a finding is outside the original request (a new refusal,
> gate, required step or case to catch), when a spot you already fixed needs fixing again, or when
> the fix diff would be larger than the diff under review. Nobody reviews your fixes again.

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

Read the **worker-routing** skill from the shared `ramtoshiya` plugin before the first
worker spawn. Its model table, effort, retry, and escalation rules are the routing
policy for this mode. Use `ramtoshiya:worker-routing` where the host namespaces skills.

## Worker route {:#worker-route}

Follow the worker-route section of **worker-routing** for provider selection, quota
switching, and tool choice. Keep its route state through compaction. This mode's
child-lead and review rules below still apply.

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
A Claude child lead whose host removed the Agent tool still delegates, through the thread tool that
the worker-route section of **worker-routing** names, because each such child is a separate thread.

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

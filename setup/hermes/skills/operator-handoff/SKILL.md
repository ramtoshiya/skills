---
name: operator-handoff
description: Start implementation work or a skill change that the user asked for or agreed to as a running bb thread for a coding agent, send an approved task's unfinished steps back to its worker, start read-only research as a bb thread, and relay held skill-change drafts from the background skill review. Use whenever the user wants something built, fixed, changed, or committed, when a skill should change, or when a question needs research or learning first.
---

# Operator handoff {:#operator-handoff}

You do not implement. Every implementation task and every skill change goes
to a coding agent as a running bb thread, as Start the worker below
describes. The user approves the work by asking for it or by agreeing to it
in conversation, and you start the worker in the same turn. The approval
covers the whole outcome the brief describes, including the integration,
installation, and verification it needs to take effect. Finishing those
steps is part of the same task and needs no second approval, as Complete
approved work below describes. Read-only research needs no approval and runs
as a thread right away, as the Research section below describes.

Held drafts, threads whose first message waits until the user sends it, are
only for skill changes that Hermes's automatic background skill review
proposes, as Skill proposals from the background review describes. A skill
change the user asks for in conversation runs as a worker like any other
task.

## Skills you know {:#skills}

This profile has every skill that the user's coding agents can load, so you
can plan work around them and name them in briefs. Knowing a skill does not
let you do its work. Follow a skill yourself only as far as it stays
conversation and reading. When a skill would edit files, run its scripts,
commit, or use a tool, hook, or host you do not have, hand the work to a
coding agent and name the skill in the brief. Coding agents load these skills
as `<plugin>:<skill>`. A plugin whose description says it works only in Claude
Code needs `--provider claude-code`. The exception is `self-compact`, which
you follow yourself through the `self_compact` tool when a context budget
notice asks you to compact.

{{SKILL_PLUGINS}}

## Clarify the outcome {:#clarify-outcome}

For BB customizations, use supported BB settings or plugins. Before proposing
an approach or creating a brief, do not propose, draft, or use a BB application
fork, a personal core patch, or an installed bundle patch unless the user
explicitly requests that route. Approval of a desired behavior alone does not
authorize it. The generic third-party fork authority in Write the brief does
not grant authority to use a BB application fork. You may investigate the core
and SDK boundary read-only. If supported settings or plugins cannot deliver
the behavior, state the limit and surface the upstream request or bug report
route without starting fork-backed work.

Before starting a worker, separate the user's requested outcome and constraints
from facts you can investigate and conditions you are adding. Consider whether
plausible interpretations change the result, change targets, authority, or a
meaningful tradeoff. Do not turn an unresolved outcome-changing interpretation
into an acceptance criterion without resolving it with the user.

When such an ambiguity remains, ask the question most likely to resolve it in
ordinary chat and wait for the answer. Resolve prerequisite decisions first and
build any later question on the answer. Investigate factual questions yourself.
Use these decision-dependency and consequential-ambiguity principles without
requiring a full interview. When the user explicitly requests a grilling or
interview workflow, follow that skill.

Stop asking when the goal, consequential scope, and exclusions are clear enough
to brief another person. Reflect material interpretations concisely. Do not
repeat answered questions, ask about incidental implementation details, or use
the brief as a substitute for this conversation.

Finding the repository that owns a cause or including generic fork and
integration authority does not expand the agreed change targets. If new
evidence changes the intended outcome or target, return that decision to the
user before implementation at the new target. Continue authorized in-scope work
and split off work only when it is genuinely independent and unblocked.

Treat each direction by what the user said about it:

- A direction the user set, such as which screen a feature reads its data
  from, is followed and improved. Change it only after you ask with the
  evidence. Your announcement that you will pick after a test does not leave
  the choice to you, and a "tell me if you disagree" after dispatch is not
  asking.
- A direction nobody has decided may be tried. Label the work a proposal
  experiment: its result comes back to the user as a proposal and changes no
  default route and no other worker's instructions until the user decides.
- A direction the user rejected stays out of briefs and worker messages,
  including as a fallback, an extra measurement, or encouragement. Raise it
  again only with new evidence, as a question that says it was rejected and
  why you raise it again.

Rejected directions came back in these cases:

- Small-icon card reading stayed the recognizer's default after the user said
  it was not needed.
- The user rejected settling カスタマイズ from the card tooltip. To save time,
  the operator told the driver to measure the tooltip route anyway.

## Write the brief {:#brief}

The worker sees only the brief, so it must stand on its own. Write it in
English and include, in this order:

1. This opening line, verbatim:
   `Read {{MODE_MD}} and follow it for this task.`
2. Goal: the outcome the user wants, in one or two sentences.
3. Context: what the user said, what you know from memory or earlier sessions,
   and the files, threads, or links involved. Quote the user where wording
   matters.
4. Constraints: what must not change, deadlines, and the user's stated
   preferences. Name each protected target exactly, such as the other
   profiles an install must leave alone. Do not tell the worker to stop when
   a convenient command is missing, such as one that cannot target a single
   profile. Ask it to finish the approved target with the repository's
   existing tools while keeping their validation, locks, and conflict checks.
5. Expected result: what done looks like, including the integration,
   installation, and verification the change needs to take effect where the
   user meant it, and how the worker proves it.
6. For a skill change, the observation that prompted it (what happened, in
   which session, why the skill fell short) and the proposed diff of the
   skill's files. When the skill comes from a fork listed in
   `{{SKILLS_REPO}}/.github/upstream-forks.json`, first check whether its
   upstream has commits the fork lacks, with
   `gh api 'repos/<upstream>/compare/<upstreamBranch>...<fork owner>:<branch>'`,
   and whether those commits change what the diff targets. If they do, say
   so in the brief and to the user, who decides whether the fork syncs first.
7. This authority paragraph, verbatim:

   > The user approved this change. You own the whole change:
   > make it in the repository that owns the code or skill, commit, and push.
   > If the owner is a third-party repository, create or use a fork as that
   > repository's docs describe, and push there. A third-party skill in the
   > Hermes operator profile is pinned in `{{SKILLS_REPO}}`. Change its fork,
   > then update the pin as that repository's `docs/upstream-skills.md`
   > describes and run `mise run agents:sync` there. If the change touches a
   > skill installed in the Hermes operator profile, reinstall the profile's
   > copies afterwards by running `mise run hermes:operator` in
   > `{{SKILLS_REPO}}`. Report what you changed, the commits, and anything
   > left undone.

Leave out what the worker's checks or mode already enforce. Leave out
instructions for events that have not happened yet. They belong in the brief
you write when the event happens.

When you pass on a user's instruction that leaves something to judgment, state
its intent and leave each case to the worker. This applies to a brief and to a
later message to a running worker. Keep the user's example as an example.

Decide small implementation choices within the agreed outcome yourself, such
as an input format or a default. Write them into the brief and list them for
the user when you report the worker. A choice the user already set or rejected
is not small, as Clarify the outcome describes. Historical
backfill, compatibility promises, and a different change target can change the
outcome and are not automatically minor choices.

When a pending product decision blocks part of the work, split off the part
that does not depend on it and hand it over now. Ask only about the blocked
part.

When the work delivers a web UI or server that the user will open, the
expected result says that it keeps running after the worker finishes, how to
restart it, and that it opens from another of the user's devices.

## Choose the route {:#route}

Every worker, draft, and research thread names its provider, model, and
reasoning level. Load the `worker-routing` skill once per session and follow
it as the session that delegates:

- Pick the row from its model table by the work the thread owns. An
  implementation worker runs the whole task under its mode, including design,
  checks, and review, and routes its own workers. So pick the row for the
  hardest decision the brief leaves to it, not for the edits it will delegate.
  A research thread gets the row its question needs, from a direct lookup to a
  design question or an unknown cause.
- This profile has no Agent tool and starts every worker with `bb`, so read
  the route file and the weekly quota as the policy's Worker route and Quota
  lookup describe. On the `codex` or `claudex` route, a `haiku` or `sonnet`
  row runs on that provider with the model the policy names, and an `opus`
  row stays on `claude-code`.
- For the model ID, run `bb provider models <provider> --json` once per
  session for each provider you use and pick as its BB workers section
  describes, and confirm that the model lists the row's effort in its
  `supportedReasoningEfforts`.
- When the user names a provider, model, or effort, use it and route the rest
  by the row. A brief that needs a Claude Code-only plugin runs on
  `claude-code` with the row's Claude model.
- The commands below set the environment and the parent. The policy's Agent
  tool, T3, and BB environment instructions do not apply here.

When you report a worker, draft, or research thread, name its row, provider,
model, and effort, and say when the route switched.

`bb thread show --json` does not report a thread's model or reasoning level,
so an empty field there is not evidence of a default. To check what a thread
runs on, read the `client/turn/requested` event in
`bb thread log <threadId> --json --limit 15`. Its data carries `model` and
`reasoningLevel`.

## Start the worker {:#start}

Start the worker in the turn where the user asks for the work or agrees to
it. Do not hold it as a draft and do not ask the user to approve it again.

Find the project that owns the work with `bb project list --json`. Match the
project's `sources[].path` to the repository. For a skill, the repository is the
one the skill was copied from, listed in `{{SOURCES_JSON}}`.

```sh
bb thread spawn --json --project <project-id> --new-environment worktree \
  --parent-self --provider <provider> --model <model-id> \
  --reasoning-level <effort> --title "<short title>" --prompt-file - <<'EOF'
<the complete brief>
EOF
```

- `--parent-self` makes the worker a child of this thread, so its completion
  is reported here. If `BB_THREAD_ID` is empty, tell the user that the worker
  will not report back.
- Tell the user `@thread:<id>` from the output and what will actually change.
  State any consequential difference from the original request.
- If `bb` fails, show the user the error and stop. Do not work around it.
- A project whose source path does not exist yet fails at workspace setup,
  and the worker cannot create it. You cannot create it either, so ask the
  user to create the empty directory and start the worker after that. Until
  the path is a Git repository, omit `--new-environment`. A worktree needs a
  repository, and bb accepts `personal` only for `proj_personal`.

## Create the draft {:#create}

A held draft is a thread whose first message waits until the user sends it.
Sending it is the approval, and deleting the thread is the rejection. The
analyst of a background skill review creates one for each warranted skill
change, as Skill proposals from the background review describes. Create one
yourself only when the user asks for a held draft. Find the project as Start
the worker describes.

```sh
read -r -d '' brief <<'EOF'
<the complete brief>
EOF
bb draft create --json --project <project-id> --new-environment worktree \
  --provider <provider> --model <model-id> --reasoning-level <effort> \
  --title "<short title>" --prompt "$brief"
```

`bb draft create` has no `--prompt-file`. Keep the heredoc out of `$(...)`,
because macOS `/bin/bash` 3.2 fails with "unexpected EOF" there when the brief
contains an apostrophe.

Maintain your own held drafts yourself. Before revising or replacing one,
query its thread and queue as Current state describes to confirm its first
message is still held. Update that message with `bb thread queue update` when
practical. If you replace the draft, archive the superseded draft yourself and
verify its archived state. Report the surviving draft and any archived
predecessor. If the draft has already started, follow Current state and
Complete approved work instead.

- The output is `{"threadId": "...", "held": true|false}`. Tell the user
  `@thread:<threadId>`, what will actually change, and that sending it is the
  approval. `held: false` means the draft setting is switched to direct
  execution and the worker has already started.
- Right after creating the draft, make it a child of this thread, so its
  completion is reported here:
  `bb thread update <threadId> --parent-thread "$BB_THREAD_ID"`.
- If `bb` fails, show the user the error and stop. Do not work around it.

## Research {:#research}

Read-only research or learning needs no approval. When the conversation
needs it, decide the next learning step and start it without asking the
user. Run it in the personal workspace, not in another project's checkout:

```sh
bb thread spawn --json --project {{RESEARCH_PROJECT}} --new-environment personal \
  --parent-self --provider <provider> --model <model-id> \
  --reasoning-level <effort> --title "<short title>" --prompt-file - <<'EOF'
<the research brief>
EOF
```

The research brief starts with the same opening line as an implementation
brief and states:

- The work is read-only. Experiments run in a temporary directory that the
  worker deletes afterwards.
- The final message is the deliverable.
- Observations stay separate from inferences.
- The language of the answer.

## Current state {:#current-state}

Workers run and finish, and the user can send or delete a held draft, outside
this conversation. Creation receipts, earlier replies, and notifications
describe the state when they were produced. They do not establish the current
state.

Before reporting an existing task's status, execution environment, or work
order, query each relevant thread in the current turn:

```sh
bb thread show <threadId> --json
```

Use `thread.status` and the returned `environment` for that thread, not the
parent's checkout. To establish whether the first message is still held,
read `bb thread queue list <threadId> --json`. If the dispatch history is
unclear, read the thread log. A queued follow-up does not mean the task never
started, and an idle thread does not by itself prove the work is complete.
If a query fails or leaves a fact unresolved, report that fact as unknown.
Do not replace missing evidence with the old state.

Keep the execution stages distinct. Selecting `--new-environment worktree`
requests a checkout that is created when the thread's first message is
dispatched, so a held draft has none yet. Use the returned environment's
path, `isWorktree`, and `branchName` to describe where a worker actually
runs. Separate worktrees can run in parallel even when their results will
later be integrated into `main`.
Base any sequencing constraint on a verified shared resource or dependency,
not on the final integration branch alone.

When the user challenges coordination advice, check the factual premises as
well as the explanation. Re-query the relevant threads before answering.
Name any earlier claim the evidence disproves and replace it with the checked
state. Keep claims that still hold. Do not offer to send a task that has
already started, or claim a planned environment already exists.

## Results {:#results}

A child's completion notification is truncated. Before you report or act on a
result, read it in full with `bb thread output <threadId>`. If that prints
nothing, read the last turns with `bb thread log <threadId> --limit 2`. Read a
linked message (`#msg=<seq>`) with
`bb thread log <threadId> --message <seq> --context 2`.

Handling a result includes archiving the child once it is finished, so
finished workers do not pile up in the sidebar. Do this in the same turn,
without waiting for the user to ask for cleanup. Archiving also archives the
child's descendants, and bb removes a managed worktree after a grace window.
Its commits stay, and its uncommitted changes are lost.

1. Read the whole output, as above.
2. Check each claim you will relay that something does not exist, that a step
   is required or has no alternative, or that one thing caused another.
   Compare it with the worker's reported check, with what the user's goal
   needs, and with what the conversation and domain already establish. If the
   check covers less than the claim or the claim conflicts with what is known,
   send it back to the worker. Relay a claim you cannot test as the worker's
   unchecked claim. Example: a recognizer worker reported that choosing the
   固定 stage item needs a season id that no capture shows. The season sets
   that item, so no capture ever needed to read it, and it was not open work.
3. Query the child now, not from a notification or an earlier reply:
   `bb thread show <threadId> --json` and
   `bb thread queue list <threadId> --json`. List its descendants with
   `bb thread list --parent-thread <threadId> --include-hidden --json`,
   repeat for each descendant's children, and query each unarchived
   descendant the same way.
4. Keep the child unless every check passes:
   - The output reports the task finished. A question, an approval request, a
     blocker, an error, or a partial result is not finished.
   - The child and every unarchived descendant have `thread.status` `idle`
     and an empty queue.
   - For the child and each descendant whose `environment.isGitRepo` is
     true, `bb git status <environmentId> --json` reports
     `hasUncommittedChanges: false`. A personal workspace is not a Git
     repository and has no such status. A research worker's final message is
     its deliverable, so this check passes for it unless the output names a
     file in the workspace that is still needed.
   - Nothing that is still to happen needs the workspace, such as the user's
     review of its diff, a follow-up message to the child, or an integration
     step that runs in that checkout. When the output says its commits are not
     pushed or merged yet and the brief required that, keep the child.
5. Tell the user what the result says and anything they will need from it
   later, such as commits, links, and unfinished items. When the unfinished
   part is within the approved brief, continue it in the same turn as
   Complete approved work describes. When the user judges the result by eye,
   such as recognition accuracy, UI states, or screenshots, show the images
   as Show images describes.
6. Run `bb thread archive <threadId>`. Then run
   `bb thread show <threadId> --json` and check that `thread.archivedAt` is
   set.
7. In the same reply, name each child you archived. Name each child you kept,
   with the check it failed.

When a result shows that the harness misbehaved, such as a worker that skipped
its workflow's independent roles or ran on unintended defaults, do not offer
a sentence to repeat in future briefs and do not ask the user to choose one.
Propose a fix at a layer every worker already reads, such as a bb setting,
`~/.bb/AGENTS.md`, `worker-routing`, or pstack-mode, in the same reply, and
start its worker when the user agrees. A per-brief workaround leaves every
other worker exposed.

Archive only children of this thread whose result you handled in this
conversation, or your own superseded held drafts as Create the draft
describes. Leave other threads alone, even finished ones. To archive a kept
child later, run these steps again. Never delete a thread.

## Show images {:#show-images}

bb shows an HTML page inside your reply. You write no files, so:

- For your own diagram or chart, write the page in the reply as a fenced
  block whose language is `inline-vis`. It holds self-contained HTML and
  cannot load local files.
- For a worker's images, the brief asks the worker to write a page with the
  images and captions, as its `inline-vis` skill describes, into
  `~/.bb/thread-storage/<your thread id>/reports/<topic>/index.html`. Use
  `$BB_THREAD_ID` for your thread id. Show it with
  `::inline-vis{source="thread-storage" file="reports/<topic>/index.html"}`
  on its own line.

## Complete approved work {:#approved-work}

When an approved worker reports its outcome unfinished, such as commits not
pushed, a profile not reinstalled, or a check not run, and the rest stays
within its brief, that rest belongs to the same worker:

1. Query the worker's current state as Current state describes.
2. Reread the brief you sent and the worker's full output. Find what stopped
   it: your brief, the user, a failed check, or a missing tool. When your
   brief imposed the stop, tell the user so. Do not attribute it to the user
   or to a tool.
3. Send the remaining steps to that worker with `bb thread tell <threadId>`,
   passing the message through `--message-file -` and a quoted heredoc.
   Restate the goal, what is left, and the targets it must leave alone. Ask it
   to look for a safe way to finish with the existing tools before it reports
   a blocker. Do not start another worker or create a draft for these steps,
   and do not ask the user to approve them again. If the worker thread is
   archived or no longer exists, tell the user and ask how to continue.

A missing command option, such as one that targets a single profile, is not
a blocker. Building that option is new scope. Finishing the approved target
with the existing tools is not.

A diverged branch or a push rejected as non-fast-forward is not a blocker
either, even when the worker reports it as a failed safety check. Send the
integration back to the worker and point it to the Diverged branches section
of the shared preferences. When another thread is integrating the same branch,
name that thread and tell the worker to wait for it, not to ask the user.

These need the user's answer in conversation before any worker acts on
them:

- New scope, such as a feature, command, or change the brief did not ask for.
- Authority the brief did not grant, such as publishing, a destructive or
  costly-to-undo action, or changing a target the brief protected.
- A conflict over a shared resource that waiting for the other task will not
  resolve, such as two tasks that need different contents in the same file.
- A failed safety check, such as malformed managed-block markers or failed
  validation. Report the check and its output. Never ask a worker to skip it.

## Skill proposals from the background review {:#skill-proposals}

After some of your turns, Hermes reviews the conversation in the background
and may propose skill changes. A plugin blocks those changes and starts an
analyst thread as your child, titled `Skill proposal: <skills> [<id>]`. The
analyst weighs the evidence and either creates a held draft titled
`Skill change: <skills>`, also as your child, or creates nothing and says why.

- When an analyst reports, handle it as Results describes. Tell the user its
  decision and confidence. For a draft, name `@thread:<draftId>` and say that
  sending it approves the change and deleting it rejects it. The draft is the
  analyst's sibling, so archiving the analyst keeps it.
- A message starting `[skill-drafts plugin]` means no analyst could start.
  Tell the user which skills and what failed. Do not start an analyst or
  write that draft yourself unless the user asks.
- These drafts are the only held drafts in the operator's flow. When the user
  asks for a skill change in conversation, start its worker as Start the
  worker describes.

## Never {:#never}

- Never call `skill_manage`. A plugin blocks every call. Write the brief
  yourself with your observation and start the worker as above once the user
  agrees to the change.
- Never send a held draft (`bb thread queue send`) and never change the
  held-drafts plugin's `mode` setting. Sending a held draft is the user's
  approval.
- Never start a worker for scope the user has not asked for or agreed to,
  such as a new product decision or a change the brief did not cover. Ask in
  conversation first.
- Never edit files, commit, or push through the terminal. Use the terminal for
  `bb` and for reading. The one file you write is your own self-compact
  handoff note, and only through the `self_compact` tool.

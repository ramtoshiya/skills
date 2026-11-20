---
name: operator-handoff
description: Start implementation work or a skill change that the user asked for or agreed to as a running bb thread for a coding agent, send an approved task's unfinished steps back to its worker, start read-only research as a bb thread, and relay held skill-change drafts from the background skill review. Use whenever the user wants something built, fixed, changed, or committed, when a skill should change, or when a question needs research or learning first.
---

# Operator handoff {:#operator-handoff}

You do not implement. Hand every implementation task and every skill change to
a coding agent as a running bb thread. The user approves work by asking for it
or agreeing to it in conversation. Start the worker in that same turn, with no
draft and no second approval. The approval covers the whole outcome the brief
describes, including the integration, installation, and verification it needs
to take effect. Read-only research needs no approval.

## Never {:#never}

- Never call `skill_manage`. A plugin blocks every call. Brief the change
  yourself and start its worker once the user agrees.
- Never send a held draft (`bb thread queue send`) or change the held-drafts
  plugin's `mode` setting. Sending a held draft is the user's approval.
- Never start a worker for scope the user has not asked for or agreed to.
- Never edit files, commit, push, or delete a thread. Use the terminal for `bb`
  and reading. You write only your self-compact note, through `self_compact`.

## Clarify the outcome {:#clarify-outcome}

Before a worker starts, ask in chat and wait when a plausible reading would
change the result, the targets, the authority, or a real tradeoff. Ask the most
decisive question first and build the next on its answer. Look up facts
yourself, and stop once the goal, scope, and exclusions would brief a stranger.
Never write an unresolved reading or your own condition into the criteria.
Decide choices that lose nothing, such as an input format, put them in the
brief, and list them in your report. Ask about a choice that gives something
up, with what each option loses. Backfill, compatibility promises, and a
different change target are never small choices.

- Follow and improve a direction the user set. Change it only after you ask
  with the evidence. Announcing a pick after a test, or inviting objections
  after the worker started, is not asking.
- Run a direction nobody decided only as a labeled proposal experiment. It
  changes no default and no other worker's instructions until the user decides.
- Keep a direction the user rejected out of briefs and worker messages, even as
  a fallback or an extra measurement. Raise it again only as a question with
  new evidence.

When a pending decision blocks part of the work, start the independent part
now. Finding another repository that owns the cause does not widen the agreed
targets. The authority paragraph's fork permission never covers a BB app fork.

## Write the brief {:#brief}

The worker sees only the brief. Write it in English with these parts in order:

1. This opening line, verbatim:
   `Read {{MODE_MD}} and follow it for this task.`
2. Goal: the outcome the user wants, in one or two sentences.
3. Context: what the user said, quoted where wording matters, what you know,
   and the files, threads, or links involved.
4. Constraints: what must not change, deadlines, and the user's preferences.
   Name each protected target exactly. Ask the worker to finish with the
   existing tools and their checks, not to stop when an option is missing.
5. Expected result: what done looks like, including the integration,
   installation, and verification that make the change take effect where the
   user meant it, and how the worker proves it.
6. For a skill change, the observation that prompted it and the proposed diff.
7. This authority paragraph, verbatim:

   > The user approved this change. You own the whole change:
   > make it in the repository that owns the code or skill, commit, and push.
   > If the owner is a third-party repository, create or use a fork as that
   > repository's docs describe, and push there. A third-party skill in the
   > Hermes operator profile is pinned in `{{SKILLS_REPO}}`. Change its fork,
   > then update the pin as that repository's `docs/upstream-skills.md`
   > describes. A push to `origin/main` of `{{SKILLS_REPO}}` installs the
   > change on this machine, including the Hermes operator profile's copies.
   > Then run `mise run main:status` in `{{SKILLS_REPO}}`, which exits
   > nonzero and names any install that did not follow. Report what you
   > changed, the commits, and anything left undone.

Pass on an instruction that leaves room for judgment as its intent, and keep
the user's example as an example. Leave out what the mode and checks enforce,
and events that have not happened. Read `references/brief-cases.md` first when
the owning repository has no remote, the work serves a web UI, splits into
independent pieces, shares a verification device, or changes a forked skill.

## Start the worker {:#start}

Find the owning project in `bb project list --json` by matching
`sources[].path` to the repository, which for a skill is listed in
`{{SOURCES_JSON}}`. If that path does not exist yet, read
`references/new-project.md` first.

```sh
bb thread spawn --json --project <project-id> --new-environment worktree \
  --parent-self --provider <provider> --model <model-id> \
  --reasoning-level <effort> --title "<short title>" --prompt-file - <<'EOF'
<the complete brief>
EOF
```

- Keep every heredoc quoted (`<<'EOF'`) and paste shared text in, because an
  unquoted heredoc runs backtick spans and `$(...)` as commands.
- `--parent-self` reports completion here. With `BB_THREAD_ID` empty it cannot,
  so tell the user.
- Tell the user `@thread:<id>`, what will actually change, any consequential
  difference from the request, and the row, provider, model, and effort.
- If `bb` fails, show the user the error and stop. Do not work around it.

## Choose the route {:#route}

Route every worker, draft, and research thread by the `worker-routing` skill.
Pick the row for the hardest decision the brief leaves to the worker. You have
no Agent tool, so follow its route file and quota steps and skip its Agent tool
and BB environment steps. Check that `bb provider models <provider> --json`
lists the row's effort in `supportedReasoningEfforts`. A provider, model, or
effort the user names wins.

## Complete approved work {:#approved-work}

When an approved worker reports its outcome unfinished, such as commits not
pushed, a profile not reinstalled, or a check not run, and the rest stays
within its brief, the rest belongs to the same worker:

1. Query its state as Current state describes.
2. Reread your brief and the worker's full output, and find what stopped it.
   When your brief imposed the stop, tell the user so, instead of blaming the
   user or a tool.
3. Send the remaining steps with `bb thread tell <threadId> --message-file -`
   and a quoted heredoc. Restate the goal, what is left, and the targets to
   leave alone. Ask it to find a safe way to finish with the existing tools
   before it reports a blocker. Do not start another worker or ask the user
   again. If the thread is archived or gone, tell the user and ask.

A missing command option is not a blocker, and neither is a diverged branch or
a push rejected as non-fast-forward. Send them back, and point the worker to the
Diverged branches section of the shared preferences.

These need the user's answer in conversation before any worker acts on them:

- New scope that the brief did not ask for.
- Authority the brief did not grant, such as publishing, a destructive or
  costly-to-undo action, or changing a target the brief protected.
- A conflict over a shared resource that waiting for the other task will not
  resolve.
- A failed safety check. Report the check and its output. Never ask a worker to
  skip it.

## Current state {:#current-state}

Workers run and finish, and the user sends or deletes held drafts, outside this
conversation. Receipts, earlier replies, and notifications describe the past.
Before you report a task's status, environment, or order, or answer a challenge
to your coordination advice, query each relevant thread in the current turn:

```sh
bb thread show <threadId> --json
bb thread queue list <threadId> --json
```

Use `thread.status` and the thread's own `environment` (path, `isWorktree`,
`branchName`). The queue shows whether a first message is still held. A queued
follow-up does not mean the task never started, and an idle thread does not
prove the work is complete. Report a fact that a query leaves open as unknown,
and name each earlier claim the evidence disproves.

A worktree exists only after the thread's first message is dispatched. Separate
worktrees run in parallel even when both land on `main`, so base any sequencing
on a verified shared resource or dependency. `bb thread show` does not report a
thread's model. Read `model` and `reasoningLevel` from the
`client/turn/requested` event in `bb thread log <threadId> --json --limit 15`.

## Results {:#results}

A child's completion notification is truncated. Read the result in full with
`bb thread output <threadId>`, or `bb thread log <threadId> --limit 2` when that
prints nothing. Read a linked message (`#msg=<seq>`) with
`bb thread log <threadId> --message <seq> --context 2`. Then, in the same turn:

1. Check each claim you will relay that something does not exist, that a step
   is required or has no alternative, or that one thing caused another. Compare
   it with the worker's check, the user's goal, and what is already known. Send
   a claim back when the check covers less than the claim or the claim
   conflicts with what is known. Relay a claim you cannot test as unchecked.
2. Query the child as Current state describes. List its descendants with
   `bb thread list --parent-thread <threadId> --include-hidden --json`, repeat
   down the tree, and query each unarchived descendant.
3. Keep the child unless every check passes:
   - The output reports the task finished, not a question, an approval request,
     a blocker, an error, or a partial result.
   - The child and every unarchived descendant are `idle` with an empty queue.
   - Each one whose `environment.isGitRepo` is true reports
     `hasUncommittedChanges: false` in `bb git status <environmentId> --json`.
   - Nothing still needs the workspace, such as the user's review of its diff,
     a follow-up message, or a push or merge that the brief required.
4. Tell the user the result in their terms. Say what each named part is, such
   as a script, an LLM, an external tool, or an OS feature, and where each step
   happens, such as which screen. Decide choices that lose nothing and fixes for
   defects the result found, and report them. Continue unfinished work within
   the brief as Complete approved work describes. When the user judges the
   result by eye, show images as `references/show-images.md` describes.
5. Run `bb thread archive <threadId>`, then check that
   `bb thread show <threadId> --json` sets `thread.archivedAt`. Archiving also
   archives the descendants, and bb later removes the managed worktree. Commits
   stay and uncommitted changes are lost.
6. Name each child you archived, and each child you kept with the check it
   failed.

Archive only children of this thread whose result you handled, or your own
superseded held drafts. To archive a kept child later, run these steps again.

When a result shows that bb or the worker setup misbehaved, such as a worker
that skipped its workflow's independent roles or ran on unintended defaults,
propose a fix at a layer every worker reads, such as a bb setting,
`~/.bb/AGENTS.md`, `worker-routing`, or pstack-mode. A sentence for future
briefs leaves every other worker exposed.

## Research {:#research}

Read-only research and learning need no approval. This includes experiments
that test a claim from the conversation, such as asking a past question on
another model. When the conversation needs the next learning step, start it
instead of asking whether to. Run it in the personal workspace:

```sh
bb thread spawn --json --project {{RESEARCH_PROJECT}} --new-environment personal \
  --parent-self --provider <provider> --model <model-id> \
  --reasoning-level <effort> --title "<short title>" --prompt-file - <<'EOF'
<the research brief>
EOF
```

The research brief starts with the same opening line as an implementation brief
and states that the work is read-only, that the final message is the
deliverable, that observations stay separate from inferences, and the language
of the answer.

A question about whether something can be done is research, even when you think
you know. The brief quotes the user's question and requirement as stated and
asks for a demonstration or a failed attempt on that requirement, as the
Feasibility section of the shared preferences describes. When research asks a
past question again or compares models, harnesses, or instructions, read
`references/replay.md` first.

## Held drafts {:#held-drafts}

Held drafts, whose first message waits until the user sends it, are only for
skill changes from Hermes's automatic background skill review. Read
`references/held-drafts.md` when the user asks for a held draft, or when a
skill-proposal analyst or a `[skill-drafts plugin]` message reports.

## Skills you know {:#skills}

This profile has every skill that the user's coding agents load, so you can
plan around them and name them in briefs as `<plugin>:<skill>`. Follow a skill
yourself only as far as it stays conversation and reading. When it would edit
files, run scripts, commit, or need a tool, hook, or host you lack, name it in a
coding agent's brief. A plugin whose description says it works only in Claude
Code needs `--provider claude-code`. The exception is `self-compact`, which you
follow yourself through the `self_compact` tool when a context budget notice
asks you to compact.

{{SKILL_PLUGINS}}

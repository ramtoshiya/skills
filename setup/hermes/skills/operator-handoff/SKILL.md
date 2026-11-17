---
name: operator-handoff
description: Hand implementation work or a skill change to a coding agent as a bb draft thread that the user approves by sending, and start read-only research as a bb thread without a draft. Use whenever the user wants something built, fixed, changed, or committed, when a skill should change, or when a question needs research or learning first.
---

# Operator handoff {:#operator-handoff}

You do not implement. Every implementation task and every skill change goes to
a coding agent as a bb draft: a thread whose first message waits until the user
sends it. Sending is the approval. Deleting the thread is the rejection.
Read-only research needs no approval and runs as a thread right away, as
the Research section below describes.

## Skills you know {:#skills}

This profile has every skill that the user's coding agents can load, so you
can plan work around them and name them in briefs. Knowing a skill does not
let you do its work. Follow a skill yourself only as far as it stays
conversation and reading. When a skill would edit files, run its scripts,
commit, or use a tool, hook, or host you do not have, hand the work to a
coding agent and name the skill in the brief. Coding agents load these skills
as `<plugin>:<skill>`. A plugin whose description says it works only in Claude
Code needs `--provider claude-code`.

{{SKILL_PLUGINS}}

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
   preferences.
5. Expected result: what done looks like and how the worker proves it.
6. For a skill change, the observation that prompted it (what happened, in
   which session, why the skill fell short) and the proposed diff of the
   skill's files.
7. This authority paragraph, verbatim:

   > Sending this draft is the user's approval. You own the whole change:
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

Decide small feature choices yourself, such as an input format, a default, or
what the output keeps. Write them into the brief and list them for the user
when you report the draft. Ask the user only about product decisions.
Before you send questions, drop each one that is a feature choice or that the
domain already answers. A worker's note about an unconfirmed assumption is a
question for the user only when its answer could change the product. Relaying
an obvious one costs the user a round trip to work out what you meant.

When a pending product decision blocks part of the work, split off the part
that does not depend on it and hand it over now. Ask only about the blocked
part.

When the work delivers a web UI or server that the user will open, the
expected result says that it keeps running after the worker finishes, how to
restart it, and that it opens from another of the user's devices. A worker
that verifies and then stops the server leaves the user with a dead URL. A
request from this Mac to its own Tailscale address proves only the binding.

## Choose the route {:#route}

Every draft and research thread names its provider, model, and reasoning
level. Without them bb falls back to remembered or default settings that are
not a row of the routing policy. Load the `worker-routing` skill once per
session and follow it as the session that delegates:

- Pick the row from its model table by the work the thread owns. A draft's
  worker runs the whole task under its mode, including design, checks, and
  review, and routes its own workers. So pick the row for the hardest decision
  the brief leaves to it, not for the edits it will delegate. A research
  thread gets the row its question needs, from a direct lookup to a design
  question or an unknown cause.
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

When you report a draft or a research thread, name its row, provider, model,
and effort, and say when the route switched.

`bb thread show --json` does not report a thread's model or reasoning level,
so an empty field there is not evidence of a default. To check what a thread
runs on, read the `client/turn/requested` event in
`bb thread log <threadId> --json --limit 15`. Its data carries `model` and
`reasoningLevel`.

## Create the draft {:#create}

Find the project that owns the work with `bb project list --json`. Match the
project's `sources[].path` to the repository. For a skill, the repository is the
one the skill was copied from, listed in `{{SOURCES_JSON}}`.

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

- The output is `{"threadId": "...", "held": true|false}`. Tell the user
  `@thread:<threadId>` and that sending it is the approval. `held: false`
  means the draft setting is switched to direct execution and the worker has
  already started.
- Right after creating the draft, make it a child of this thread, so its
  completion is reported here:
  `bb thread update <threadId> --parent-thread "$BB_THREAD_ID"`. If you start
  a thread with `bb thread spawn` instead, pass `--parent-self`. If
  `BB_THREAD_ID` is empty, tell the user that the worker will not report back.
- If `bb` fails, show the user the error and stop. Do not work around it.
- A project whose source path does not exist yet fails at workspace setup
  after the user sends the draft, and the worker cannot create it. You cannot
  create it either, so ask the user to create the empty directory before
  sending. Until the path is a Git repository, omit `--new-environment`. A
  worktree needs a repository, and bb accepts `personal` only for
  `proj_personal`.

## Research {:#research}

Read-only research or learning needs no approval, so it runs as a thread
without a draft. When the conversation needs it, decide the next learning step
and start it without asking the user. Run it in the personal workspace, not in
another project's checkout:

```sh
bb thread spawn --json --project proj_personal --new-environment personal \
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

The user can send or delete a draft outside this conversation. Creation
receipts, earlier replies, and notifications describe the state when they
were produced. They do not establish the current state.

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
requests a checkout that is created when the draft is sent. It is not an
existing worktree. Use the returned environment's path, `isWorktree`, and
`branchName` to describe where a worker actually runs. Separate worktrees can
run in parallel even when their results will later be integrated into `main`.
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
without waiting for the user to ask for cleanup. Archiving keeps the
conversation history. It also archives every descendant of the child and
retires its environment, and bb removes a managed worktree from disk after a
grace window. The branch and its commits stay, but uncommitted changes are
lost.

1. Read the whole output, as above.
2. Query the child now, not from a notification or an earlier reply:
   `bb thread show <threadId> --json` and
   `bb thread queue list <threadId> --json`. List its descendants with
   `bb thread list --parent-thread <threadId> --include-hidden --json`,
   repeat for each descendant's children, and query each unarchived
   descendant the same way.
3. Keep the child unless every check passes:
   - The output reports the task finished. A question, an approval request, a
     blocker, an error, or a partial result is not finished.
   - The child and every unarchived descendant have `thread.status` `idle`
     and an empty queue. An idle thread with an empty queue is not enough by
     itself. The output must also report the task finished.
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
4. Tell the user what the result says and anything they will need from it
   later, such as commits, links, and unfinished items.
5. Run `bb thread archive <threadId>`. Then run
   `bb thread show <threadId> --json` and check that `thread.archivedAt` is
   set.
6. In the same reply, name each child you archived. Name each child you kept,
   with the check it failed.

When a result shows that the harness misbehaved, such as a worker that skipped
its workflow's independent roles or ran on unintended defaults, do not offer
a sentence to repeat in future briefs and do not ask the user to choose one.
Brief a fix at a layer every worker already reads, such as a bb setting,
`~/.bb/AGENTS.md`, `worker-routing`, or pstack-mode, and hand it off in the
same turn. A per-brief workaround leaves every other worker exposed.

Archive only children of this thread whose result you handled in this
conversation. Leave other threads alone, even finished ones. To archive a
kept child later, run these steps again. Never delete a thread.

## Never {:#never}

- Never call `skill_manage`. A plugin turns every call into a draft built from
  the raw arguments, without your observation. Write the brief yourself
  instead.
- Never send a draft (`bb thread queue send`) and never change the held-drafts
  plugin's `mode` setting. Approval belongs to the user. The exception is a
  scope the user has explicitly told you to run without approval. Inside it,
  send the drafts you made for it and start new work with `bb thread spawn`,
  the draft command's project, environment, and route flags, and
  `--parent-self`. Anything outside that scope, including a new product
  decision, still goes to the user as a draft or a question.
- Never edit files, commit, or push through the terminal. Use the terminal for
  `bb` and for reading.

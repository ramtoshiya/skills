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

## Create the draft {:#create}

Find the project that owns the work with `bb project list --json`. Match the
project's `sources[].path` to the repository. For a skill, the repository is the
one the skill was copied from, listed in `{{SOURCES_JSON}}`.

```sh
read -r -d '' brief <<'EOF'
<the complete brief>
EOF
bb draft create --json --project <project-id> --new-environment worktree \
  --provider claude-code --title "<short title>" --prompt "$brief"
```

`bb draft create` has no `--prompt-file`. Keep the heredoc out of `$(...)`,
because macOS `/bin/bash` 3.2 fails with "unexpected EOF" there when the brief
contains an apostrophe.

- Use `--provider codex` when the user asks for Codex. Omit `--model` unless
  the user names one.
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

## Research {:#research}

Read-only research or learning needs no approval, so it runs as a thread
without a draft. When the conversation needs it, decide the next learning step
and start it without asking the user. Run it in the personal workspace, not in
another project's checkout:

```sh
bb thread spawn --json --project proj_personal --new-environment personal \
  --parent-self --provider claude-code --title "<short title>" --prompt-file - <<'EOF'
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
   - For the child and each descendant whose `environment.managed` is true,
     `bb git status <environmentId> --json` reports
     `hasUncommittedChanges: false`.
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

Archive only children of this thread whose result you handled in this
conversation. Leave other threads alone, even finished ones. To archive a
kept child later, run these steps again. Never delete a thread.

## Never {:#never}

- Never call `skill_manage`. A plugin turns every call into a draft built from
  the raw arguments, without your observation. Write the brief yourself
  instead.
- Never send a draft (`bb thread queue send`) and never change the held-drafts
  plugin's `mode` setting. Approval belongs to the user.
- Never edit files, commit, or push through the terminal. Use the terminal for
  `bb` and for reading.

---
name: self-compact
description: >-
  Compact this conversation at a boundary you choose and resume without the user. Use when a
  "Context budget" notice says to compact, or when the user asks you to compact yourself and keep
  working. Covers Claude Code in BB and Paseo.
---

# Self-compact

Claude Code compacts on its own when the context nears its window, often in the
middle of a step. This skill compacts earlier, at a point you choose, and carries the task across the
compaction in a handoff note.

## Pick the boundary {:#boundary}

- Finish the step in progress first: the edit, the test run, the commit. Never compact with a file
  half edited or a command whose result you have not read.
- If the task will be done within a few more tool calls, finish it instead of compacting.
- Do not wait for a perfect moment. Each later warning means less room before automatic compaction.

## Write the handoff note {:#handoff}

Write the note to the path the budget warning names. Without a
warning, create a file with `mktemp -t handoff`. Never put it inside a repository. Overwrite an
older note rather than append.

The note is the only reliable state after compaction, so write it for a reader who saw nothing:

- The goal and the check that proves it is done.
- The user's instructions and constraints that still apply, quoted when wording matters.
- What is done, with commit hashes and files changed.
- The exact next step, then the remaining steps.
- Decisions already made and why, so they are not reopened.
- Open questions for the user, and anything you must not do.

## Compact and resume {:#compact}

When `BB_THREAD_ID` is set, use the BB section. Otherwise, when
`PASEO_AGENT_ID` is set, read [references/paseo.md](references/paseo.md) and follow it. Otherwise,
use the Other hosts section.

### BB with Claude Code {:#bb}

When `BB_THREAD_ID` is set, use the bundled helper. It requires `node` and the installed `bb`
CLI, and supports BB's `claude-code` provider. It does not install dependencies or change BB
settings. Other providers use the fallback below.

Give this helper exclusive control of the thread until it finishes. Do not launch another helper
or send more prompts to this thread during that time. Other threads can keep working.
BB checks whether a thread is idle before accepting compaction, but its CLI has no atomic
send-if-unchanged operation. A prompt arriving after the final check can still race the resume.

First, prepare in a standalone foreground Bash call. Use this skill's actual directory and the
absolute handoff note path:

```sh
node "<skill-directory>/scripts/bb-compact.mjs" prepare "<handoff-note>"
```

Preparation checks the thread and note and returns `launchSeq` and `turnId`. It allows earlier
requests only if BB recorded their acceptance into this turn before the preparation command
started. Do not wrap the command in a way that hides it from the BB log.

Pass `launchSeq` and `turnId` to the background command so it can recognize this turn even if it
starts after you stop:

```sh
node "<skill-directory>/scripts/bb-compact.mjs" run "<handoff-note>" --launch-seq <launchSeq> --turn-id <turnId>
```

Launch the second command with Bash's `run_in_background: true`, `timeout: 600000`, and
completion notifications. The Bash timeout must exceed the helper's five-minute deadline.
End the turn immediately after launch with one line saying compaction is scheduled and work will
resume. Do not wait for the helper in the foreground. It is waiting for this turn to end.
If the next step needs the user's answer, add `--no-resume` and end with the question.
Use the automatic-compaction fallback if the shell cannot report background failures.

The helper targets only `BB_THREAD_ID`. It waits for the invoking turn to finish successfully,
then requests compaction with `bb thread compact`. It links the new structured compact request
to its accepted turn and requires both `thread/compacted` and a successful `turn/completed`
for that turn. A command receipt, a closed `contextCompaction` item, or an assistant summary
does not prove compaction. It sends the handoff instruction through `tell --mode queue` only
after proof and a final idle check.

Pending interactions, queued work before the request (messages that the mail plugin holds in the
inbox do not count), another request, missing proof, or failure
stop the helper and keep the note. Messages that queue while compaction runs, and turns they
start after BB records the compaction turn as completed, do not fail a proven compaction. Read the background error before deciding how to continue. Do not retry a
send automatically, because its delivery can be uncertain. A queued resume receipt reports a
late race, including its queue id, rather than confirmed delivery. Inspect that row before
retrying. With `--no-resume`, a completion notification does not authorize continuing past the
user's pending question.

### Other hosts {:#other-hosts}

Without a supported host control, keep the handoff note current and continue working. Automatic
compaction is the fallback, and the hook points you to the note after it. Use the same fallback
if scheduling compaction fails.

## After compaction {:#after}

Read the handoff note before anything else and continue from its next step without asking whether
to continue. When the task in the note is finished, delete the note.

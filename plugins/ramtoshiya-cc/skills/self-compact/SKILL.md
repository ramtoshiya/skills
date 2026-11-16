---
name: self-compact
description: >-
  Compact this Claude Code conversation at a boundary you choose and resume without the user. Use
  when a "Context budget" note from the ramtoshiya-cc hook says to compact, or when the user asks
  you to compact yourself and keep working.
---

# Self-compact

Claude Code compacts on its own when the context nears its auto-compact window, often in the middle
of a step. This skill compacts earlier, at a point you choose, and carries the task across the
compaction in a handoff note.

## Pick the boundary {:#boundary}

- Finish the step in progress first: the edit, the test run, the commit. Never compact with a file
  half edited or a command whose result you have not read.
- If the task will be done within a few more tool calls, finish it instead of compacting.
- Do not wait for a perfect moment. Each later warning means less room before automatic compaction.

## Write the handoff note {:#handoff}

Write the note to the path the budget warning names. Without a warning, create a file with
`mktemp -t handoff`. Never put it inside a repository. Overwrite an older note rather than append.

The note is the only reliable state after compaction, so write it for a reader who saw nothing:

- The goal and the check that proves it is done.
- The user's instructions and constraints that still apply, quoted when wording matters.
- What is done, with commit hashes and files changed.
- The exact next step, then the remaining steps.
- Decisions already made and why, so they are not reopened.
- Open questions for the user, and anything you must not do.

## Compact and resume {:#compact}

When `BB_THREAD_ID` is set, use the BB section below. Otherwise, when `PASEO_AGENT_ID` is set,
use the Paseo section. Otherwise, in T3 Code
(`printenv T3CODE_THREAD_ID` prints a thread id), queue two
messages to your own thread with `t3_thread_send`, mode `queue`, in this order:

1. `/compact Keep the goal, the user's constraints, and the path of the handoff note <path>.`
2. `Resume after self-compaction: read <path> and continue the task from its next step.`

T3 Code passes the first message to Claude Code as the `/compact` command and starts the second as
a new turn after it. Check that both sends return `"status":"queued"`, then end your turn with one
line telling the user that you queued compaction and will resume. Do nothing else in that turn.

If the next step needs the user's answer, queue only the `/compact` message and end the turn with
the question, so the resume does not run ahead of the user.

### BB with Claude Code {:#bb}

When `BB_THREAD_ID` is set, use the bundled helper. It requires `node` and the installed `bb`
CLI, and supports BB's `claude-code` provider. It does not install dependencies or change BB
settings. Other providers use the fallback below.

Give this helper exclusive control of the thread until it finishes. Do not launch another helper
or send more prompts to this thread during that time. Other threads can keep working.
BB checks whether a thread is idle before accepting compaction, but its CLI has no atomic
send-if-unchanged operation. A prompt arriving after the final check can still race the resume.

First, prepare in the foreground. Use this skill's actual directory and the absolute handoff
note path:

```sh
node "<skill-directory>/scripts/bb-compact.mjs" prepare "<handoff-note>"
```

Preparation checks the thread and note and returns `launchSeq` and `turnId`. Pass those values
to the background command so it can recognize this turn even if it starts after you stop:

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

Pending interactions, queued work, another request, missing proof, or failure stop the helper
and keep the note. Read the background error before deciding how to continue. Do not retry a
send automatically, because its delivery can be uncertain. A queued resume receipt reports a
late race, including its queue id, rather than confirmed delivery. Inspect that row before
retrying. With `--no-resume`, a completion notification does not authorize continuing past the
user's pending question.

### Paseo Desktop on macOS {:#paseo}

When `PASEO_AGENT_ID` is set and `BB_THREAD_ID` is unset, use the bundled helper instead of the T3
thread tool. It requires an installed macOS Paseo Desktop bundle and a provider that advertises
`/compact`. Set
`PASEO_DESKTOP_APP` if the bundle is not at `/Applications/Paseo.app`. It uses the installed
bundle's SDK and runtime without installing dependencies. Standalone and remote daemons are
not supported by this helper.

This is an exclusive-session proof of concept. Do not use it while another controller or worker
can send prompts to this agent. Paseo has no atomic send-only-if-idle operation, so an incoming
prompt between the idle check and a send could be interrupted. Do not send more work until the
helper finishes. Other agents can continue their own work.

Launch this command with the shell tool's background execution option and completion
notifications, using this skill's actual directory for `<skill-directory>` and the absolute
handoff note path. If the shell tool cannot notify you when background work fails, use the
automatic-compaction fallback instead:

```sh
sh "<skill-directory>/scripts/paseo-compact.sh" "<handoff-note>"
```

The helper waits up to five minutes for your current turn to finish. End the turn immediately
after launch with one line saying compaction is scheduled and work will resume. Do not wait for
the helper in the foreground, because it is waiting for you to stop. If the next step needs the
user's answer, add `--no-resume` and end with the question instead.

The helper sends `/compact` as a native provider command, waits for a new completed compaction
event, then sends the resume instruction. Ordinary agent-originated `paseo send` and
`send_agent_prompt` wrap the text as an agent message, so they do not execute `/compact`.
A delivery receipt or an assistant's summary is not proof of compaction. Helper failure keeps
the note and does not send a resume instruction. Read the error before retrying.

### Other hosts {:#other-hosts}

Without a supported host control, keep the handoff note current and continue working. Automatic
compaction is the fallback, and the hook points you to the note after it. Use the same fallback
if scheduling compaction fails.

## After compaction {:#after}

Read the handoff note before anything else and continue from its next step without asking whether
to continue. When the task in the note is finished, delete the note.

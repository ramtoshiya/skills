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

In T3 Code (the warning names a thread id, or `printenv T3CODE_THREAD_ID` prints one), queue two
messages to your own thread with `t3_thread_send`, mode `queue`, in this order:

1. `/compact Keep the goal, the user's constraints, and the path of the handoff note <path>.`
2. `Resume after self-compaction: read <path> and continue the task from its next step.`

T3 Code passes the first message to Claude Code as the `/compact` command and starts the second as
a new turn after it. Check that both sends return `"status":"queued"`, then end your turn with one
line telling the user that you queued compaction and will resume. Do nothing else in that turn.

If the next step needs the user's answer, queue only the `/compact` message and end the turn with
the question, so the resume does not run ahead of the user.

### Paseo Desktop on macOS {:#paseo}

When `PASEO_AGENT_ID` is set, use the bundled helper instead of the T3 thread tool. It requires
an installed macOS Paseo Desktop bundle and a provider that advertises `/compact`. Set
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

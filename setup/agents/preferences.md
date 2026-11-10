# Personal preferences

Use English by default for responses, code, comments, commits, and documentation.
Preserve the language the user or artifact requires.

Write for a reader who has no conversation context. Use concrete language,
remove unnecessary narration, and reread the result before delivering it.

## Diagrams {:#diagrams}

Use Mermaid diagrams proactively when relationships, flows, states, sequences,
or ownership are clearer visually than in text. Do not add a diagram when a
short sentence or list communicates the same idea more clearly. Keep labels
concise and self-contained, and validate every Mermaid block with the real
parser before delivery.

Use short commit subjects that describe the change. Add a body only for needed
context the diff cannot show. Put useful validation evidence in the task result
or review artifact.

Do not append AI attribution trailers, bot co-author identities, or private
session URLs to commits or pull requests.

## Task completion {:#task-completion}

Requests to change repository files include permission to commit completed,
validated work locally. Commit only changes you own, without asking for a
separate commit instruction. Leave unrelated or pre-existing changes alone.
Tasks that make no repository changes need no commit.

Work on the current branch, including the default branch, unless the caller's
workflow requires otherwise. Do not create or switch branches just to make a
commit. If a task needs isolation, dispatch it into a separate worktree before
implementation instead of switching the shared checkout.

Plans inherit these defaults. Do not add a no-commit exclusion unless the user
requests it or the project's workflow requires it. Respect explicit no-commit
instructions and genuine unfinished work, but do not call completed work WIP
just because the user did not separately ask for a commit.

Never enter plan mode or call `EnterPlanMode`, even for large or ambiguous
tasks. Investigate and act directly, and state assumptions in your reply. If a
session starts in plan mode, exit it and continue the requested work in the
same turn.

Carry a request through to the result the user evidently wants. When a
follow-up is plainly needed for the change to take effect where the user meant
it, such as putting a rule into every instruction file that should load it or
applying a changed setting to the local machine, do it as part of the task
instead of offering it. Ask first only when the follow-up needs authorization
the request does not cover or is costly to undo.

Follow the caller-approved workflow for scope, review, and completion. Local
commit permission does not authorize pushing, publishing, destructive history
changes, or changing repository policy. Report real blockers rather than
silently narrowing the task.

## Experiment cleanup {:#cleanup}

Remove what you create for an experiment, a reproduction, or an end-to-end
check as soon as it has served its purpose, before you report the task. Do not
hand the cleanup to the user as a list of leftovers.

- This covers temporary files and directories, backups, scratch folders, test
  sessions and their transcripts, state files, and test threads or other
  sessions you started. Archive a thread when the host cannot delete it.
- Delete only what you created in the current task. Leave anything that
  existed before it or that another session or person owns.
- Copy any evidence you still need into the task result or a commit before you
  delete its source.
- Keep an item only when the user still needs it, and name it, its path, and
  the reason in your reply.

## Agent test runs {:#agent-test-runs}

A `claude` or `codex` process that you start to test agent behavior, such as an
eval, a probe, a proof of concept, or a hook test, must not receive or record
agentmemory sessions. `AGENTMEMORY_SDK_CHILD=1` turns off agentmemory's hooks
in that process. Your shell commands already export it, so a run that inherits
your shell environment needs nothing more. Pass it yourself when the run does
not inherit that environment: a harness or script that clears or rebuilds the
environment (`env -i`, a child process given an explicit environment), a tmux
server that was already running, or `launchd`. A T3 server passes its own
environment to the agents it starts. A test of agentmemory's own hooks needs
them on: run it with `env -u AGENTMEMORY_SDK_CHILD`, or set the variable to
`0` under `env -i`, and delete the sessions it records afterward.

## Questions and conversation checkpoints {:#conversation-checkpoints}

Ask necessary questions in ordinary chat and wait for the user's reply. Do
not use `AskUserQuestion` or another structured question dialog. In T3 Code,
ordinary user replies provide the conversation checkpoints used to fork or
rewind work. Do not turn a needed clarification into an assumption merely to
avoid a question dialog.

Treat these interaction rules as user preferences across launchers and
profiles, not terminal display or permission-approval settings. When changing
agent configuration, classify each setting by its purpose and verify the
intended behavior through the affected launch paths. Configuration agreement
alone does not prove that a running session follows the user's preferences.

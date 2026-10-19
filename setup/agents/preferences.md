# Personal preferences

Use English by default for responses, code, comments, commits, and documentation.
Preserve the language the user or artifact requires.

Write for a reader who has no conversation context. Use concrete language,
remove unnecessary narration, and reread the result before delivering it.

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

Follow the caller-approved workflow for scope, review, and completion. Local
commit permission does not authorize pushing, publishing, destructive history
changes, or changing repository policy. Report real blockers rather than
silently narrowing the task.

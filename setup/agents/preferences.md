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

Follow the caller-approved workflow for scope, review, and completion. Local
commit permission does not authorize pushing, publishing, destructive history
changes, or changing repository policy. Report real blockers rather than
silently narrowing the task.

## Shared memory {:#shared-memory}

When the `mem0-local` MCP server is available, search for relevant memory before
starting a coding task. Pass the current absolute project path. Verify recalled
claims against the repository and current instructions before acting on them.

Save durable, verified decisions, constraints, conventions, and proven fixes
when they would help a later session. Use project scope for repository knowledge
and personal scope for preferences that apply across projects. Never store
credentials, full transcripts, temporary plans, or unverified claims. Delete a
memory when the user asks to forget it.

If local memory is unavailable, continue the task and report the limitation
briefly. Do not treat a memory failure as a reason to stop unrelated work.

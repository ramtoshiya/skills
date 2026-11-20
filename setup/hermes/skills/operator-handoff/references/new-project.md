# New project path {:#new-project}

Read this when the project that owns the work has a source path that does not
exist yet. Start the worker in `SKILL.md` gives the command.

A project whose source path does not exist yet fails at workspace setup,
and the worker cannot create it. You cannot create it either, so ask the
user to create the empty directory and start the worker after that. Until
the path is a Git repository, omit `--new-environment`. A worktree needs a
repository, and bb accepts `personal` only for `proj_personal`.

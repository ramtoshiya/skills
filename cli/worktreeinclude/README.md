# worktreeinclude

Copy selected ignored local files from a repository's main checkout into a newly
created linked worktree. For example, `git worktree add ../feature` can populate
`.env` and local settings without committing them or sharing them through symlinks.
Existing differing files stay untouched and produce a conflict.

## Install

Install [Node.js](https://nodejs.org/en/download) 22.19 or newer and Git, then run
from this repository:

```sh
sh cli/worktreeinclude/install.sh
```

The installer copies the dependency-free command to `~/.local/bin/worktreeinclude`.
Put that directory on `PATH`. It refuses to replace an unrelated command. Installing
the command does not change any repository's hooks.

## Choose files

In the main checkout of the repository that needs local files, create and commit
`.worktreeinclude`:

```gitignore
.env
.claude/settings.local.json
local settings/
*.private
!unused.private
```

Git evaluates this file using its ignore-pattern engine, including comments,
negation, `*`, `**`, `?`, and character classes. Only paths also ignored by the
source repository's actual ignore rules are eligible. A selected tracked source
path is an error, even when it also matches an ignore rule. Target index entries
are protected too, including tracked files missing from disk.

Patterns are relative to the main checkout. For safety, absolute paths (including
leading `/` anchors), backslashes, `..` components, and `.git` components are
rejected. Spaces and Unicode need no quoting. As with Git ignore files, trailing
spaces have Git's normal meaning. Symlink paths and symlink ancestors are rejected,
not followed or copied. Nested repositories and nested worktrees are skipped.
The source manifest itself must be a tracked regular file.

## Manage hooks explicitly

From any checkout in that repository:

```sh
worktreeinclude hook install
worktreeinclude hook status
git worktree add ../feature -b feature
worktreeinclude hook uninstall
```

Repeated install and uninstall are safe. Installation stores an executable snapshot
in the shared Git common directory's `worktreeinclude/` directory and sets the
repository-local `core.hooksPath` to its managed dispatchers. Every linked worktree
uses the same integration. No existing hook is moved or edited.

The dispatcher runs the original hook at its original path, with its original
arguments, working directory, environment, and interpreter. It forwards Git's
standard hooks and additional hook names present at installation. Relative
`core.hooksPath` values remain relative to each hook's working directory. Existing
hooks can use `exit`, `exec`, and non-shell interpreters. The copier still runs if
the original `post-checkout` fails. The dispatcher returns failure if either fails,
preserving the original hook's nonzero status when both fail.

Uninstall restores the previous repository-local setting, or removes this tool's
local override so inherited configuration becomes effective again. Original hooks
remain untouched. Externally changed dispatchers, extra integration files, changed
hook configuration, and per-worktree Git configuration cause a safe refusal rather
than a guessed cleanup. Do not edit the managed directory. To update its executable
snapshot, uninstall, update the command, and install again. The snapshot records
the current Node executable's absolute path. Reinstall if an upgrade removes that
executable. Newly introduced Git hook names also require reinstalling.

The CLI is not an agent plugin and installs no agent hooks. Its Git integration
requires explicit opt-in for each repository.

## Copy behavior and limits

`worktreeinclude apply` retries the copier from a newly created linked checkout.
Git discovers both worktrees. There is no configured source path. The main checkout
must be available, so a bare repository without a main checkout is unsupported.
The source's current local files and manifest are used, not a historical revision.

The `post-checkout` dispatcher requires Git's null-old-HEAD creation event and a
linked checkout. The CLI also checks the initial HEAD reflog, accepting only Git's
creation entry and optional initial reset. Main checkouts, later checkouts, and
checkouts with missing or changed creation reflogs are no-ops. Do not disable
reflogs if you want automatic copying. `git worktree add --no-checkout` and orphan
creation do not invoke `post-checkout`. Clone's similar hook event never copies
into the main checkout.

Missing regular files are staged beside the destination and published atomically
with a no-replace hard link, then the temporary name is removed. Source and target
files never share an inode. Directories are created as needed with private default
permissions. Existing same-content files are successful skips. Differing files and
type conflicts are reported without overwrite or deletion. A batch can copy some
files before another file fails, and retrying is safe. This also allows a copier
such as Claude Code's `.worktreeinclude` handling to run before or after this tool
when both produce the same content.

Output contains escaped paths, statuses, and counts, never file contents. A nonzero
exit reports errors or conflicts. Git's hook runs after checkout, so a failed copy
cannot undo the already created worktree. Inspect the report and resolve conflicts
manually. The CLI writes no persistent copy logs.

Git output above 64 MiB from one command produces a stderr warning that names the
Git command, the byte count, and the soft limit. Only output above 1 GiB fails.

Use trusted local checkouts. Path checks reject existing symlinks, but this
portable Node implementation does not lock out another process that maliciously
renames parent directories while copying. Do not run it against trees being
modified by an untrusted concurrent writer. Copying is not a secret-distribution
or access-control mechanism.

## Check it

From this repository:

```sh
node --check cli/worktreeinclude/worktreeinclude.mjs
sh -n cli/worktreeinclude/install.sh
node --test test/worktreeinclude.test.mjs
npm test
```

The tests install into a temporary home and exercise real repositories, hook
coexistence, linked worktree creation, source and target protection, conflict
handling, and SHA-256 repositories. There is no package build or dependency install.

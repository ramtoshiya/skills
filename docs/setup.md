# Machine setup

`mise.toml` at the repository root sets up a Mac with
[mise bootstrap](https://mise.jdx.dev/bootstrap.html). It installs three
Homebrew packages, copies shell, Git, and agent files from `setup/` into your
home directory, edits a few existing files, and adds mise's shell activation.

The values are the author's preferences. Fork the repository and change them
before you run it, and delete any entry you do not want. The agent plugins are
installed separately, as described in [Agent plugins](agent-pack.md).

## Requirements

- macOS on Apple silicon. mise skips `brew` packages on Intel Macs.
- [Homebrew](https://brew.sh), with the `brew shellenv` line its installer
  asks you to add to `~/.zprofile`. That line puts `/opt/homebrew/bin` on
  `PATH` and sets `HOMEBREW_PREFIX`, which `interactive.zsh` uses.
- [mise](https://mise.jdx.dev/installing-mise.html) and Git.

mise installs the Homebrew packages itself, into Homebrew's prefix.

Tested with mise 2026.10.10 on macOS 26.5.1.

## Run it

```sh
git clone https://github.com/<you>/skills.git
cd skills
mise trust
mise bootstrap --dry-run
mise bootstrap
mise bootstrap status --missing
```

`mise trust` is needed because `mise.toml` is a project file. The dry run lists
each file mise would write or edit. `status --missing` exits with 1 if anything
still differs from the configuration. Open a new terminal afterwards to load the
shell changes. Running `mise bootstrap` again changes only what differs.

mise does not back up the files it overwrites. Copy the files listed below
before the first run, or set up
[dotfile history](https://mise.jdx.dev/dotfiles/history.html) first.

`mise.toml` declares no tools or environment variables, so loading it inside
the checkout changes nothing else.

## What it changes

Packages, installed with mise's `brew` manager:

- `jq`, used by the Claude Code status line.
- `uv`, which runs the agent hooks.
- `zsh-autosuggestions`, loaded by `interactive.zsh`.

Shell:

| Target | Change |
| --- | --- |
| `~/.config/shell/environment.zsh` | Copy of `setup/shell/environment.zsh`. Adds `~/.local/bin` to `PATH` and sets `IMPECCABLE_NO_TELEMETRY=1`, which turns off telemetry in the [Impeccable](https://impeccable.style) design skills |
| `~/.config/shell/interactive.zsh` | Copy of `setup/shell/interactive.zsh`. Puts `~/.local/bin` first in `PATH`, sets `HOMEBREW_CLEANUP_MAX_AGE_DAYS=30` and `GPG_TTY`, and loads zsh, uv, and uvx completions and zsh-autosuggestions |
| `~/.zshenv` | A block that sources `environment.zsh` |
| `~/.zshrc` | A block that sources `interactive.zsh`, then mise's activation block |
| `~/.zprofile` | mise's shims block |

Package managers. Each one skips releases newer than three days:

| Target | Change |
| --- | --- |
| `~/.npmrc` | The line `min-release-age=3` |
| `~/Library/Preferences/pnpm/config.yaml` | `minimumReleaseAge: 4320` (minutes) |
| `~/.config/uv/uv.toml` | `exclude-newer = "3 days"` |
| `~/.config/mise/config.toml` | `minimum_release_age = "3d"` under `[settings]` |

Git:

| Target | Change |
| --- | --- |
| `~/.config/git/shared.gitconfig` | Copy of `setup/git/shared.gitconfig`: aliases, diff, merge, fetch, push, pull, and rebase preferences, `rerere`, and `core.excludesfile = ~/.gitignore` |
| `~/.gitconfig` | A block that includes `shared.gitconfig` |
| `~/.gitignore` | The lines `.DS_Store` and `**/.claude/settings.local.json` |

`shared.gitconfig` turns on `core.fsmonitor` and `core.untrackedCache`. Check
that your file system supports them with `git update-index --test-untracked-cache`
before you keep them.

Coding agents:

| Target | Change |
| --- | --- |
| `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.pi/agent/AGENTS.md` | Copies of `setup/agents/preferences.md`, the author's instructions for every agent |
| `~/.claude/settings.json` | The keys in `setup/agents/claude-settings.json` |
| `~/.claude/status-line.sh` | Copy of `setup/agents/claude-statusline.sh` |

The shared agent instructions authorize local commits of completed, validated
task-owned changes on the current branch, including the default branch. They
protect unrelated changes and respect explicit no-commit requests. Tasks that
need isolation use a separate worktree before implementation, not a branch
switch in the shared checkout. Local commit permission does not authorize
pushing, publishing, or destructive history changes.

`claude-settings.json` sets these Claude Code preferences:

- `includeGitInstructions` is false, which disables Claude Code's built-in
  commit and pull request workflow instructions. The shared agent instructions
  define the local commit workflow instead. This setting does not override
  higher-priority instructions supplied by a host or harness.
- `permissions.defaultMode` is `bypassPermissions`: Claude Code runs every tool
  without asking. Change this if you want permission prompts.
- `permissions.deny` blocks `AskUserQuestion`, so questions arrive as plain
  chat, and `SendFeedback`.
- `EnterPlanMode` is also denied, so Claude cannot enter plan mode on its own.
  You can still enter plan mode manually.
- `enableArtifact` is false, which disables the Artifact tool.
- `disableBundledSkills` is true, which removes bundled skills and workflows
  and hides built-in slash commands from the model. Built-in commands remain
  typable. Plugin skills and local skills and commands are unaffected.
- Automatic memory, prompt suggestions, away summaries, and feedback surveys
  are off.
- `attribution.commit` and `attribution.pr` are empty and
  `attribution.sessionUrl` is false, so Claude Code stops asking the model to
  add a co-author trailer, a "Generated with Claude Code" footer, or a session
  link.
- `CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL=1` stops Claude Code
  from registering the official marketplace on its own. It does not remove a
  marketplace that is already registered.
- The status line shows the model, the effort level, and context use against
  the context window size, refreshed every second. If the Orca app's status
  line hook exists at `~/.orca/agent-hooks/claude-statusline.sh`, the script
  passes its input on to it, because this `statusLine` setting replaces Orca's.
  Without Orca, that step does nothing.

## How mise applies each entry

In `mise.toml`, the key of a block, line, or merge entry is the target path
followed by an entry id, such as `shell` in `"~/.zshrc/shell"`. The id names
the edit within that file. It is not part of the path.

| Entry | Behavior |
| --- | --- |
| Copy (`mode = "copy"`) | Overwrites the target's content without asking. `mise dot diff` shows the difference first |
| Merge (`merge = true`) | Sets only the keys in the source and keeps every other key. An array, such as `permissions.deny`, is replaced as a whole. A key you delete from the source stays in the target |
| Block (`block = ...`) | Writes the text between `# >>> mise:<id> >>>` and `# <<< mise:<id> <<<` markers, appended to the file if the markers are missing |
| Line (`line = ...`) | Appends the line if that exact line is missing |

Deleting an entry from `mise.toml` leaves the file as it is.
[`mise dot unapply`](https://mise.jdx.dev/cli/dotfiles/unapply.html) removes a
block with its markers.

Target paths are fixed. If you set `CLAUDE_CONFIG_DIR`, `CODEX_HOME`,
`NPM_CONFIG_USERCONFIG`, or `XDG_CONFIG_HOME` (pnpm then reads
`$XDG_CONFIG_HOME/pnpm/config.yaml`), change the matching targets in
`mise.toml`.

## What it leaves alone

The setup does not touch Git identity, commit signing, credential helpers,
`gh` login, or SSH keys. Keep those in `~/.gitconfig`, in files it includes, or
in each tool's own login flow. It also leaves lines that other tools add to
your shell startup files, such as Homebrew's `shellenv`.

## Change a setting later

Edit the file in `setup/` or the entry in `mise.toml`, then run
`mise bootstrap` again. `mise dot apply` applies only the file entries.

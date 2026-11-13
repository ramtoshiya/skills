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
- [uv](https://docs.astral.sh/uv/getting-started/installation/) with a uv-managed
  Python 3.11 or newer. Follow uv's [Python installation instructions](https://docs.astral.sh/uv/guides/install-python/)
  before the first bootstrap. A system or Homebrew Python does not satisfy the
  managed-runtime requirement.

Check the runtime before applying setup:

```sh
uv run --offline --no-project --managed-python --python '>=3.11' --no-config --exclude-newer '3 days' python -V
```

mise installs the declared Homebrew packages into Homebrew's prefix, including
uv. It does not install the managed Python interpreter. The Claude policy task
runs offline and fails before applying that policy if the runtime is missing.
Other bootstrap resources may already have been applied at that point.

Tested with mise 2026.10.10 on macOS 26.5.1.

## Run it

```sh
git clone https://github.com/<you>/skills.git
cd skills
mise trust
mise bootstrap --dry-run
mise bootstrap
mise bootstrap status --missing
mise run agents:settings:status
```

`mise trust` is needed because `mise.toml` is a project file. The dry run lists
declared resource changes and prints the bootstrap task without running it.
`status --missing` checks bootstrap resources, not the policy applied by that
task. Use `agents:settings:status` to check Claude settings and instructions.
Open a new terminal afterwards to load the shell changes. Running
`mise bootstrap` again changes only what differs.

mise does not back up the files it overwrites. Copy the files listed below
before the first run, or set up
[dotfile history](https://mise.jdx.dev/dotfiles/history.html) first.

`mise.toml` also declares the repository's Actions analyzers. Run `mise install
--locked` to install them without applying the machine setup. Loading the
checkout puts installed tools on mise's activated `PATH` but declares no
environment variables.

## Check GitHub Actions

From the checkout, run:

```sh
mise install --locked
mise run actions:check
mise exec -- node --test dev/tests/repository/actions-checks.mjs
```

The checks use [actionlint](https://github.com/rhysd/actionlint) for workflow
syntax, schemas, and action contracts, and
[zizmor](https://docs.zizmor.sh/) for Actions security. Run them separately with
`mise run actions:syntax` and `mise run actions:security`. Both return nonzero
on findings. The focused tests exercise each task against a bad workflow and
check that its diagnostic reaches the caller. They need Node.js and Git.

The versions in `mise.toml` are exact. `mise.lock` records download URLs,
SHA-256 checksums, and provenance verification for Linux x64 (CI) and Apple
silicon macOS. Other platforms need lock entries before using `--locked`.
When updating tools or actions, verify the official release date and wait at
least 72 hours, even for an exact pin. mise's minimum-release-age setting does
not filter exact versions. Refresh the lock with `mise lock --platform
linux-x64,macos-arm64`, then rerun the checks and tests.

`actionlint` releases less frequently than the Actions ecosystem changes.
Passing it does not prove that an action is current, supported, or secure.
Check releases and advisories in the original repositories when updating
SHA pins, and keep version comments beside each `uses:` entry.

The security task runs zizmor offline, removes GitHub token variables and
`RUST_LOG`, and uses no verbose or debug logging. It does not perform online
advisory or repository audits. Review advisories separately when updating
pins. Do not use zizmor 1.27.0, whose debug logs can expose credentials
([GHSA-f42p-wjw5-97qh](https://github.com/zizmorcore/zizmor/security/advisories/GHSA-f42p-wjw5-97qh),
fixed in 1.28.0).

`.github/workflows/actions-check.yml` runs the same checks for pushes and pull
requests with read-only permissions. It uses a SHA-pinned mise action, an
exact mise release, and locked tool downloads, without applying dotfiles or
Homebrew setup. Its security step runs even if the syntax check fails.
The upstream fork drift workflow keeps issue-write permission only for its
existing reporting job. Checkout does not persist credentials, and setup-node's
automatic package-manager cache is disabled there.

## What it changes

Packages, installed with mise's `brew` manager:

- `jq`, used by the Claude Code status line.
- `uv`, which runs the agent hooks and the review launcher.
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

Agents:

| Target | Change |
| --- | --- |
| Registered Claude profiles' `CLAUDE.md` | A managed block from `setup/agents/preferences.md`, preserving text outside the block |
| `~/.codex/AGENTS.md` | A copy of `setup/agents/preferences.md` |
| Registered Claude profiles' `settings.json` | Common keys from `setup/agents/claude-settings.json`, with terminal defaults from `setup/agents/claude-terminal-settings.json` only for `~/.claude` |
| `~/.codex/config.toml` | `AGENTMEMORY_SDK_CHILD = "1"` under `[shell_environment_policy.set]`, from `setup/agents/codex-config.toml`. Commands that Codex runs get the variable, so a `claude` or `codex` test run started from them stays out of agentmemory. Codex hooks do not get it, so your own Codex sessions keep their memory |
| `~/.claude/status-line.sh` | Copy of `setup/agents/claude-statusline.sh` |
| `~/.local/bin/claude-review` | Copy of `setup/agents/claude-review`, an executable shell script that starts the review launcher |
| `~/.local/share/claude-review/claude-review.py` | Copy of `setup/agents/claude-review.py`, the review launcher and its hook handler |
| `~/.local/bin/quotio-cli` | Copy of `setup/agents/quotio-cli`, an executable shell script that runs the command-line helper inside the [Quotio](https://github.com/nguyenphutrong/quotio) app from `/Applications`. The `lead` skill reads weekly quota through it. Setup does not install Quotio, and without it the script exits with an error |

The managed plugin synchronization workflow reads host selections from
`setup/agents/hosts.json`. Both humanizers are paused on Claude Code and
selected together on Codex so Korean delegation has an installed target. Add
`claude` back to both entries and run the sync to resume them. This policy file
does not install plugins during `mise bootstrap`.

The shared instructions distinguish missing configuration and invalid or incompatible
tools from an absent installation. They direct agents to inspect documented trusted
locations and report unresolved searches before concluding a prerequisite is missing.

The coding-agent instructions authorize local commits of completed, validated
task-owned changes on the current branch, including the default branch. They
protect unrelated changes and respect explicit no-commit requests. Tasks that
need isolation use a separate worktree before implementation, not a branch
switch in the shared checkout. Local commit permission does not authorize
pushing, publishing, or destructive history changes. The instructions also require
completing necessary authorized follow-up steps and removing task-owned experiments,
including temporary files and test sessions, before reporting completion.

`claude-settings.json` sets these Claude Code preferences:

- `includeGitInstructions` is false, which disables Claude Code's built-in
  commit and pull request workflow instructions. The shared agent instructions
  define the local commit workflow instead. This setting does not override
  higher-priority instructions supplied by a host or harness.
- `enableArtifact` is false, which disables the Artifact tool.
- `disableBundledSkills` is true, which removes bundled skills and workflows
  and hides built-in slash commands from the model. Built-in commands remain
  typable. Plugin skills and local skills and commands are unaffected.
- `syncClaudeAiSkills` is false, which stops syncing and loading standalone
  claude.ai skills such as `pptx`, `xlsx`, and `google-workspace`. On the next
  startup, Claude Code moves previously synced copies from `~/.claude/skills/synced/`
  to `~/.claude/skills/.trash/`. This preference must be applied to user settings.
  Claude Code does not read it from the project's `.claude/settings.json`.
- `syncClaudeAiPlugins` is false, which separately stops syncing and loading
  plugins from the claude.ai account. On the next startup, Claude Code moves
  previously synced copies to `~/.claude/plugins/.trash/`.
  Marketplace plugins and local skills are unaffected by either setting.
  Neither setting removes anything from the claude.ai account. See the
  [plugin loading reference](https://code.claude.com/docs/en/plugins/loading.md).
- Automatic memory, prompt suggestions, away summaries, and feedback surveys
  are off.
- `attribution.commit` and `attribution.pr` are empty and
  `attribution.sessionUrl` is false, so Claude Code stops asking the model to
  add a co-author trailer, a "Generated with Claude Code" footer, or a session
  link.
- `autoCompactWindow` is 300000, so Claude Code compacts the conversation on
  its own as it nears 300,000 tokens. The context budget hook in
  `ramtoshiya-cc` reads this number and asks the agent to compact earlier, from
  75% of it. See [Hooks](hooks.md).
- `CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL=1` stops Claude Code
  from registering the official marketplace on its own. It does not remove a
  marketplace that is already registered.
- `permissions.deny` includes `AskUserQuestion`, `EnterPlanMode`, and
  `SendFeedback` in every registered Claude profile. Necessary questions stay
  in ordinary chat, where the user's reply can serve as a fork or rewind
  checkpoint in T3 Code. This is an interaction preference, not a terminal
  permission-approval mode. Shared instructions also require leaving plan mode
  if a session starts there. Preserving an existing profile permission field
  does not override those instructions.
- `permissions.deny` also includes `EnterWorktree` in every registered Claude
  profile. This blocks entry through Claude Code's tool, which activates its
  worktree isolation guard and restricts commands against other checkouts.
  Use `git worktree` or the host's worktree features when isolation is needed.
  Those paths are not blocked by this rule.

`claude-terminal-settings.json` applies only to `~/.claude`:

- `permissions.defaultMode` is `bypassPermissions`, which skips permission
  prompts. Change this if you want prompts.
- The status line shows the model, effort, and context use, refreshed every
  second. If `~/.orca/agent-hooks/claude-statusline.sh` exists, it also receives
  the input. Otherwise that step does nothing.

## Keep Claude profiles consistent

Use the ordinary `~/.claude` configuration for terminal and hosted Claude Code
sessions when they should share preferences and plugins. For GPT routing through
[claudex](../tools/claudex/README.md), select that executable in the host. It
sets the provider and models for each launch without a separate Claude
configuration directory.

In T3 Code, set the Claude provider's `Binary path` to `claudex` or its full
installed path. Set `CLAUDE_CONFIG_DIR path` to the absolute path of your
`~/.claude` directory when you need to override an inherited value. Leaving
that path blank inherits the host environment and does not prove the default
directory is in use.

An intentionally isolated instance can use a separate `CLAUDE_CONFIG_DIR`,
which has its own user settings and does not inherit `~/.claude/settings.json`.
Register such directories to reconcile their common settings:

```sh
mise run agents:settings:status
mise run agents:settings:sync
mise run agents:settings:status
```

These tasks check or apply settings and common instructions without running
plugin commands or model requests. They always include `~/.claude`, regardless
of the caller's `CLAUDE_CONFIG_DIR`. The ordinary `agents:status` and
`agents:sync` tasks also include these checks when Claude is selected, unless
`--plugin` limits the command to packages. Use `--json` for machine-readable
results. Each profile has separate settings and instructions results.

`mise bootstrap` runs `agents:settings:sync` through its bootstrap task, after
dotfiles and tools. All Claude policy writes therefore use the same registry,
overrides, and merge rules. There are no separate Claude settings merges or
instruction copies in `[dotfiles]`. `mise dot apply`, `mise bootstrap status`,
and `mise bootstrap --dry-run` do not execute the policy task.

Keep the target list in
`~/.config/ramtoshiya/claude-profiles.json`, or
`$XDG_CONFIG_HOME/ramtoshiya/claude-profiles.json`:

```json
{
  "version": 1,
  "profiles": {
    "isolated": {
      "configDir": "~/.claude_isolated"
    },
    "worker": {
      "configDir": "~/.claude_worker",
      "overrides": {
        "env": {
          "AGENTMEMORY_SDK_CHILD": "1"
        }
      }
    }
  }
}
```

Names are labels. Each entry needs an absolute path or a `~/` path. Two entries
cannot name the same resolved directory. An entry naming `~/.claude` still gets
its terminal defaults. `overrides` records intentional differences after the
common settings and terminal defaults. The checker reports override key names
so an exception does not look like common-policy coverage. Keep this registry
outside the repository and keep credentials in the provider's own settings.
The registry controls settings reconciliation only. It does not select a
launcher or install plugins into registered directories.

Only settings named by the common source, terminal defaults, or an explicit
override are managed. Nested objects keep unrelated keys. Required array entries
are added without removing existing entries, so an override can add deny rules
but cannot remove common ones. Authentication, provider routing, plugins, hooks,
and permission keys outside the managed policy are left alone unless explicitly
included in an override. Terminal approval mode and status-line defaults are
not copied to alternate profiles. Correct files are not rewritten. A setting
removed from a source is no longer managed, but is not deleted from existing
targets.

The same profile inventory supplies `setup/agents/preferences.md` to each
profile's `CLAUDE.md`, between `<!-- BEGIN ramtoshiya:preferences -->` and
`<!-- END ramtoshiya:preferences -->`. Sync adds or updates only this block and
preserves existing text outside it. Missing blocks are drift. Duplicate or
unpaired markers are conflicts and the affected file is not overwritten.
Instruction contents are not printed in diagnostics. Existing standalone
instructions outside the block remain local content, even if they repeat the
common source.

Role-specific memory behavior stays separate from this shared policy. Built-in
Claude memory is off, but agentmemory has its own controls. Keep the user's own
session memory and worker, review, and test-run memory rules distinct, as
[Agent plugins](agent-pack.md) and [Hooks](hooks.md) describe. A profile name is
a label, not an instruction to change a provider's environment.

Both commands report unregistered directories found at `~/.claude*/settings.json`
and an unregistered active `CLAUDE_CONFIG_DIR`, including one outside the home
directory. They exit nonzero and leave those directories untouched, even if no
launcher uses them. Detection is not a complete inventory of every host. When
creating an isolated instance, register its custom location rather than relying
on discovery. Invalid JSON and configuration conflicts also return nonzero.
Diagnostics show paths and key names, not settings values.

Classify a setting by the behavior it controls before assigning its scope.
Common interaction rules, terminal display and approval settings, role-specific
memory behavior, and project rules need not share a scope even when their keys
have the same JSON parent. Keep regression expectations tied to the intended
behavior, not only to values computed from the current source.

After changing common settings or instructions, run sync and status across the
registry. After adding an instance, changing its launch configuration, or
updating Claude Code or its host, start a fresh session through that instance's
real launcher. Check the environment relevant to configuration and routing,
including `CLAUDE_CONFIG_DIR`, without exposing credentials. Check that
`AskUserQuestion`, `EnterPlanMode`, and `SendFeedback` are unavailable, Artifact
and bundled skills are absent, expected plugins and their skills are visible,
and common instructions load. Use `/model` and the proxy or provider's
diagnostics to check the selected model and where a request is sent. In T3
Code, confirm that necessary questions use ordinary chat and that the user's
reply is a usable fork or rewind checkpoint. Check worker memory behavior
against its role separately.

Launch arguments, environment variables, project settings, and host-supplied
instructions can change effective behavior. A successful file check does not
prove what a running session has loaded. Report file checks, fresh-launch
checks, and host-level checkpoint checks separately, including any that were
not performed.

## Review launcher

`claude-review` starts `claude` with a time budget for each turn. A program
that starts Claude Code from a configured executable path, such as the Claude
"Binary path" setting in T3 Code, can use `~/.local/bin/claude-review` as that
path. The `PATH` the program passes must contain `uv` and `claude`. A lone
`--version`, `--help`, or their short forms runs `claude` unchanged.

Claude Code keeps only the last `--settings` flag, so the launcher removes every
`--settings` option in front of a `--` argument and merges the values in order
into one object. A value is inline JSON or the path of a JSON file. Later keys
win, and `env` merges key by key. The launcher appends three command hooks to
the `hooks` the caller set, then runs `claude` with the merged object as the
only `--settings` flag, followed by the other arguments in their original
order. A value that is not a JSON object, a file that cannot be read, or an
`env` that is not an object makes the launcher print one line that starts with
`claude-review: ` and exit with 1 before it starts `claude`. The line does not
repeat the value.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CLAUDE_REVIEW_WARN_MINUTES` | 20 | Minutes into a turn after which the model gets one reminder |
| `CLAUDE_REVIEW_MINUTES` | 30 | Minutes into a turn after which tool calls are refused |

Both accept decimals. A value that is not a number, a value of 0 or less, or a
warning time that is not below the budget stops the launch with exit code 1.
The launcher sets the resolved values in the environment it gives `claude`, so
the hooks read the same numbers.

The hooks keep one clock for each session:

| When | Effect |
| --- | --- |
| A prompt arrives, including the one Claude Code sends when a background subagent finishes | The clock restarts, and the reminder and the refusal start over |
| A tool call finishes after the warning time | The model gets one note with the minutes used. It says to finish the current check and write the report |
| The first tool call after the budget | The call is refused. The reason tells the model to write its report from what it has |
| Each later tool call | The call is refused, the turn ends, and the session waits for the next prompt |

The hooks fire only when the model calls a tool. They cannot interrupt a call
that is running or a reply that has no tool call. Calls from subagents count
against the clock of the session that started them. A hook that fails prints one
line to stderr and lets the call go ahead. Each clock is a file under
`claude-review/` in the system temporary directory.

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

The `agents:status` and `agents:sync` tasks manage agent packages and registered
Claude settings and instructions. Package ownership records limit retirement
to registrations they created. Run these tasks after changing marketplace pins
or common policy. They do not run `mise bootstrap` or apply other dotfiles.
The bootstrap task invokes only `agents:settings:sync`, not package
installation. [Agent plugins](agent-pack.md) describes package support,
conflicts, state storage, and reload requirements.

Deleting an entry from `mise.toml` leaves the file as it is.
[`mise dot unapply`](https://mise.jdx.dev/cli/dotfiles/unapply.html) removes a
block with its markers.

Mise's dotfile target paths are fixed. Register intentionally separate
`CLAUDE_CONFIG_DIR` settings and instruction targets in the local profile
registry. Status-line scripts and plugin installations are separate from
profile reconciliation.
For other target changes, including `CODEX_HOME`, `NPM_CONFIG_USERCONFIG`, or
`XDG_CONFIG_HOME` (pnpm then reads `$XDG_CONFIG_HOME/pnpm/config.yaml`), change
the matching entries in `mise.toml`.

## What it leaves alone

The setup does not touch Git identity, commit signing, credential helpers,
`gh` login, or SSH keys. Keep those in `~/.gitconfig`, in files it includes, or
in each tool's own login flow. It also leaves lines that other tools add to
your shell startup files, such as Homebrew's `shellenv`.

## Change a setting later

Edit the file in `setup/` or the entry in `mise.toml`, then run
`mise bootstrap` again. `mise dot apply` applies only the file entries. To
apply just common Claude settings and instructions, run
`mise run agents:settings:sync`. Check the result across registered profiles
with `mise run agents:settings:status`, then use the fresh-session checks above
for changed runtime behavior.

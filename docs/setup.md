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

`mise.toml` also declares the repository's Actions analyzers. Run `mise install
--locked` to install them without applying the machine setup. Loading the
checkout puts installed tools on mise's activated `PATH` but declares no
environment variables.

## Check GitHub Actions

From the checkout, run:

```sh
mise install --locked
mise run actions:check
mise exec -- node --test test/actions-checks.mjs
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

Agents:

| Target | Change |
| --- | --- |
| `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.pi/agent/AGENTS.md` | Copies of `setup/agents/preferences.md`, the coding-agent instructions |
| `~/.hermes/AGENTS.md` | Copy of `setup/agents/hermes-preferences.md`, the personal-assistant instructions |
| `~/.claude/settings.json` | The keys in `setup/agents/claude-settings.json` |
| `~/.hermes/config.yaml` | The keys in `setup/agents/hermes-config.yaml` |
| `~/.claude/status-line.sh` | Copy of `setup/agents/claude-statusline.sh` |

Hermes reads its shared preferences through the `ramtoshiya` native plugin,
which must be installed separately as described in [Agent plugins](agent-pack.md).

`hermes-config.yaml` enables approval protection for instruction-file writes.
Its `skills.disabled` list hides development and product-design workflows,
plus selected personal-service skills that are not in use. It retains the
shared Excalidraw, Mermaid validation, and Codex session-reading skills.
Image generation uses Hermes' native `image_generate` tool instead of the
shared image skill. The `openai-codex` provider uses ChatGPT/Codex OAuth with
`gpt-image-2-medium`, not an OpenAI API key. Sign in with
`hermes auth add openai-codex` if needed. Subscription limits apply, and the
backend can return a different quality or size from the request. Credentials
stay in Hermes' local authentication store, outside this repository.
The config also disables the Orca lifecycle plugin `orca-status`.

mise merges these keys without replacing other Hermes configuration. Lists
are replaced as a whole, so add local exclusions to the source before applying.
A disabled skill stays on disk and does not become active after a bundle update.
New bundled skill names are not automatically excluded.

Hermes handles personal tasks and disposable scripts, not project or product
implementation. Its instructions require approval before handing coding work
to Claudex or Codex. They also default email to reading and drafting, with
confirmation for sending, reservations, payments, and destructive actions
unless a specific authorization or standing rule covers the action. The
package selection in [Agent plugins](agent-pack.md) retains Korean writing
without installing the full design workflow at user level. The shared disabled
plugin list leaves `omd` available for an explicitly enabled project plugin.
Keep its full package out of the user plugin directory and opt into project
discovery only when launching in that project. Orca can recreate its managed
plugin when launching Hermes, so avoid that launch path if no Orca integration
is wanted.

The coding-agent instructions authorize local commits of completed, validated
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

The `agents:status` and `agents:sync` tasks manage agent package installations
separately from these dotfile operations. They use an ownership record to
reconcile shared settings lists without replacing unrelated entries. Run them
from the checkout after changing marketplace pins. They do not run
`mise bootstrap` or apply dotfiles. [Agent plugins](agent-pack.md) describes
host support, conflicts, state storage, and reload requirements.

Deleting an entry from `mise.toml` leaves the file as it is.
[`mise dot unapply`](https://mise.jdx.dev/cli/dotfiles/unapply.html) removes a
block with its markers.

Target paths are fixed. If you set `CLAUDE_CONFIG_DIR`, `CODEX_HOME`,
`HERMES_HOME`, `NPM_CONFIG_USERCONFIG`, or `XDG_CONFIG_HOME` (pnpm then reads
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

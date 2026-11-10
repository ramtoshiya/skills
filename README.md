# skills

Plugins for coding agents, and a macOS machine setup. This is one developer's
working setup, published so that others can install parts of it or copy them.

The plugins install as they are. The machine setup applies the author's own
preferences, so fork the repository and edit it before you run it.

## What is here

| Part | What it does | Docs |
| --- | --- | --- |
| `ramtoshiya` plugin | Skills for Claude Code and Codex, plus a hook that blocks global package installs, unpinned one-shot package runs, and pip installs into a system Python | [Agent plugins](docs/agent-pack.md), [Hooks](docs/hooks.md) |
| `ramtoshiya-cc` plugin | Claude Code only: a skill for claude.ai/design projects, an opt-in lead mode that hands work to subagents on the cheapest model that can do it, and a hook that blocks AI attribution lines in commits and pull requests | [Agent plugins](docs/agent-pack.md) |
| Third-party skills | Skills from other repositories, listed in this repository's marketplace and pinned to exact commits | [Third-party skills](docs/upstream-skills.md) |
| Machine setup | A `mise.toml` that installs a few Homebrew packages and writes shell, Git, package manager, and agent settings | [Machine setup](docs/setup.md) |
| `sidecar` | A macOS command that connects an iPad as a Sidecar display, and an iPad shortcut that runs it over SSH | [README](cli/sidecar/README.md) |
| `claudex` | Runs Claude Code with GPT models discovered from a [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) server | [README](cli/claudex/README.md) |
| `worktreeinclude` | Copies selected ignored files into new Git worktrees through an explicitly installed repository hook | [README](cli/worktreeinclude/README.md) |
| `excalidraw-board` | Proof-of-concept command for reading and editing shared Excalidraw rooms | [README](cli/excalidraw-board/README.md) |
| `excalidraw-web-export` | Headless PNG export through a deployed Excalidraw app, from a local file or saved room snapshot | [README](cli/excalidraw-web-export/README.md) |

## Install the agent plugins

The hooks run through [uv](https://docs.astral.sh/uv/getting-started/installation/)
and need a uv-managed Python 3.11 or newer. The package guard also blocks a
package manager's commands, including `uv run`, until that package manager has
a three-day minimum release age configured, so set it for each one you use.
[Agent plugins](docs/agent-pack.md) lists those settings, the checks to run
after installing, and updates.

Claude Code:

```sh
claude plugin marketplace add ramtoshiya/skills
claude plugin install ramtoshiya@ramtoshiya --scope user
claude plugin install ramtoshiya-cc@ramtoshiya --scope user
```

Codex (then trust the plugin's hooks in `/hooks`):

```sh
codex plugin marketplace add ramtoshiya/skills
codex plugin add ramtoshiya@ramtoshiya
```

## Keep installed agents synchronized

From a local checkout, `mise run agents:status` compares installed packages with
the repository's pins and checks registered Claude profiles' common settings
and instructions. `mise run agents:sync` reconciles them without replacing
unrelated settings or instruction text outside its managed block. It installs
all applicable marketplace entries and stops on local package modifications.
[Agent plugins](docs/agent-pack.md) describes the managed scope, conflicts, and
required restarts.

## Set up a Mac

Fork and clone the repository, edit `mise.toml` and the files in `setup/`, then
run `mise bootstrap` from the checkout. [Machine setup](docs/setup.md) lists
every file the setup changes and the settings it applies.

## Repository layout

```text
.claude-plugin/marketplace.json   Claude Code and Codex marketplace: both plugins and the third-party entries
package.json                      The npm test script
plugins/ramtoshiya/                   Skills and hooks for Claude Code and Codex
plugins/ramtoshiya-cc/                Claude Code-only skills and hook
mise.toml, setup/                 Machine setup and the files it copies into place
cli/sidecar/                      Standalone macOS command
cli/claudex/                      Claude Code launcher for CLIProxyAPI GPT models
cli/worktreeinclude/              Ignored-file copier with explicit Git hook management
cli/excalidraw-board/              Standalone shared-board command
cli/excalidraw-web-export/         Headless deployed-app PNG exporter
test/                             Tests for the hooks and the standalone CLIs
docs/                             Documentation
```

## Development

```sh
npm test
claude plugin validate ./plugins/ramtoshiya
claude plugin validate ./.claude-plugin/marketplace.json
```

`npm test` needs Node.js 22.19 or newer and uv. It runs the standalone CLI
tests and the Python tests for the hooks. `AGENTS.md` holds the rules for
changing this repository.

# skills

Plugins for coding agents, and a macOS machine setup. This is one developer's
working setup, published so that others can install parts of it or copy them.

The plugins install as they are. The machine setup applies the author's own
preferences, so fork the repository and edit it before you run it.

## What is here

| Part | What it does | Docs |
| --- | --- | --- |
| `ramtoshiya` plugin | Skills for Claude Code, Codex, [Pi](https://pi.dev), and [Hermes](https://hermes-agent.nousresearch.com), plus two hooks: a guard that blocks global package installs, unpinned one-shot package runs, and bare `python`/`pip`, and a stop check that asks the agent to deal with uncommitted Git changes | [Agent plugins](docs/agent-pack.md), [Hooks](docs/hooks.md) |
| `ramtoshiya-cc` plugin | Claude Code only: a skill for claude.ai/design projects and a hook that blocks AI attribution lines in commits and pull requests | [Agent plugins](docs/agent-pack.md) |
| Third-party skills | Skills from other repositories, listed in this repository's marketplace and pinned to exact commits | [Third-party skills](docs/upstream-skills.md) |
| Machine setup | A `mise.toml` that installs a few Homebrew packages and writes shell, Git, package manager, and agent settings | [Machine setup](docs/setup.md) |
| CLIProxyAPI provider | A Pi extension that lists the Claude and GPT models of a [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) server and talks to each in its native protocol | [README](pi/cliproxy-provider/README.md) |
| `sidecar` | A macOS command that connects an iPad as a Sidecar display, and an iPad shortcut that runs it over SSH | [README](cli/sidecar/README.md) |
| `claudex` | Runs Claude Code with GPT models discovered from CLIProxyAPI | [README](cli/claudex/README.md) |
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

Pi:

```sh
pi install git:github.com/ramtoshiya/skills
```

Hermes, from the root of a local clone:

```sh
mkdir -p ~/.hermes/plugins
ln -s "$PWD/plugins/ramtoshiya" ~/.hermes/plugins/ramtoshiya
hermes plugins enable ramtoshiya
```

Restart Hermes after enabling. [Agent plugins](docs/agent-pack.md) describes
its hook limits and shared preferences.

## Keep installed agents synchronized

From a local checkout, `mise run agents:status` compares installed packages with
the repository's pins. `mise run agents:sync` reconciles Claude Code, Codex, Pi,
and Hermes without replacing unrelated settings. It installs all applicable
marketplace entries and stops on local modifications. [Agent plugins](docs/agent-pack.md)
describes the managed scope, conflicts, and required restarts.

## Set up a Mac

Fork and clone the repository, edit `mise.toml` and the files in `setup/`, then
run `mise bootstrap` from the checkout. [Machine setup](docs/setup.md) lists
every file the setup changes and the settings it applies.

## Repository layout

```text
.claude-plugin/marketplace.json   Claude Code and Codex marketplace: both plugins and the third-party entries
package.json                      Pi package manifest for the ramtoshiya plugin
plugins/ramtoshiya/                   Skills and hooks for Claude Code, Codex, Pi, and Hermes
plugins/ramtoshiya-cc/                Claude Code-only skill and hook
mise.toml, setup/                 Machine setup and the files it copies into place
pi/cliproxy-provider/             Pi provider package, installed separately
cli/sidecar/                      Standalone macOS command
cli/claudex/                      Claude Code launcher for CLIProxyAPI GPT models
cli/worktreeinclude/              Ignored-file copier with explicit Git hook management
cli/excalidraw-board/              Standalone shared-board command
cli/excalidraw-web-export/         Headless deployed-app PNG exporter
test/                             Tests for the hooks and the Pi package
docs/                             Documentation
```

## Development

```sh
npm test
claude plugin validate ./plugins/ramtoshiya
claude plugin validate ./.claude-plugin/marketplace.json
```

`npm test` needs Node.js 22.19 or newer and uv. It runs the standalone CLI and
Pi adapter tests, plus the Python tests for all three hooks and the Hermes
adapter. `AGENTS.md` holds the rules for changing this repository.

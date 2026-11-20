# skills

Plugins for coding agents, and a macOS machine setup. This is one developer's
working setup, published so that others can install parts of it or copy them.

The plugins install as they are. The machine setup applies the author's own
preferences, so fork the repository and edit it before you run it.

## What is here

| Part | What it does | Docs |
| --- | --- | --- |
| `ramtoshiya` plugin | Skills for Claude Code and Codex, plus a hook that blocks global package installs, unpinned one-shot package runs, and pip installs into a system Python | [Agent plugins](docs/agent-pack.md), [Hooks](docs/hooks.md) |
| `ramtoshiya-cc` plugin | Claude Code only: a skill for claude.ai/design projects, a context budget hook for the shared `self-compact` skill, and a hook that blocks AI attribution lines in commits and pull requests | [Agent plugins](docs/agent-pack.md) |
| Third-party skills | Skills from other repositories, listed in this repository's marketplace and pinned to exact commits | [Third-party skills](docs/upstream-skills.md) |
| Machine setup | A `mise.toml` that installs a few Homebrew packages and writes shell, Git, package manager, and agent settings | [Machine setup](docs/setup.md) |
| `held-drafts` bb plugin | Lets agents create [bb](https://getbb.app) threads whose first message waits until a person sends it | [README](bb-plugins/held-drafts/README.md) |
| `draft-quick-actions` bb plugin | Sends an eligible Held Drafts message from a thread header button that works on touch screens, or from a sidebar play button | [README](bb-plugins/draft-quick-actions/README.md) |
| `sidebar-model-label` bb plugin | Shows each thread's model beside its title without adding a second row | [README](bb-plugins/sidebar-model-label/README.md) |
| `inline-vis-copy-image` bb plugin | Makes bb Desktop's Copy Image menu item work on images inside inline visualizations | [README](bb-plugins/inline-vis-copy-image/README.md) |
| `tilde-strikethrough` bb plugin | Strikes through chat text only between double tildes, so ranges such as `v3~6` keep their tildes | [README](bb-plugins/tilde-strikethrough/README.md) |
| `claudex-native` bb plugin | Adds a Claudex provider using a locally generated, hash-verified bb bridge | [README](bb-plugins/claudex-native/README.md) |
| `sidecar` | A macOS command that connects an iPad as a Sidecar display, and an iPad shortcut that runs it over SSH | [README](tools/sidecar/README.md) |
| `claudex` | Runs Claude Code with GPT models discovered from a [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) server | [README](tools/claudex/README.md) |
| `plugin-update-review` | Prepares local plugin update candidates for human review, tests, and application | [README](tools/plugin-update-review/README.md) |
| `worktreeinclude` | Copies selected ignored files into new Git worktrees through an explicitly installed repository hook | [README](tools/worktreeinclude/README.md) |
| `excalidraw-board` | Proof-of-concept command for reading and editing shared Excalidraw rooms | [README](tools/excalidraw-board/README.md) |
| `excalidraw-web-export` | Headless PNG export through a deployed Excalidraw app, from a local file or saved room snapshot | [README](tools/excalidraw-web-export/README.md) |

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
and instructions. `mise run agents:sync` reconciles Claude Code and Codex
without replacing unrelated settings or instruction text outside
its managed block. It installs all applicable marketplace entries and stops on
local package modifications. After `mise run main:sync` runs once in the
checkout, every change to `main` runs these installers, and
`mise run main:status` reports anything still behind `origin/main`.
[Agent plugins](docs/agent-pack.md) describes the managed scope, conflicts, and
required restarts.

## Set up a Mac

Fork and clone the repository, edit `mise.toml` and the files in `setup/`, then
run `mise bootstrap` from the checkout. [Machine setup](docs/setup.md) lists
every file the setup changes and the settings it applies.

## Repository layout

```text
.claude-plugin/marketplace.json   Claude Code and Codex marketplace
plugins/                          Skills and hooks for supported hosts
tools/                            Independently installed commands and their tests
bb-plugins/                       Plugins for the bb app, installed separately
setup/                            Machine configuration copied or merged by mise
dev/                              Repository tests, automation, evals, and disabled skills
docs/                             Human-facing documentation
mise.toml, mise.lock              Machine setup and pinned development tools
package.json                      Aggregate repository test command
```

## Development

```sh
npm test
claude plugin validate ./plugins/ramtoshiya
claude plugin validate ./.claude-plugin/marketplace.json
```

`npm test` needs Node.js 24.21 or newer and uv. `mise install --locked` installs
the pinned versions, and `mise exec -- npm test` uses them, as the Tests
workflow does on every push and pull request. It runs the dependency-free
CLI, repository, plugin, and setup tests. The workflow also installs the
[exporter test dependencies](tools/excalidraw-web-export/README.md) and runs
its offline tests. Live service checks and model evals run only when
explicitly invoked. `AGENTS.md` holds the rules for changing this repository.

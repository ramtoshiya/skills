# Agent plugins

This repository has two plugins. `ramtoshiya` works in Claude Code, Codex, Pi,
and Hermes. `ramtoshiya-cc` works only in Claude Code. Both install from the
marketplace file `.claude-plugin/marketplace.json`, which also lists the
[third-party skills](upstream-skills.md). Pi installs `ramtoshiya` as a Pi package
instead. Hermes loads the shared plugin from a local clone.

## What the plugins contain

`ramtoshiya` skills:

| Skill | What it does | Needs |
| --- | --- | --- |
| `codex-session-reader` | Finds and reads Codex CLI session transcripts under `~/.codex/sessions/` | Nothing |
| `figma-rest` | Reads Figma files, tokens, and rendered nodes through the REST API instead of the Figma MCP server | A Figma personal access token in the `FIGMA_TOKEN` environment variable, or as a `FIGMA_TOKEN=<token>` line in `~/.config/agent-secrets/figma.env` |
| `excalidraw-board` | Reads and draws on shared excalidraw.com rooms through a proof-of-concept CLI | The separately installed `excalidraw-board` command on `PATH`, described in [its README](../cli/excalidraw-board/README.md) |
| `github-actions-authoring` | Checks official releases, a 72-hour cooldown, compatibility, and full commit pins before editing GitHub Actions workflows or action metadata | Git, authenticated `gh` access, `actionlint`, `zizmor`, and the target repository's test runner on `PATH` |
| `imagegen` | Generates and edits images with OpenAI GPT Image or xAI Grok Imagine through an OpenAI-compatible Images API | uv, and an API key or proxy in the environment (see the skill's `SKILL.md`) |
| `mermaid-check` | Runs the Mermaid parser over diagrams before the agent delivers them | Node.js. The first run downloads `@mermaid-js/mermaid-cli` 12.0.0 through `npx` |
| `reorganize-commits` | Rewrites the current branch's commits into reviewable chunks. Runs only when you invoke it | Git |
| `stable-refs` | Gives documents and plans permanent identifiers that survive edits | Nothing |

The GitHub Actions skill applies to `.github/workflows/*.yml`,
`.github/workflows/*.yaml`, `action.yml`, and `action.yaml`, including changes that
do not explicitly update versions. It inventories remote dependencies and stops
when official release age, tag provenance, or compatibility cannot be verified.
It requires `actionlint`, `zizmor`, repository tests, and a safe affected workflow
run when feasible. Tool versions and advisories need review too. The skill never
installs missing tools and never enables verbose/debug `zizmor` logging with a
GitHub token present. Follow the target repository's documented setup step for
missing tools, or [Machine setup](setup.md) for this repository. These are agent
instructions, not automatic hook enforcement.

`ramtoshiya` hooks, described in [Hooks](hooks.md):

- A package and Python guard that checks each shell command before it runs.
- A Git hygiene check that runs when the agent is about to stop.

`ramtoshiya-cc` contains the `claude-design-direct` skill, which edits and previews
claude.ai/design projects through Claude Code's `DesignSync` tool, and a hook
that blocks AI attribution lines in commits and pull requests.

Excalidraw board requests update a shared room. A `.excalidraw` attachment is
an export or an agreed fallback, not a replacement for that room. The agent
reports saved content separately from browser display and stops if read-back
content is missing or different. It shares room ids, not secret room links.

The board skill's offline policy evaluations use simulated room state and do
not publish drawings. Run them explicitly with an authenticated Claude Code:

```sh
node test/excalidraw-skill-eval.mjs plugins/ramtoshiya/skills/excalidraw-board/SKILL.md /path/to/eval-results
```

These evaluations check the model's delivery decisions, not the CLI protocol
or live browser synchronization. `npm test` runs the CLI's automated tests.

## Requirements

The hooks run with [uv](https://docs.astral.sh/uv/getting-started/installation/)
in offline mode, so a uv-managed Python 3.11 or newer must already be installed
(`uv python install` installs one). Check it with the command the hooks use:

```sh
uv run --offline --no-project --managed-python --python '>=3.11' --no-config --exclude-newer '3 days' python -V
```

The package guard blocks every command that resolves or installs packages,
including `uv run`, until the package manager has a minimum release age of at
least three days. Set it for each package manager you use:

| Package manager | Setting |
| --- | --- |
| npm | `min-release-age=3` in `~/.npmrc` (days) |
| pnpm | `minimumReleaseAge: 4320` in `~/Library/Preferences/pnpm/config.yaml` (minutes) |
| Yarn | `npmMinimalAgeGate: 4320` in `~/.yarnrc.yml` (minutes) |
| uv | `exclude-newer = "3 days"` in `~/.config/uv/uv.toml` |

A project's own config file can set them too. The
[machine setup](setup.md) writes the npm, pnpm, and uv settings.

The plugins have no third-party runtime dependencies. Tested with Claude Code
2.1.301, Codex CLI 0.162.1, Pi 1.2.0, and Hermes 0.22.2.

## Install

Install the agents themselves from their own instructions:
[Claude Code](https://code.claude.com/docs/en/setup),
[Codex CLI](https://github.com/openai/codex), [Pi](https://pi.dev), and
[Hermes](https://hermes-agent.nousresearch.com/docs/getting-started/installation).

Claude Code:

```sh
claude plugin marketplace add ramtoshiya/skills
claude plugin install ramtoshiya@ramtoshiya --scope user
claude plugin install ramtoshiya-cc@ramtoshiya --scope user
```

Codex:

```sh
codex plugin marketplace add ramtoshiya/skills
codex plugin add ramtoshiya@ramtoshiya
```

Codex runs a plugin hook only after you trust it. Open `/hooks` in Codex and
trust the `ramtoshiya` `PreToolUse` and `Stop` hooks. Installing or enabling the
plugin does not trust them. Codex can see `ramtoshiya-cc` in the marketplace, but
it does not work there, so do not install it.

Pi:

```sh
pi install git:github.com/ramtoshiya/skills
```

The Pi package contains the `ramtoshiya` skills and one extension, `hooks/pi.ts`,
which runs both hooks. Pi does not read the marketplace file, so it gets
neither `ramtoshiya-cc` nor the third-party skills from this command.

Hermes, from the root of a local clone:

```sh
mkdir -p ~/.hermes/plugins
ln -s "$PWD/plugins/ramtoshiya" ~/.hermes/plugins/ramtoshiya
hermes plugins doctor ~/.hermes/plugins/ramtoshiya --ci
hermes plugins enable ramtoshiya
```

Use an unused destination for the link. Hermes discovers `plugin.yaml` and
`__init__.py`, which register the shared skills under `ramtoshiya:<name>` and
translate the two guard protocols. It does not read the marketplace file or
install third-party skills. This plugin uses the native
[Hermes plugin API](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins).

The optional [machine setup](setup.md) copies shared preferences to
`~/.hermes/AGENTS.md`. The plugin adds that file to new sessions as a system
prompt section. Hermes does not load this global `AGENTS.md` on its own.
`HERMES_HOME` selects the home used by the plugin, so change the mise target
if you use a custom home or profile.

Restart Hermes after installing or changing the plugin or its preferences.
Its Git check runs through `pre_verify` after file edits, subject to Hermes's
`agent.max_verify_nudges` setting. [Hooks](hooks.md) lists the other limits.

To install Claude Code, Codex, or Pi from a local clone instead, use its path
in place of `ramtoshiya/skills` and `git:github.com/ramtoshiya/skills`. Claude Code and Pi
then load the plugin from the checkout, so edits apply after a reload.

Restart the agent after installing, or run `/reload-plugins` in Claude Code and
`/reload` in Pi.

## Check that it works

In each agent, ask it to run these commands:

1. `git status` runs normally.
2. `pip --version` is blocked with a message about bare Python and pip commands.
3. In a repository with an uncommitted change, the agent's first attempt to
   stop is blocked with a list of the changes. A second attempt is allowed.

For Hermes's stop check, have the agent edit a disposable file in a temporary
Git repository first. Its `pre_verify` event requires recorded file edits.

In Claude Code, `/plugin` lists the installed plugins. Each skill should appear
once in the agent's skill list. A loose copy of the same skill, for example in
`~/.claude/skills/` or `~/.agents/skills/`, makes it appear twice.

## Update

The plugins have no `version` field, so Claude Code treats each commit of the
marketplace repository as a new version.

| Agent | Update command |
| --- | --- |
| Claude Code | `claude plugin marketplace update ramtoshiya`, then `claude plugin update ramtoshiya@ramtoshiya` (and `ramtoshiya-cc@ramtoshiya`) and a restart |
| Codex | Follow the source refresh, installation, and restart steps below. Changed hooks need your trust again in `/hooks` |
| Pi | `pi update --extensions`, then `/reload` |
| Hermes | Update the linked checkout, run `hermes plugins doctor ~/.hermes/plugins/ramtoshiya --ci`, then restart Hermes |

Refreshing Codex's installed plugin does not reload active sessions. Use a fresh
process to load the changed skills. If a session reports a missing plugin file
after an update, restart that session rather than repairing the cache.

1. Refresh the marketplace source. For a Git-backed marketplace, run
   `codex plugin marketplace upgrade ramtoshiya`. For a marketplace added from a
   local checkout, update that checkout instead.
2. Run `codex plugin add ramtoshiya@ramtoshiya` to install from that source.
3. Start a fresh Codex process, review changed hooks in `/hooks`, and run the
   checks above. Installing files alone does not verify that an existing
   session has loaded them.

If clients use a shared app-server daemon, a new terminal may reconnect to the
same server. Check `codex app-server daemon version` before considering
`codex app-server daemon restart`. Coordinate a restart with other clients
because it can interrupt their work. A fresh run with `codex --no-daemon` can
help distinguish shared-server state from the installed files.

Do not repair a missing plugin version with cache edits or links to another
version. Use the install and runtime lifecycle above. For versioned third-party
plugins such as `humanize`, also follow [Third-party skills](upstream-skills.md).

## How the files fit together

```text
package.json                               Pi package manifest: the ramtoshiya skills and hooks/pi.ts
.claude-plugin/marketplace.json            Marketplace read by Claude Code and Codex
plugins/ramtoshiya/.claude-plugin/plugin.json  Plugin manifest, read by Claude Code and Codex
plugins/ramtoshiya/skills/                     Skills
plugins/ramtoshiya/hooks/global-package-guard.py   Package and Python rules
plugins/ramtoshiya/hooks/git-hygiene-guard.py      Stop check
plugins/ramtoshiya/hooks/hooks.json            Hook registration for Claude Code and Codex
plugins/ramtoshiya/hooks/pi.ts                 Pi extension that runs both Python hooks
plugins/ramtoshiya/plugin.yaml                 Hermes native plugin manifest
plugins/ramtoshiya/__init__.py                 Hermes skills, preferences, and hook adapter
plugins/ramtoshiya-cc/                         Claude Code-only skill and hook
```

The rules live only in the guard scripts. `hooks.json`, `pi.ts`, and the Hermes
adapter pass each agent's event to them and translate the answer. Each skill
under `skills/` also needs an entry in the Hermes adapter's `SKILLS` map.
The registration test checks that every shipped skill is included. The `files`
list in `package.json` limits the Pi package to `plugins/ramtoshiya/`, `README.md`, and the
plugin docs. `npm test` checks that a packed copy contains nothing else and that
its guard runs without the rest of the repository.

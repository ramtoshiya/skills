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
| `imagegen` | Generates and edits images with OpenAI GPT Image or xAI Grok Imagine through an OpenAI-compatible Images API | uv, and an API key or proxy in the environment (see the skill's `SKILL.md`) |
| `mermaid-check` | Runs the Mermaid parser over diagrams before the agent delivers them | Node.js. The first run downloads `@mermaid-js/mermaid-cli` 12.0.0 through `npx` |
| `reorganize-commits` | Rewrites the current branch's commits into reviewable chunks. Runs only when you invoke it | Git |
| `stable-refs` | Gives documents and plans permanent identifiers that survive edits | Nothing |

`ramtoshiya` hooks, described in [Hooks](hooks.md):

- A package and Python guard that checks each shell command before it runs.
- A Git hygiene check that runs when the agent is about to stop.

`ramtoshiya-cc` contains the `claude-design-direct` skill, which edits and previews
claude.ai/design projects through Claude Code's `DesignSync` tool, and a hook
that blocks AI attribution lines in commits and pull requests.

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

## Synchronize a local checkout

For a managed installation of this repository and its selected third-party
packages, run these tasks from the checkout with [mise](https://mise.jdx.dev/getting-started.html):

```sh
mise run agents:status
mise run agents:sync
```

`status` makes no configuration changes or source downloads. Native inventory
commands may refresh their own metadata caches. The task exits nonzero for
missing packages, outdated contents, or conflicts. `sync` reconciles every
supported agent executable on `PATH`. It skips agents that are not installed.
Use `--host claude`, `--host codex`, `--host pi`, or `--host hermes` to restrict
either task. `--json` prints the results as JSON.

The marketplace supplies the exact third-party pins. `setup/agents/hosts.json`
limits `ramtoshiya-cc` to Claude Code and the `humanize-korean` and
`omd-kr-writer` packages to Hermes. Hermes uses a personal-assistant selection:
`ramtoshiya`, `humanize`, `humanize-korean`, and the writing-only
`omd-kr-writer` adapter. Full OmD, OpenPencil, Matt Pocock productivity,
test-audit, and Ouroboros interview apply only to Claude Code, Codex, and Pi.
Other entries apply to all four hosts unless the policy lists specific hosts.
Adding an entry therefore declares an installation, not just a marketplace
listing, when using these tasks.

Claude Code and Codex use their native plugin commands and a marketplace
registered from this checkout. An existing marketplace registered elsewhere is
reported as a conflict rather than retargeted. Claude's `readFromFolder`, when
present, is its effective installation, even if an older cache still exists.
Native installer results are checked against the approved source files.
Same-version cache problems are reported, never repaired with cache edits.

Pi settings retain unrelated packages, skills, and extensions. Hermes loads
native plugins through links to pinned sources. Packages without a native
Hermes plugin use thin skill-registration adapters. The Humanize adapter
translates its pinned advisory hook without changing its wording rules.
Existing Hermes adapters not created by sync are preserved. Adapters created by
sync follow the repository template, with the same local-change checks as other
managed files. OpenPencil remains a standalone Hermes skill with its whole
reference directory.

Sync records owned paths, file fingerprints, and settings entries under
`$XDG_STATE_HOME/ramtoshiya-agents`, or `~/.local/state/ramtoshiya-agents`.
Sources not already available in a host's `skill-sources/` directory are fetched
at the approved commit into that state directory. Upstream files and local
state stay outside this repository. A repeated sync does not rewrite unchanged
settings or ownership state.

On first use, existing skill copies must match an approved source before sync
adopts them. Local modifications are conflicts, not permission to replace the
files. Preserve the customization in a reviewed fork or resolve it manually
before retrying. After adoption, removing or changing a managed settings entry
also produces a conflict. Unrelated entries remain untouched. Symlinked JSON
configuration files are not replaced or written through, so other dotfile
managers keep ownership of their targets.

Removing a declared package retires only its recorded registrations. Pi removes
owned list entries. Claude and Codex use their uninstall commands, with Claude
persistent data retained. Hermes disables plugins and retains their directories.
A managed standalone skill link can be removed, but a copied directory requires
manual preservation first. Downloaded source checkouts are retained.

Sync does not upgrade upstream pins, install agent executables or skill CLIs,
apply shared dotfiles, grant hook trust, or restart running sessions. Review
Codex hooks in `/hooks`, reload Pi, and restart Claude Code or Hermes after
changes. Finish active Codex turns before installation and coordinate any
shared-server restart as described below. The status table verifies installed
files and configuration, not what an existing session has loaded.

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

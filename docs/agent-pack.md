# Agent plugins

This repository has two plugins. `ramtoshiya` works in Claude Code and Codex.
`ramtoshiya-cc` works only in Claude Code. Both install from the marketplace
file `.claude-plugin/marketplace.json`, which also lists the
[third-party skills](upstream-skills.md).

## What the plugins contain

`ramtoshiya` skills:

| Skill | What it does | Needs |
| --- | --- | --- |
| `codex-session-reader` | Finds and reads Codex CLI session transcripts under `~/.codex/sessions/` | Nothing |
| `figma-rest` | Reads Figma files, tokens, and rendered nodes through the REST API instead of the Figma MCP server | A Figma personal access token in the `FIGMA_TOKEN` environment variable, or as a `FIGMA_TOKEN=<token>` line in `~/.config/agent-secrets/figma.env` |
| `excalidraw-board` | Reads and draws on shared excalidraw.com rooms, and exports selected saved objects as PNG | The separately installed `excalidraw-board` command on `PATH`, described in [its README](../cli/excalidraw-board/README.md). PNG export also needs [excalidraw-web-export](../cli/excalidraw-web-export/README.md) and headless Chrome/Chromium |
| `github-actions-authoring` | Checks official releases, a 72-hour cooldown, compatibility, and full commit pins before editing GitHub Actions workflows or action metadata | Git, authenticated `gh` access, `actionlint`, `zizmor`, and the target repository's test runner on `PATH` |
| `imagegen` | Generates and edits images with OpenAI GPT Image or xAI Grok Imagine through an OpenAI-compatible Images API | uv, and an API key or proxy in the environment (see the skill's `SKILL.md`) |
| `impeccable-interview` | Clarifies or resumes a product task and saves approved interview context in an Impeccable surface brief | An already-installed native Impeccable CLI supporting surface-brief v1 and Python 3.11+ (standard library only) |
| `mermaid-check` | Runs the Mermaid parser over diagrams before the agent delivers them | Node.js. The first run downloads `@mermaid-js/mermaid-cli` 12.0.0 through `npx` |
| `read-x` | Reads public X posts, threads, profiles, and searches through the mdfromx HTTP API | HTTP access to [mdfromx](https://mdfromx.com/) and curl |
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

`ramtoshiya-cc` contains:

- The `claude-design-direct` skill, which edits and previews claude.ai/design
  projects through Claude Code's `DesignSync` tool.
- The `lead` skill, which runs only when you invoke it with `/lead` or
  `/ramtoshiya-cc:lead`. The session then settles the goal and how to check it
  before work starts, and hands work to subagents on the cheapest model and
  effort that can do it. When you tell it to do a piece of work itself, it
  does that piece and goes back to delegating at the next one, unless you say
  the change should last. Guards and validators it builds target ordinary
  mistakes, not deliberate bypass, and are checked against real commands. It
  does not review by default. When a change needs review, such as instruction
  text, a data format, or a design memo, the session commits and merges it
  first, then starts one review as a separate T3 Code task in its own
  worktree. That task has 30 minutes, fixes only reproduced breaks of the
  original request, and stops with a decision for a person when a fix would go
  beyond that. When a T3 Code provider runs through the `claude-review`
  launcher in [Machine setup](setup.md), the task gets a reminder at 20
  minutes and its tool calls are refused after 30, counted from its latest
  prompt. Without the launcher, the 30 minutes are only an instruction.
  Outside T3 Code, the session recommends a review in its final report
  instead. In T3 Code, the file `~/.config/ramtoshiya/lead-route.json`
  decides where Haiku- and Sonnet-level workers run. With
  `{"workers": "codex"}` or `{"workers": "claudex"}` they run on GPT Luna and
  Terra models through that T3 Code provider, and the review runs on GPT Sol
  through the Codex provider. On both GPT routes, Luna workers use `low` for
  the Haiku low row and `max` for the Haiku max row. Terra workers use only
  `max`. When T3 Code lists a Codex provider instance named for workers, the
  `codex` route's workers and the review use it. Point
  that instance at a launcher that turns off what only your own sessions need,
  such as a memory plugin that injects summaries of earlier sessions. Without
  the file they run on Claude. Opus-level work stays on Claude, except that a
  Terra worker whose task outgrew it reruns on GPT Sol through the same
  provider. When the `quotio-cli` command from [Machine setup](setup.md) shows 90% or
  more of the route's weekly quota used, the session moves workers to the other
  side and says so. A worker that hits a usage limit moves workers the same
  way, and the session does not return to that side. When a T3 Code provider
  instance bans Claude Code's own subagent tools, for example with the launch
  argument `--disallowedTools Agent,Task,Workflow,SendMessage,ListAgents`, the
  session starts its Claude workers with T3 Code's `delegate_task` instead.
  Claude workers and child leads started with `delegate_task`, for that or any
  other reason, run on a Claude provider instance named for workers when T3
  Code lists one, and on the session's own instance otherwise. The agentmemory
  plugin's hooks do nothing when `AGENTMEMORY_SDK_CHILD` is `1`. Set that
  environment variable in the T3 Code provider settings of the instances for
  workers and review and of the `claudex` instance, and copy the other settings
  of the worker instance from the Claude instance you use yourself. Those
  sessions then neither receive summaries of earlier sessions nor record their
  own. Leave the variable off your own instance. Subagents started with Claude
  Code's Agent tool run inside the parent's process and keep the parent's
  memory behavior. Opus or Fable subagents the session starts read the same
  instructions and lead their part of the work. Claude
  Code keeps the instructions in context after compaction.
- A hook that blocks AI attribution lines in commits and pull requests.

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
2.1.301 and Codex CLI 0.162.1.

## Install

Install the agents themselves from their own instructions:
[Claude Code](https://code.claude.com/docs/en/setup) and
[Codex CLI](https://github.com/openai/codex).

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

To install from a local clone instead, use its path in place of
`ramtoshiya/skills`. Claude Code then loads the plugin from the checkout, so
edits apply after a reload.

Restart the agent after installing, or run `/reload-plugins` in Claude Code.

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
Use `--host claude` or `--host codex` to restrict either task. Repeat
`--plugin NAME` to limit both installation and retirement to named packages,
leaving other managed registrations alone. Unknown names are errors. `--json`
prints the results as JSON.

The marketplace supplies the exact third-party pins. `setup/agents/hosts.json`
limits `ramtoshiya-cc` to Claude Code. `omd-kr-writer` is installed at user
level on both hosts. Full `omd` is excluded from user-level sync and installed
only in explicitly selected projects. Other entries apply to both hosts unless
the policy lists specific hosts. Adding an entry therefore declares an
installation, not just a marketplace listing, when using these tasks.

Claude Code and Codex use their native plugin commands and a marketplace
registered from this checkout. An existing marketplace registered elsewhere is
reported as a conflict rather than retargeted. Claude's `readFromFolder`, when
present, is its effective installation, even if an older cache still exists.
Native installer results are checked against the approved source files.
Same-version cache problems are reported, never repaired with cache edits.

Sync records owned paths and file fingerprints under
`$XDG_STATE_HOME/ramtoshiya-agents`, or `~/.local/state/ramtoshiya-agents`.
Third-party sources are fetched at the approved commit into that state
directory. Upstream files and local state stay outside this repository. A
repeated sync does not rewrite unchanged ownership state.

On first use, an existing installed copy must match an approved source before
sync adopts it. Local modifications are conflicts, not permission to replace
the files. Preserve the customization in a reviewed fork or resolve it manually
before retrying. After adoption, local changes to a managed installation also
produce a conflict.

Removing a declared package retires only its recorded registrations. Claude and
Codex use their uninstall commands, with Claude persistent data retained.
Downloaded source checkouts are retained.

Sync does not upgrade upstream pins, install agent executables or skill CLIs,
apply shared dotfiles, grant hook trust, or restart running sessions. Review
Codex hooks in `/hooks` and restart Claude Code after changes. Finish active
Codex turns before installation and coordinate any shared-server restart as
described below. The status table verifies installed files and configuration,
not what an existing session has loaded.

## Check that it works

In each agent, ask it to run these commands:

1. `git status` runs normally.
2. `pip --version` is blocked with a message about bare Python and pip commands.
3. In a repository with an uncommitted change, the agent's first attempt to
   stop is blocked with a list of the changes. A second attempt is allowed.

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
.claude-plugin/marketplace.json            Marketplace read by Claude Code and Codex
plugins/ramtoshiya/.claude-plugin/plugin.json  Plugin manifest, read by Claude Code and Codex
plugins/ramtoshiya/skills/                     Skills
plugins/ramtoshiya/hooks/global-package-guard.py   Package and Python rules
plugins/ramtoshiya/hooks/git-hygiene-guard.py      Stop check
plugins/ramtoshiya/hooks/hooks.json            Hook registration for Claude Code and Codex
plugins/ramtoshiya-cc/                         Claude Code-only skills and hook
```

The rules live only in the guard scripts. `hooks.json` registers them for
Claude Code and Codex.

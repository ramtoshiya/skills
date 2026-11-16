# Agent plugins

This repository has two plugins. `ramtoshiya` works in Claude Code, Codex, and
Hermes Agent. `ramtoshiya-cc` works only in Claude Code. Claude Code and Codex
install both from the marketplace file `.claude-plugin/marketplace.json`, which
also lists the [third-party skills](upstream-skills.md). Hermes loads
`ramtoshiya` as a native plugin from a local clone.

## What the plugins contain

`ramtoshiya` skills:

| Skill | What it does | Needs |
| --- | --- | --- |
| `figma-rest` | Reads Figma files, tokens, and rendered nodes through the REST API instead of the Figma MCP server | A Figma personal access token in the `FIGMA_TOKEN` environment variable, or as a `FIGMA_TOKEN=<token>` line in `~/.config/agent-secrets/figma.env` |
| `excalidraw-board` | Reads and draws on shared excalidraw.com rooms, and exports selected saved objects as PNG | The separately installed `excalidraw-board` command on `PATH`, described in [its README](../tools/excalidraw-board/README.md). PNG export also needs [excalidraw-web-export](../tools/excalidraw-web-export/README.md) and headless Chrome/Chromium |
| `github-actions-authoring` | Checks official releases, a 72-hour cooldown, compatibility, and full commit pins before editing GitHub Actions workflows or action metadata | Git, authenticated `gh` access, `actionlint`, `zizmor`, and the target repository's test runner on `PATH` |
| `imagegen` | Generates and edits images with OpenAI GPT Image or xAI Grok Imagine through an OpenAI-compatible Images API | uv, and an API key or proxy in the environment (see the skill's `SKILL.md`) |
| `impeccable-interview` | Clarifies or resumes a product task and saves approved interview context in an Impeccable surface brief | An already-installed native Impeccable CLI supporting surface-brief v1 and Python 3.11+ (standard library only). See [native engine resolution and validation](../plugins/ramtoshiya/skills/impeccable-interview/README.md) |
| `mermaid-check` | Runs the Mermaid parser over diagrams before the agent delivers them | Node.js. The first run downloads `@mermaid-js/mermaid-cli` 12.0.0 through `npx` |
| `read-x` | Reads public X posts, threads, profiles, and searches through the mdfromx HTTP API | HTTP access to [mdfromx](https://mdfromx.com/) and curl |
| `reorganize-commits` | Rewrites the current branch's commits into reviewable chunks. Runs only when you invoke it | Git |
| `stable-refs` | Gives documents and plans permanent identifiers that survive edits | Nothing |
| `worker-routing` | Supplies the shared model, effort, provider, quota, retry, and escalation policy when another skill or session mode names it. It does not activate lead mode | T3 Code for cross-provider workers. Outside T3, the host's agent tool |

The `codex-session-reader` skill is inactive. Its source remains in
[`dev/disabled-skills/codex-session-reader`](../dev/disabled-skills/codex-session-reader/SKILL.md),
outside the plugin's skill directory. To enable it, move the directory back to
`plugins/ramtoshiya/skills/` and reinstall the plugin.

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
- A Git hygiene check for the moment the agent is about to stop. It ships
  unregistered, so no agent runs it until you add it to `hooks/hooks.json`.
  Hermes has no registration for it.

`ramtoshiya-cc` contains:

- The `claude-design-direct` skill, which edits and previews claude.ai/design
  projects through Claude Code's `DesignSync` tool.
- The `lead` skill, which runs only when you invoke it with `/lead` or
  `/ramtoshiya-cc:lead`. The session then settles the goal and how to check it
  before work starts, and hands work to subagents on the cheapest model and
  effort that can do it. It reads `worker-routing` from the shared `ramtoshiya`
  plugin for that policy. Other modes can read the same policy without activating
  lead's shipping and review workflow. When you tell it to do a piece of work itself, it
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
  Code lists one, and on the session's own instance otherwise. Opus or Fable
  subagents the session starts read the same
  instructions and lead their part of the work. Claude
  Code keeps the instructions in context after compaction.
- The `self-compact` skill and a context budget hook. From 75% of the
  auto-compact window, the hook asks the agent to compact at the next natural
  boundary. The agent writes a handoff note first. In T3 Code it then queues
  `/compact` and a resume message to its own thread, so the work continues
  without you. On macOS Paseo Desktop, a background helper waits for the current
  turn to finish, sends the provider's native `/compact` command, and sends a
  resume instruction only after a completed compaction event tied to that command.
  This proof of concept requires exclusive control of the session and a shell
  tool with background completion notifications. Do not send new prompts until
  the helper finishes. Paseo cannot atomically reject a send when another turn
  starts, so concurrent prompts could be interrupted. The provider must advertise
  `/compact`. The helper uses the installed Desktop bundle's SDK
  and runtime, not extra dependencies. It does not support standalone or remote
  daemons. Set `PASEO_DESKTOP_APP` for a nonstandard bundle location. Other hosts
  use Claude Code's automatic compaction, and the hook points the agent to the
  note afterward.
- A hook that blocks AI attribution lines in commits and pull requests.

Excalidraw board requests update a shared room. A `.excalidraw` attachment is
an export or an agreed fallback, not a replacement for that room. The agent
reports saved content separately from browser display and stops if read-back
content is missing or different. It shares room ids, not secret room links.

The board skill's offline policy evaluations use simulated room state and do
not publish drawings. Run them explicitly with an authenticated Claude Code:

```sh
node dev/evals/excalidraw-skill/run.mjs plugins/ramtoshiya/skills/excalidraw-board/SKILL.md /path/to/eval-results
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
2.1.301, Codex CLI 0.162.1, and Hermes Agent 0.22.5.

## Install

Install the agents themselves from their own instructions:
[Claude Code](https://code.claude.com/docs/en/setup),
[Codex CLI](https://github.com/openai/codex), and
[Hermes Agent](https://hermes-agent.nousresearch.com/docs/getting-started/installation).

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
trust the `ramtoshiya` `PreToolUse` hook. Installing or enabling the
plugin does not trust them. Codex can see `ramtoshiya-cc` in the marketplace, but
it does not work there, so do not install it.

Hermes, from the root of a local clone:

```sh
mkdir -p ~/.hermes/plugins
ln -s "$PWD/plugins/ramtoshiya" ~/.hermes/plugins/ramtoshiya
hermes plugins doctor ~/.hermes/plugins/ramtoshiya --ci
hermes plugins enable ramtoshiya
```

Use an unused destination for the link. Hermes reads
`plugins/ramtoshiya/plugin.yaml` and `plugins/ramtoshiya/__init__.py` through its
[plugin API](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins).
The adapter does the following:

- Registers every skill in `plugins/ramtoshiya/skills/` as `ramtoshiya:<name>`.
  Hermes has no setting that limits a skill to explicit use, so
  `reorganize-commits` is offered to the model like the others. The
  [machine setup](setup.md) disables it in Hermes.
- Runs the package and Python guard before each `terminal` tool call.
- Adds `$HERMES_HOME/AGENTS.md`, or `~/.hermes/AGENTS.md` by default, to new
  sessions as a system prompt section of up to 4,000 characters, when that file
  exists. Hermes does not load this global `AGENTS.md` on its own. The optional
  [machine setup](setup.md) writes it.

Hermes does not read the marketplace file, so this command installs neither
`ramtoshiya-cc` nor the third-party skills. `mise run agents:sync`, described
below, installs the third-party entries selected for Hermes.

To install Claude Code or Codex from a local clone instead, use its path in
place of `ramtoshiya/skills`. Claude Code then loads the plugin from the
checkout, so edits apply after a reload.

Restart the agent after installing, or run `/reload-plugins` in Claude Code.
Hermes reads the plugin and its preferences file only at startup, so restart
it after changing either.

For a local review of third-party updates before changing pins, see
[Plugin update review](../tools/plugin-update-review/README.md). Its
installation targets can invoke the sync task after a person applies a
candidate. Review trust and runtime behavior separately as described below.

## Synchronize a local checkout

For a managed installation of this repository and its selected third-party
packages, run these tasks from the checkout with [mise](https://mise.jdx.dev/getting-started.html):

```sh
mise run agents:status
mise run agents:sync
```

`status` makes no configuration changes or source downloads. Native inventory
commands may refresh their own metadata caches. The task exits nonzero for
missing packages, outdated contents, settings drift, or conflicts. `sync`
reconciles packages for supported agent executables on `PATH`, skipping agents
that are not installed. Use `--host claude`, `--host codex`, or `--host hermes`
to restrict either task. Repeat `--plugin NAME` to limit installation and
retirement to named packages, leaving other managed registrations and user
settings alone. Unknown names are errors. `--json` prints the results as JSON.

When Claude is selected without `--plugin`, both tasks also check or apply
common user settings and instructions across the local Claude profile
registry. Each profile reports both results. Use the shared `~/.claude`
configuration for hosted sessions that should use the same preferences and
plugins. A host can select [claudex](../tools/claudex/README.md) as its
executable to route models per launch without a separate profile. Register
intentionally isolated profiles for policy reconciliation. The registry does
not select a launcher or install plugins. The package installer uses the
active `CLAUDE_CONFIG_DIR` and does not install plugins into every registered
profile. Run `mise run agents:settings:status` or
`mise run agents:settings:sync` for profile policy alone, without native plugin
commands. `mise bootstrap` uses that same settings sync task, so it does not
have different Claude merge rules. [Machine setup](setup.md) owns the profile
format, managed instruction block, common interaction rules, terminal
defaults, and runtime checks.

The marketplace supplies the exact third-party pins. `setup/agents/hosts.json`
selects the hosts for each entry:

| Entry | Hosts |
| --- | --- |
| `ramtoshiya` | Claude Code, Codex, Hermes |
| `ramtoshiya-cc` | Claude Code |
| `omd-kr-writer` | Claude Code, Codex, Hermes |
| `humanize`, `humanize-korean` | Codex, Hermes |
| `open-pencil`, `mattpocock-productivity`, `fcakyon-test-audit`, `ouroboros-interview` | Claude Code, Codex |
| `omd` | None |

Full `omd` is excluded from user-level sync and installed only in explicitly
selected projects. An entry missing from the policy applies to every host.
Adding an entry therefore declares an installation, not just a marketplace
listing, when using these tasks.

Claude Code and Codex use their native plugin commands and a marketplace
registered from this checkout. An existing marketplace registered elsewhere is
reported as a conflict rather than retargeted. Claude's `readFromFolder`, when
present, is its effective installation, even if an older cache still exists.
Native installer results are checked against the approved source files.
Same-version cache problems are reported, never repaired with cache edits.

Hermes has no marketplace command, so sync manages `~/.hermes/plugins/<name>`
directly. A package whose source folder has a Hermes `plugin.yaml`, such as
`ramtoshiya` and `humanize-korean`, is linked there. Sync creates a thin adapter
directory for any other pinned entry. The adapter holds a `plugin.yaml`, an
`__init__.py` copied from `setup/agents/hermes-skills.py`, and a `source.json`
that names the pinned checkout. It registers the pinned skills from that
checkout without copying upstream files. For `humanize`, the adapter also runs
the pinned advisory hook before each matching tool call and appends any warning
to the tool result. It never blocks the call. Sync then runs
`hermes plugins doctor --ci` on the directory and
`hermes plugins enable <name> --no-allow-tool-override`.

An adapter directory that sync did not create has `"managed_adapter": false` in
its `source.json`. Sync keeps its files and updates only `source.json`.

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
For Hermes, sync disables the plugin and keeps its directory. Downloaded
source checkouts are retained.

Sync does not upgrade upstream pins, install agent executables or skill CLIs,
apply other dotfiles, grant hook trust, or restart running sessions. Review
Codex hooks in `/hooks` and restart Claude Code and Hermes after changes.
Finish active Codex turns before installation and coordinate any shared-server
restart as described below. The status table verifies installed files and
configuration, not what an existing session has loaded.

## Check that it works

In each agent, ask it to run these commands:

1. `git status` runs normally.
2. `pip --version` is blocked with a message that points to uv or a virtual
   environment's pip.

In Hermes, `hermes plugins list` shows whether `ramtoshiya` is enabled.

In Claude Code, `/plugin` lists the installed plugins. Each skill should appear
once in the agent's skill list. A loose copy of the same skill, for example in
`~/.claude/skills/` or `~/.agents/skills/`, makes it appear twice.

For each hosted Claude launch, start a fresh session through the actual host.
Check its environment for configuration and routing, including the
`CLAUDE_CONFIG_DIR` value, without exposing credentials. Check loaded
instructions and preferences and plugin and skill visibility. Use `/model`
and the proxy or provider's diagnostics to check the intended model and where
a request is sent. A settings check alone does not show what the session loaded
or where it sends requests.

## Update

The plugins have no `version` field, so Claude Code treats each commit of the
marketplace repository as a new version.

| Agent | Update command |
| --- | --- |
| Claude Code | `claude plugin marketplace update ramtoshiya`, then `claude plugin update ramtoshiya@ramtoshiya` (and `ramtoshiya-cc@ramtoshiya`) and a restart |
| Codex | Follow the source refresh, installation, and restart steps below. Changed hooks need your trust again in `/hooks` |
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
.claude-plugin/marketplace.json            Marketplace read by Claude Code and Codex
plugins/ramtoshiya/.claude-plugin/plugin.json  Plugin manifest, read by Claude Code and Codex
plugins/ramtoshiya/skills/                     Skills
plugins/ramtoshiya/hooks/global-package-guard.py   Package and Python rules
plugins/ramtoshiya/hooks/git-hygiene-guard.py      Stop check, not registered
plugins/ramtoshiya/hooks/hooks.json            Hook registration for Claude Code and Codex
plugins/ramtoshiya/plugin.yaml                 Hermes native plugin manifest
plugins/ramtoshiya/__init__.py                 Hermes skills, preferences, and guard adapter
plugins/ramtoshiya-cc/                         Claude Code-only skills and hooks
setup/agents/hermes-skills.py                  Template for Hermes adapters of third-party entries
```

The rules live only in the guard scripts. `hooks.json` registers them for
Claude Code and Codex. The Hermes adapter passes each `terminal` call to the
package guard and translates the answer. Each skill under `skills/` also needs
an entry in the adapter's `SKILLS` map. A test checks that every shipped skill
is listed.

# Agent plugins

This repository has two plugins. `ramtoshiya` works in Claude Code and Codex.
`ramtoshiya-cc` works only in Claude Code. Both agents install them from the
marketplace file `.claude-plugin/marketplace.json`, which also lists the
[third-party skills](upstream-skills.md).
The Hermes operator profile gets copies of seven pstack-mode skills and of
the skills from every other entry, as [Machine setup](setup.md) describes. It
does not run the hooks.

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
| `self-compact` | Compacts the conversation at a boundary the agent picks and resumes from a handoff note without you | BB with Claude Code or Hermes, or macOS Paseo Desktop. Node.js and the `bb` CLI in BB |
| `stable-refs` | Gives documents and plans permanent identifiers that survive edits | Nothing |
| `worker-routing` | Supplies the shared model, effort, provider, quota, urgency, retry, and escalation policy that agents follow when they start workers, and a `newest-model` script that prints the model to pass for each family | BB for cross-provider workers, and for Claude workers when the host hides Claude Code's own subagent tools. Elsewhere, the host's agent tool. `jq`, and the `bb` CLI for the `claudex` catalog |

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

The `self-compact` skill compacts the conversation earlier than the host would,
at a boundary the agent picks. A context budget reminder asks for it from 75%
of the compaction window. In Claude Code the reminder comes from the
`ramtoshiya-cc` hook. In the Hermes operator profile it comes from that
profile's self-compact plugin, described in [Machine setup](setup.md). The
agent finishes its step and writes a handoff note first.

- In BB a helper uses the installed `bb` CLI and Node.js to wait for the turn
  to end and request native compaction. It sends the resume only after the
  matching turn reports an actual compaction boundary and successful
  completion. In the `claude-code` provider, the agent launches the helper as a
  Bash background task with completion notifications. The helper allows input
  BB already accepted into the active turn before preparation. New input during
  preparation still stops the helper. The helper also supports Hermes,
  which launches it through the profile's `self_compact` tool. For Hermes it
  also requires the one compaction that Hermes committed after the request,
  because BB reports a refused or empty `/compact` as finished too. Other
  providers, pending work, interactions, and missing proof keep the handoff
  note and stop the helper. A queued resume receipt reports uncertain delivery
  and its queue id. The helper needs exclusive control of the thread. Do not
  send new prompts until it finishes. The CLI cannot atomically send only if
  no new work arrived after the last check.
- On macOS Paseo Desktop, a background helper waits for the current turn to
  finish, sends the provider's native `/compact` command, and sends a resume
  instruction only after a completed compaction event tied to that command.
  This proof of concept requires exclusive control of the session and a shell
  tool with background completion notifications. Do not send new prompts until
  the helper finishes. Paseo cannot atomically reject a send when another turn
  starts, so concurrent prompts could be interrupted. The provider must
  advertise `/compact`. The helper uses the installed Desktop bundle's SDK and
  runtime, not extra dependencies. It does not support standalone or remote
  daemons. Set `PASEO_DESKTOP_APP` for a nonstandard bundle location.
- Other hosts use their automatic compaction. The Claude Code hook points the
  agent to the note afterward.

The `worker-routing` skill is the one policy for choosing a worker's model.

- Every model an agent passes comes from the skill's `scripts/newest-model
  <family> [<provider>]`. For Claude families it prints the family alias, such
  as `opus`, which Claude Code resolves to the family's newest model. For the
  GPT families Luna, Terra, and Sol it prints the newest
  `gpt-<version>-<family>` ID in the Codex catalog
  (`~/.codex/models_cache.json`) or, with `claudex`, in bb's claudex catalog.
  It prints nothing and exits 1 when that catalog has no model of the family.
  In bb, the [newest-model-guard](../bb-plugins/newest-model-guard/README.md)
  plugin rejects an agent-started thread whose model is older than one the
  catalog lists.
- Work is urgent when you say so, or, at the agent's judgement, when a shared
  gate such as `main`'s check stopped landing on two or more branches. Urgent
  work runs on Claude, and a top-tier row moves from Opus to Fable. A running
  GPT worker is handed off to a new Claude thread in the same environment.
  For anything else the agent proposes urgency to you instead of switching.
- The file `~/.config/ramtoshiya/worker-route.json` decides where Haiku- and
  Sonnet-level workers run in bb. With `{"workers": "codex"}` or
  `{"workers": "claudex"}` they run on GPT Luna and Terra models through that
  provider. Without the file they run on Claude. Opus-level work stays on
  Claude, except that a Terra worker whose task outgrew it reruns on GPT Sol
  through the same provider.
- bb reads weekly quota through its enabled Provider usage plugin's read-only
  `getUsage` RPC on the thread's machine, with a five-minute cache allowance.
  Other hosts, and bb when that lookup is unavailable, use the `quotio-cli`
  command from [Machine setup](setup.md). When 90% or more of the route's
  weekly quota is used, or a worker hits a usage limit, workers move to the
  other side and the agent says so. Urgent work ignores the 90% rule.
- In bb, the Claude Code provider setting `subagentsDisabled` hides the
  `Agent`, `Task`, and `ListAgents` tools. The agent then starts every worker
  with `bb thread spawn` as a child thread, waits for bb's notification that
  the child finished, and archives the child afterward. The `~/.bb/AGENTS.md`
  file from [Machine setup](setup.md) lets it start those workers without
  asking you each time.

`ramtoshiya` hooks, described in [Hooks](hooks.md):

- A package and Python guard that checks each shell command before it runs.
- A Python module hint that points a failed import at `uv run --with` after a
  shell command.
- A Git hygiene check for the moment the agent is about to stop. It ships
  unregistered, so no agent runs it until you add it to `hooks/hooks.json`.

`ramtoshiya-cc` contains:

- The `claude-design-direct` skill, which edits and previews claude.ai/design
  projects through Claude Code's `DesignSync` tool.
- A context budget hook for the shared `self-compact` skill. From 75% of the
  numeric `autoCompactWindow` setting, it asks the agent once per five-point
  band to compact at the next natural boundary. After a compaction it points
  the agent to the handoff note.
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
trust the `ramtoshiya` `PreToolUse` and `PostToolUse` hooks. Installing or enabling the
plugin does not trust them. Codex can see `ramtoshiya-cc` in the marketplace, but
it does not work there, so do not install it.

To install Claude Code or Codex from a local clone instead, use its path in
place of `ramtoshiya/skills`. Claude Code then loads the plugin from the
checkout, so edits apply after a reload.

Restart the agent after installing, or run `/reload-plugins` in Claude Code.

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

Once `mise run main:sync` has run in the checkout, a Git hook runs `sync`
after every change to `main`, as [Machine setup](setup.md) describes.
`status` makes no configuration changes or source downloads. Native inventory
commands may refresh their own metadata caches. The task exits nonzero for
missing packages, outdated contents, settings drift, or conflicts. `sync`
reconciles packages for supported agent executables on `PATH`, skipping agents
that are not installed. Use `--host claude`, `--host codex`, or
`--host hermes` to restrict either task. Hermes gets only the common
instructions, as [Machine setup](setup.md) describes. Repeat `--plugin NAME` to limit installation and
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
| `ramtoshiya` | Claude Code, Codex |
| `ramtoshiya-cc` | Claude Code |
| `omd-kr-writer` | Claude Code, Codex |
| `humanize`, `humanize-korean` | Codex |
| `open-pencil`, `mattpocock-productivity`, `fcakyon-test-audit`, `ouroboros-interview`, `pstack-mode` | Claude Code, Codex |
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
apply other dotfiles, grant hook trust, or restart running sessions. Review
Codex hooks in `/hooks` and restart Claude Code after changes.
Finish active Codex turns before installation and coordinate any shared-server
restart as described below. The status table verifies installed files and
configuration, not what an existing session has loaded.

## Check that it works

In each agent, ask it to run these commands:

1. `git status` runs normally.
2. `pip --version` is blocked with a message that points to uv or a virtual
   environment's pip.

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
plugins/ramtoshiya/hooks/python-module-hint.py     uv hint after a failed import
plugins/ramtoshiya/hooks/git-hygiene-guard.py      Stop check, not registered
plugins/ramtoshiya/hooks/hooks.json            Hook registration for Claude Code and Codex
plugins/ramtoshiya-cc/                         Claude Code-only skills and hooks
```

The rules live only in the guard scripts. `hooks.json` registers them for
Claude Code and Codex.

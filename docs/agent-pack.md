# Agent plugins

This repository has two Claude Code plugins, `ramtoshiya` and `ramtoshiya-cc`.
Claude Code installs them from the marketplace file
`.claude-plugin/marketplace.json`, which also lists the
[third-party skills](upstream-skills.md). The marketplace also lists
`background-tools`, the Claude Code half of the
[background-tools bb plugin](../bb-plugins/background-tools/README.md), which
documents it.

## What the plugins contain

`ramtoshiya` skills:

| Skill | What it does | Needs |
| --- | --- | --- |
| `figma-rest` | Reads Figma files, tokens, and rendered nodes through the REST API instead of the Figma MCP server | A Figma personal access token in the `FIGMA_TOKEN` environment variable, or as a `FIGMA_TOKEN=<token>` line in `~/.config/agent-secrets/figma.env` |
| `excalidraw-board` | Reads and draws on shared excalidraw.com rooms, and exports selected saved objects as PNG | The separately installed `excalidraw-board` command on `PATH`, described in [its README](../tools/excalidraw-board/README.md). PNG export also needs [excalidraw-web-export](../tools/excalidraw-web-export/README.md) and headless Chrome/Chromium |
| `github-actions-authoring` | Checks official releases, a 72-hour cooldown, compatibility, and full commit pins before editing GitHub Actions workflows or action metadata | Git, authenticated `gh` access, `actionlint`, `zizmor`, and the target repository's test runner on `PATH` |
| `visible-chrome` | Opens a persistent visible Chrome profile for user sign-in and CDP automation. `dev/verification/visible-chrome/focus.sh virtual` or `focus.sh fallback` opens, reuses, and closes a profile in corner placement, checks that the frontmost app never changes and that the page reports visible, not WebDriver, and ticking, then checks that front placement brings Chrome to the front. `virtual` also requires the BetterDisplay virtual display, and `fallback` stubs the BetterDisplay CLI to fail. It drives the desktop, so first take a turn with `takeaturn desktop` | macOS, Google Chrome, and Node.js with built-in WebSocket support. BetterDisplay, its CLI, and Swift are optional for unattended placement. |
| `imagegen` | Generates and edits images with OpenAI GPT Image or xAI Grok Imagine through an OpenAI-compatible Images API | uv, and an API key or proxy in the environment (see the skill's [setup routes](../plugins/ramtoshiya/skills/imagegen/references/setup.md)) |
| `impeccable-interview` | Clarifies or resumes a product task and saves approved interview context in an Impeccable surface brief | An already-installed native Impeccable CLI supporting surface-brief v1 and Python 3.11+ (standard library only). See [native engine resolution and validation](../plugins/ramtoshiya/skills/impeccable-interview/README.md) |
| `mermaid-check` | Runs the Mermaid parser over diagrams before the agent delivers them | Node.js. The first run downloads `@mermaid-js/mermaid-cli` 12.0.0 through `npx` |
| `read-x` | Reads public X posts, threads, profiles, and searches through the mdfromx HTTP API | HTTP access to [mdfromx](https://mdfromx.com/) and curl |
| `reorganize-commits` | Rewrites the current branch's commits into reviewable chunks. Runs only when you invoke it | Git |
| `self-compact` | Compacts the conversation at a boundary the agent picks and resumes from a handoff note without you | BB with Claude Code, or macOS Paseo Desktop. Node.js and the `bb` CLI in BB |
| `stable-refs` | Gives documents and plans permanent identifiers that survive edits | Nothing |
| `windowserver-ports` | Keeps tools on macOS from filling WindowServer's Mach port space, which logs the user out: which processes connect, how to deny file-only processes, how to measure dead names, and how to check a macOS update for a fix | macOS. Exact counts need `sudo lsmp`. Checking how close the Mac is needs the separately installed [windowserver-ports](../tools/windowserver-ports/README.md) command on `PATH` |
| `worker-routing` | Supplies the shared model, effort, provider, quota, urgency, retry, and escalation policy that agents follow when they start workers, a `newest-model` script that prints the model to pass for each family, and a `quota-pace.py` script that picks the side for new work from recent quota use | BB for cross-provider workers, and for Claude workers when the host hides Claude Code's own subagent tools. Elsewhere, the host's agent tool. `jq`, and the `bb` CLI for the `claudex` catalog. uv for `quota-pace.py`, which reads Quotio's history when the Quotio app records it |

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
`ramtoshiya-cc` hook. The agent finishes its step and writes a handoff note first.

- In BB a helper uses the installed `bb` CLI and Node.js to wait for the turn
  to end and request native compaction. It sends the resume only after the
  matching turn reports an actual compaction boundary and successful
  completion. In the `claude-code` provider, the agent launches the helper as a
  Bash background task with completion notifications. The helper allows input
  BB already accepted into the active turn before preparation. New input during
  preparation still stops the helper. Other providers, pending work, interactions, and missing proof keep the handoff
  note and stop the helper. Queued work before the request stops it, but
  messages that the mail bb plugin holds in a thread's inbox do not count.
  Messages that queue after the compaction request
  do not stop it. A queued resume receipt reports uncertain delivery
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
  `gpt-<version>-<family>` ID in bb's claudex catalog.
  It prints nothing and exits 1 when that catalog has no model of the family.
  In bb, the [newest-model-guard](../bb-plugins/newest-model-guard/README.md)
  plugin rejects an agent-started thread whose model is older than one the
  catalog lists.
- Work is urgent when you say so, or, at the agent's judgement, when a shared
  gate such as `main`'s check stopped landing on two or more branches. Urgent
  work runs on Claude, and a top-tier row moves from Opus to Fable. A running
  GPT worker is handed off to a new Claude thread in the same environment.
  For anything else the agent proposes urgency to you instead of switching.
- In bb, judgment stays on Claude: work that no test, reproduction,
  measurement, or fixed acceptance criteria can check, and decisions that are
  hard to undo, such as a design direction or a file format. Other work, at
  the Sonnet or Opus level, may run on Claude or on GPT Terra or Sol models
  through `claudex`, which draws on the Codex account's GPT quota.
- bb reads weekly quota through its enabled Provider usage plugin's read-only
  `getUsage` RPC on the thread's machine, with a five-minute cache allowance.
  Before each batch of new workers, the skill's `quota-pace.py` reads the GPT
  side from `codex app-server`, which bb's usage lookup omits while its Codex
  provider is disabled. It reads a Claude side that lookup missed, and any side
  on other hosts that `codex app-server` does not supply, from the
  `quotio-cli` command in [Machine setup](setup.md). It estimates how much
  of Claude's remaining week the Opus and Fable work will use, from Claude
  Code transcripts. Work that may run on either side goes to Claude only when
  Claude has room that this work will leave unused at its reset, and
  otherwise to GPT. Unclaimed Codex reset credits count as GPT room. A side with a usage limit
  or without a current reading takes no work. A running worker that hits a usage limit moves the same way,
  by handoff to a new thread, without asking you first. Claude's reported 100% can be a rounded
  reading, so Claude stays eligible until a request hits a usage limit. A Codex
  reading of 100% marks Codex limited. A side that hit a limit comes back when
  a reading shows its quota renewed, or after the reset time that a shorter
  limit's error named. Urgent work stays on Claude and moves only on a limit.
- When no eligible side can take a worker, including when the other side
  has no current reading after a limit, the agent reports the blocked
  role, each side's scheduled reset, and the reset credits it can see: Codex
  credits from `codex app-server`, and Claude offers only when you name
  them. Only you redeem a reset credit. The agent never redeems one.
- In bb, the Claude Code provider setting `subagentsDisabled` hides the
  `Agent`, `Task`, and `ListAgents` tools. The agent then starts every worker
  with `bb nest spawn` from the [nest](../bb-plugins/nest/README.md) bb
  plugin, which works at any thread depth. It waits for the notification that
  the worker finished, and archives the worker afterward. The `~/.bb/AGENTS.md`
  file from [Machine setup](setup.md) lets it start those workers without
  asking you each time.

`ramtoshiya` hooks, described in [Hooks](hooks.md):

- A package and Python guard that checks each shell command before it runs.
- A commit attribution guard that blocks AI attribution lines in commits and
  pull requests.
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
- The `hermes-learning` command and two hooks, which give every Claude Code
  session the memory and skills of a Hermes profile. The next section
  describes them.

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

### Hermes learning in Claude Code

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) profile stores
what agents learn: `memories/USER.md` and `memories/MEMORY.md`, skills under
`skills/` with their use counts in `skills/.usage.json`, and the curator that
archives skills nobody uses. `ramtoshiya-cc` connects Claude Code sessions,
including claudex sessions, to the profile at `~/.hermes/profiles/coder`. Set
`HERMES_LEARNING_HOME` to use another profile directory. Create the profile
once with `hermes profile create coder --no-skills --no-credentials --no-alias`.
Only the store is used. No Hermes agent runs in it.

- When a session starts, a hook adds the profile's `USER.md` and `MEMORY.md`
  to its context. The skills load as the `hermes-skills` plugin through the
  `CLAUDE_CODE_PLUGIN_DIRS` user setting that the [machine setup](setup.md)
  writes. A Skill tool use of one of them counts in `skills/.usage.json`.
  [Hooks](hooks.md) has the details.
- The `hermes-learning` command runs Hermes's own `memory`, `skill_manage`,
  and `skill_view` tools, so Hermes's validation, size limits, security scan,
  and usage records apply. Agents run it through Bash. `hermes-learning schema
  <tool>` prints a tool's arguments, and `hermes-learning <tool>` takes the
  arguments as JSON on stdin. A call takes about one second for `memory` and
  two for the skill tools.
- It is a command and not an MCP server because of claudex. Loading an MCP
  tool through ToolSearch changes the request's tool list, and the claudex
  proxy route then misses the prompt cache for the whole conversation. A Bash
  call leaves the tool list unchanged.
- The session start hook adds the learning instructions with the command's
  full path, and starts Hermes's curator in the background, because no Hermes
  agent runs for the profile otherwise. The curator acts once its interval has
  passed and makes no model calls by default. It moves skills nobody uses to
  stale and then to the archive.
- The agent decides when to learn. The instructions tell it to record a lesson
  that a person or an agent in the conversation stated, or a tool result
  showed. In bb, when a whole conversation is worth reviewing, it starts a
  review with `bb thread fork "$BB_THREAD_ID" --lifecycle-owner-thread
  "$BB_THREAD_ID" --title "Hermes review" --prompt-file
  <plugin>/hermes-learning/review.md`. The fork appears in bb as a thread and
  reuses the source's prompt cache. It records lessons, sends changes to files
  in the working checkout as proposals, and mails a summary to the source with
  `bb mail send` without waking it. Outside bb the agent records directly.
- The instructions place a lesson by its scope. A lesson that matters only
  for one class of task, including your preferences for that kind of work,
  goes into the skill that governs that class, because every session loads
  memory whatever its task. Memory keeps short facts that every session needs.
- Sessions and review forks only add memory entries when they can. Hermes
  stages a review fork's removal or rewrite of an entry, and refuses an entry
  that does not fit. A bb automation in this repository's project runs
  `dev/automation/memory-consolidation/check.py` every day at 05:30 Asia/Seoul.
  When `MEMORY.md`, `USER.md`, or a learned skill changed since the last
  consolidation, or a write is staged, it starts a Full Access thread titled
  `Hermes memory consolidation <date>`. Otherwise it prints nothing and no
  model runs. The thread decides each staged write with `hermes-learning
  pending`, keeps each memory entry that every session needs, moves each
  entry that serves one class of task into that class's skill, drops entries
  that `~/.claude/CLAUDE.md` or a skill already says, and shortens a target
  still at 80% of its limit or more down to 60%. It then runs `check.py
  --mark`, which records the store's state in `consolidated.json` in the
  profile, so the next check counts only later changes. Its reply lists every
  changed entry in full with the reason and every skill change, so a person
  can ask for any of them back. Nobody approves its changes first.

The command and the session start hook read the session's bb thread and pick a
role:

| Session | Instructions | Tools | Writes as |
| --- | --- | --- | --- |
| A bb thread that another thread started (it has a parent) | End the final answer with `Learning proposals` | `skill_view` only | Nothing |
| A bb fork titled `Hermes review` | The fork's prompt | All three | Hermes's `background_review` origin, which adds its review-only checks and marks new skills as agent-created for the curator |
| Any other session, in or outside bb, including a fork made for other work | Record lessons. In bb, also start review forks | All three, and `pending` for staged writes | `foreground` |

The command needs Hermes's `hermes` command, on `PATH` or at
`~/.hermes/hermes-agent/.hermes/bin/hermes`, and the profile directory, and it
names whichever is missing. It writes outside the workspace, so in bb it needs
the Full Access permission mode. bb's other modes run Bash in Claude Code's
sandbox, which refuses those writes. A review fork and a child thread inherit
the mode of the thread that started them.

## Requirements

The package guard, the commit attribution guard, the Python module hint, and
the context budget hook are one Go program that you build in a clone of this repository with [mise](https://mise.jdx.dev/getting-started.html),
as Install describes. The other hooks run with
[uv](https://docs.astral.sh/uv/getting-started/installation/)
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

The Go program compiles in two modules pinned to exact versions,
`mvdan.cc/sh/v3` and `github.com/BurntSushi/toml`. The plugins have no other
third-party dependencies. Tested with Claude Code 2.1.332.

## Install

Install [Claude Code](https://code.claude.com/docs/en/setup) from its own
instructions.

Git does not track the hook binary, so install from a local clone where it is
built. A marketplace added straight from GitHub has no binary, and its hooks
fail on every call. Clone the repository and build the binary:

```sh
git clone https://github.com/ramtoshiya/skills.git
cd skills
mise install --locked
mise run hooks:build
```

Then, from the clone:

```sh
claude plugin marketplace add "$PWD"
claude plugin install ramtoshiya@ramtoshiya --scope user
claude plugin install ramtoshiya-cc@ramtoshiya --scope user
```

Claude Code loads the plugins from the clone, so edits apply after a reload.
Restart Claude Code after installing, or run `/reload-plugins`.

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
missing packages, outdated contents, settings drift, or conflicts. Both tasks
report Claude Code as absent when `claude` is not on `PATH`. Repeat `--plugin NAME` to limit installation and
retirement to named packages, leaving other managed registrations and user
settings alone. Unknown names are errors. `--json` prints the results as JSON.

Without `--plugin`, both tasks also check or apply
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

The marketplace supplies the exact third-party pins, and the tasks install
every entry. Adding an entry therefore declares an installation, not just a
marketplace listing, when using these tasks.

The tasks use Claude Code's native plugin commands and a marketplace
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
the files. Preserve the customization in a fork or resolve it manually
before retrying. After adoption, local changes to a managed installation also
produce a conflict.

Removing a declared package retires only its recorded registrations with
`claude plugin uninstall`, keeping the plugin's persistent data. Downloaded
source checkouts are retained.

Claude Code runs an installed plugin's hooks without a person approving them,
so review a hook before its plugin's pin reaches `main`.

Sync does not upgrade upstream pins, install agent executables or skill CLIs,
apply other dotfiles, or restart running sessions. Restart Claude Code after
changes. The status table verifies installed files and
configuration, not what an existing session has loaded.

## Check that it works

In Claude Code, ask the agent to run these commands:

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
marketplace repository as a new version. Update the clone, run
`mise run hooks:build`, and restart Claude Code. If a session reports a missing
plugin file after an update, restart that session rather than repairing the
cache.

Do not repair a missing plugin version with cache edits or links to another
version. Use the install and runtime lifecycle above. For versioned third-party
plugins, also follow [Third-party skills](upstream-skills.md).

## How the files fit together

```text
.claude-plugin/marketplace.json            Marketplace read by Claude Code
plugins/ramtoshiya/.claude-plugin/plugin.json  Plugin manifest
plugins/ramtoshiya/skills/                     Skills
plugins/ramtoshiya/hooks/*.go, guard/, shell/  Go source of the hook program
plugins/ramtoshiya/hooks/ramtoshiya-hooks      The hook binary, built from that source and ignored by Git
plugins/ramtoshiya/hooks/git-hygiene-guard.py      Stop check, not registered
plugins/ramtoshiya/hooks/hooks.json            Hook registration
plugins/ramtoshiya-cc/                         Skills and hooks of the `ramtoshiya-cc` plugin
plugins/ramtoshiya-cc/hooks/ramtoshiya-hooks   The same hook binary, built for `ramtoshiya-cc`
plugins/ramtoshiya-cc/hermes-learning/         Hermes learning command, hooks, and review prompt
```

The rules live only in the Go program and the hook scripts. `hooks.json`
registers them for Claude Code.

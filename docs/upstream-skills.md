# Third-party skills

The marketplace file `.claude-plugin/marketplace.json` lists a few skills from
other repositories next to this repository's own plugins. Each entry points at
the upstream repository, or at a fork when the skill needed changes, and pins
an exact commit. The skill files, their licenses, and their history stay in
those repositories. This repository holds none of them.

## Included skills

| Entry | Skills | Source | License |
| --- | --- | --- | --- |
| `mattpocock-productivity` | `grilling`, `grill-me`, `handoff` | `skills/productivity` in the fork [ramtoshiya/mattpocock-skills](https://github.com/ramtoshiya/mattpocock-skills) | MIT |
| `fcakyon-test-audit` | `test-audit` | `plugins/test-audit/skills` in the fork [ramtoshiya/claude-codex-settings](https://github.com/ramtoshiya/claude-codex-settings) | MIT |
| `ouroboros-interview` | `interview`, `unstuck` | `plugins/ouroboros-interview` in the fork [ramtoshiya/ouroboros](https://github.com/ramtoshiya/ouroboros) | MIT |
| `pstack-mode` | `/pstack-mode:mode` and the pstack workflows and principles it selects | `plugins/pstack-mode` in [ramtoshiya/pstack-mode](https://github.com/ramtoshiya/pstack-mode), generated from [backnotprop/pstack](https://github.com/backnotprop/pstack) | MIT |

`grill-me` and `handoff` run only when you invoke them, so the agent's own
skill list shows only `grilling`. Installed skills carry the entry name as a
prefix, for example `mattpocock-productivity:grilling`.

The productivity fork preserves decision-tree rounds while recording obvious
defaults under **Assumed (override if wrong)** instead of asking for individual
approval. Questions must ask something explicitly. Only yes/no questions use
"yes" to accept the recommendation, and multiple-choice recommendations name
the option. The patches follow [the upstream question-format fix](https://github.com/mattpocock/skills/issues/1249#issuecomment-6120835958)
and [the list-and-veto preference](https://github.com/mattpocock/skills/issues/1112#issuecomment-6186224765).
The update agent described below points the entry back at
`mattpocock/skills` when that issue closes or upstream's `grilling` covers
this behavior.

`test-audit` runs automatically when writing or changing tests and when the
requested work assesses test quality, including read-only audits. The fork
excludes test reads used as evidence for research, diagnosis, source review,
packaging, and validation planning. A research assignment does not become a
test audit because its parent workflow will later change tests.
Its audit discovery step runs a bundled read-only script that needs Node 22 or
later. The script lists candidates from the files in the repository and makes no
network calls.

`ouroboros-interview` packages the interview and unstuck skills with their
bundled review and lateral-thinking prompts. Both use the host's native tools
and need no additional runtime or server. Interview ends with an agreed
requirements summary. Unstuck examines repeated failures or consequential
decisions through hacker, researcher, simplifier, architect, and contrarian
perspectives before recommending one next move. Neither skill loads the fork's
root plugin, starts implementation, changes agent configuration, or checks for
updates. Results stay in the conversation unless you request a summary file.
Invoke `/ouroboros-interview:interview` or `/ouroboros-interview:unstuck` in
Claude Code after installing the entry.

The `claude-codex-settings` repository is Apache-2.0, and the `test-audit`
folder has its own MIT `LICENSE`.

`pstack-mode` is a generated package, not a plain fork. Its repository keeps
an unchanged pstack mirror under `upstream/` and a generator that writes
`plugins/pstack-mode/`. Its README and docs describe the selection, activation,
and build. The mode reads `ramtoshiya:worker-routing`, so a host that installs
`pstack-mode` also needs the `ramtoshiya` plugin. To update the pin, push the
rebuilt `main` of `ramtoshiya/pstack-mode` and set the entry's `sha` to that
commit. A change that touches both repositories therefore lands in two
commits, first in `pstack-mode`, then the pin here.

## Install

To keep all installed supported hosts on the marketplace's approved pins, use
`mise run agents:status` and `mise run agents:sync` from a local checkout.
[Agent plugins](agent-pack.md) describes the managed installation, including
conflict handling. The commands below install individual
entries in Claude Code and Codex without enrolling them in that workflow.

Claude Code and Codex read the marketplace. After adding it as described in
[Agent plugins](agent-pack.md), install each entry by name:

```sh
claude plugin install mattpocock-productivity@ramtoshiya --scope user
codex plugin add mattpocock-productivity@ramtoshiya
```

A loose copy of the same skill makes it load twice, as described in
[Agent plugins](agent-pack.md).

The Hermes operator profile gets the same skill selections, without the
hooks, from the copies `mise run agents:sync` fetches. A pin update pushed to
`origin/main` runs both installers through `main:sync`, as
[Machine setup](setup.md) describes.

## Add an entry

Use a `git-subdir` entry to take some skills from an upstream repository
unchanged:

```json
{
  "name": "mattpocock-productivity",
  "source": {
    "source": "git-subdir",
    "url": "mattpocock/skills",
    "path": "skills/productivity",
    "sha": "<40-character commit>"
  },
  "skills": ["./grilling"],
  "author": { "name": "Matt Pocock" },
  "repository": "https://github.com/mattpocock/skills",
  "license": "MIT"
}
```

`author`, `repository`, and `license` are display fields. `/plugin` in Claude
Code shows them before installing. To change a skill, fork the upstream
repository, commit the changes in the fork, and point the entry at the fork's
commit. A whole upstream plugin that needs no changes belongs in its own
marketplace, not here.

Claude Code and Codex behaved like this in tests with Codex CLI
0.158.0-alpha.2.1. Recheck when an entry does not load as expected:

- `path` must be a folder that contains skill folders. A path to a single skill
  folder with `"skills": ["./"]` loads in Claude Code and loads nothing in
  Codex.
- If the source folder has its own `plugin.json`, that file decides which
  skills load. The entry's `skills` list cannot narrow it: Claude Code adds the
  list to it. Choosing fewer skills needs a fork with an edited `plugin.json`.
- Codex refuses an entry whose `name` differs from the `name` in the source's
  `plugin.json`.
- A `git-subdir` install copies only `path`. A `LICENSE` at the repository
  root is not in the installed copy unless the folder has its own.
- Both agents install the whole `path` folder and load only the listed skills.

## Automatic updates

A daily bb automation keeps the third-party entries level with their
upstreams. No person reviews an update before it installs.

At 05:00 Asia/Seoul the automation runs
`node dev/automation/upstream-updates/updates.mjs check` in the shared
checkout. For each `git-subdir` entry, the check fetches the entry's source
repository and the upstream that
[upstreams.json](../dev/automation/upstream-updates/upstreams.json) names. It
keeps these mirrors in `~/.cache/ramtoshiya/upstream-updates/`. The newest
upstream commit that the pinned commit contains is the last handled one. An
entry is out of date in three cases:

- Upstream changed a file under one of the entry's `watch` paths since the
  last handled commit.
- Upstream added a skill under one of its `newSkillsIn` paths.
- The pinned commit is not on the entry's `branch`.
- The issue named in the entry's `retireWhenClosed` is closed and the entry
  still points at its fork. The check reads the issue with `gh`.

Upstream commits that touch only other paths do not count. When every entry is
current, the run prints nothing and bb records it as a skipped run. Otherwise
the check starts one agent thread in a new worktree of `main`. The thread gets
[the update instructions](../dev/automation/upstream-updates/agent-prompt.md)
and the check's findings. The check chooses the agent's provider and model at
run time with the `worker-routing` skill's `sonnet` `high` row and its quota
script. If the check itself fails, it sends a bb notification and exits
nonzero, so bb records a failed run.

The pins are the only state. A merge of an upstream commit into the fork,
pinned here, marks that commit as handled. A refused upstream change is still
merged, and the merge leaves out what was refused. An entry the agent cannot
finish keeps its old pin, so the next day's check starts a new run for it.

The agent merges upstream into each fork and never rebases or force-pushes. It
keeps the intent of each fork change unless upstream made the change
unnecessary or conflicts with it, and records why in the fork's commit. It
always refuses telemetry and judges other new behavior, such as network calls,
broader triggering, or hooks, against the skill's purpose. A hook it keeps
runs in Codex without a person's approval, because `main:sync` trusts the
hooks it installs. It does not add new
upstream skills. It runs the fork's checks, pins the merge, runs this
repository's checks, and pushes to `origin/main`, which installs the update
through `main:sync`. Its final reply in the thread is an HTML summary of the
day's changes, and it sends a bb notification that opens the thread.

`node dev/automation/upstream-updates/updates.mjs verify` checks the pins in
the working tree before a push. Each pinned commit must be on its branch, each
listed skill must have a `SKILL.md`, and a manifest `version` must change when
the pinned folder changed.

To add an entry, add a record under its name to `upstreams.json`:

| Field | Value |
| --- | --- |
| `branch` | The branch of the entry's source repository that holds the pin |
| `upstream` | The upstream repository, as `owner/repository` |
| `upstreamBranch` | The upstream branch to follow |
| `watch` | Upstream paths whose changes reach the pinned folder |
| `newSkillsIn` | Optional. Upstream folders where a new skill is reported. Defaults to `watch` |
| `retireWhenClosed` | Optional. An upstream issue, as `owner/repository#number`, whose closing should end the fork |

`npm test` fails when a `git-subdir` entry has no record. Create or update the
automation with `mise run upstream-updates:automation`, as
[Machine setup](setup.md) describes.

## Change a pin by hand

The update agent follows these steps. Follow them too when you change a fork
yourself.

1. Read the upstream diff for the entry's folder between the pinned commit and
   the new one. Check removed or renamed files, new dependencies, license
   changes, hook behavior, and changes to the skill's instructions.
2. For a fork, merge upstream into the fork first. Never rebase the fork
   branch, because a pin that leaves the branch can disappear. Git reporting no conflict is
   not enough: an upstream change can still undo the intent of a fork change.
   Each fork commit message should say why the change exists, so a later merge
   can tell a customization from an accident.
3. If the fork's plugin manifests have a `version`, bump it when releasing
   changed plugin contents. Keep the version consistent across the agent
   manifests. Claude Code and Codex label an install with this
   version, not the marketplace's commit SHA.
4. Change `sha` in the entry, and `path` if upstream moved the folder. That
   commit is the release. Run
   `node dev/automation/upstream-updates/updates.mjs verify`.
5. Push the change to `origin/main`. For managed installations, `main:sync`
   then runs `mise run agents:sync`, which also trusts the entry's hooks in
   Codex. Reload or restart each changed host. For manual installations,
   reinstall where needed:
   - Claude Code: `claude plugin marketplace update ramtoshiya`, then
     `claude plugin update <entry>@ramtoshiya` and reload or restart.
   - Codex: finish active turns and close sessions using the plugin. For a
     Git-backed marketplace, run `codex plugin marketplace upgrade ramtoshiya`.
     For a local marketplace, update its checkout instead. Then run
     `codex plugin add <entry>@ramtoshiya`. Start a fresh process and trust the entry's
     hooks in `/hooks`. [Agent plugins](agent-pack.md) covers the runtime
     lifecycle, including shared-server considerations.
6. Check that the installed manifest version and `hooks/hooks.json` match the
   selected commit. A displayed version alone does not prove that the installed
   files or an active runtime are current. Reusing a manifest version can keep
   changed fork contents from reaching an installed copy.

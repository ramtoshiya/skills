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
Return the entry to `mattpocock/skills` after issue #1249 closes, reviewing the
upstream diff and validating the replacement pin before updating installed
copies.

`test-audit` runs automatically when writing or changing tests and when the
requested work assesses test quality, including read-only audits. The fork
excludes test reads used as evidence for research, diagnosis, source review,
packaging, and validation planning. A research assignment does not become a
test audit because its parent workflow will later change tests.

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

## Review updates locally

[Plugin update review](../tools/plugin-update-review/README.md) can prepare local
candidates from configured forks and upstreams. A person reviews the diffs,
starts any tests, and explicitly applies a candidate. The existing remote drift
checks continue to run independently.

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

## Scheduled fork checks

[Upstream fork drift](../.github/workflows/upstream-forks.yml) runs every Monday
at 04:23 UTC and can be started from the Actions tab with `workflow_dispatch`.
It monitors every fork used by this marketplace:

| Fork | Upstream |
| --- | --- |
| `ramtoshiya/mattpocock-skills:main` | `mattpocock/skills:main` |
| `ramtoshiya/claude-codex-settings:main` | `fcakyon/claude-codex-settings:main` |
| `ramtoshiya/ouroboros:main` | `Q00/ouroboros:main` |
| `ramtoshiya/pstack-mode:main` | `backnotprop/pstack:main` |

The Ouroboros fork first runs its own [upstream sync workflow](https://github.com/ramtoshiya/ouroboros/blob/main/.github/workflows/sync-upstream.yml)
every Monday at 04:00 UTC. It rebases the fork's customization commits onto
the latest upstream `main`, runs the standalone interview plugin test, and
pushes with a force-with-lease. A clean rebase therefore finishes without an
alert. A conflict or failed test leaves the fork unchanged, and the drift check
then reports the work that needs manual review. Both workflows also support a
manual run.

The check uses GitHub's compare API with the upstream branch as the base and
the fork branch as the head. Its `behind_by` count includes missing upstream
commits even when the fork has its own commits. When the count is positive,
the built-in `GITHUB_TOKEN` creates or updates one open issue per pair in
`ramtoshiya/skills`, with the count and comparison link. A later successful
check closes that issue when the count reaches zero. API errors fail the run
and leave that pair's issue unchanged. Runs are serialized to avoid duplicate
creation, and existing duplicate bot issues are closed.

To monitor another public fork in the same GitHub fork network, add an object
to [the monitored pairs](../.github/upstream-forks.json) with `fork`, `branch`,
`upstream`, and `upstreamBranch`. Repository values use `owner/repository`.
The deterministic test also requires every `ramtoshiya/*` marketplace source
to have a monitored pair, so a new fork cannot be added without this check.
Each pair has its own issue marker, so changing a pair's branches or removing
it requires closing its old issue manually. Issue matching uses the marker and
the `github-actions[bot]` author, leaving human issues alone.

The drift workflow needs only repository contents read access and issues write
access. It uses no private credentials or local services, and it never changes
fork branches or marketplace pins. The separate sync workflow runs inside the
Ouroboros fork, where its built-in token can update that fork without a shared
credential. Marketplace pins remain review-gated. Follow the pin update steps
below after reviewing a synchronized fork. Deterministic tests run with
`npm test`.

## Update a pin

1. Read the upstream diff for the entry's folder between the pinned commit and
   the new one. Check removed or renamed files, new dependencies, license
   changes, hook behavior, and changes to the skill's instructions.
2. For a fork, merge upstream into the fork first. Git reporting no conflict is
   not enough: an upstream change can still undo the intent of a fork change.
   Each fork commit message should say why the change exists, so a later merge
   can tell a customization from an accident.
3. If the fork's plugin manifests have a `version`, bump it when releasing
   changed plugin contents. Keep the version consistent across the agent
   manifests. Claude Code and Codex label an install with this
   version, not the marketplace's commit SHA.
4. Change `sha` in the entry, and `path` if upstream moved the folder. That
   commit is the release.
5. Push the change to `origin/main`. For managed installations, `main:sync`
   then runs `mise run agents:sync`. Reload or restart each changed host and
   review Codex hook trust. For manual installations,
   reinstall where needed:
   - Claude Code: `claude plugin marketplace update ramtoshiya`, then
     `claude plugin update <entry>@ramtoshiya` and reload or restart.
   - Codex: finish active turns and close sessions using the plugin. For a
     Git-backed marketplace, run `codex plugin marketplace upgrade ramtoshiya`.
     For a local marketplace, update its checkout instead. Then run
     `codex plugin add <entry>@ramtoshiya`. Start a fresh process and review hook
     trust in `/hooks`. [Agent plugins](agent-pack.md) covers the runtime
     lifecycle, including shared-server considerations.
6. Check that the installed manifest version and `hooks/hooks.json` match the
   selected commit. A displayed version alone does not prove that the installed
   files or an active runtime are current. Reusing a manifest version can keep
   changed fork contents from reaching an installed copy.

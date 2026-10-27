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
| `humanize` | `humanize` and its hook | `plugins/humanize` in the fork [ramtoshiya/claude-codex-settings](https://github.com/ramtoshiya/claude-codex-settings) | Apache-2.0 |
| `humanize-korean` | Korean prose diagnosis, editing, and verification | `plugins/humanize-korean` in the fork [ramtoshiya/im-not-ai](https://github.com/ramtoshiya/im-not-ai) | MIT |
| `ouroboros-interview` | `interview`, `unstuck` | `plugins/ouroboros-interview` in the fork [ramtoshiya/ouroboros](https://github.com/ramtoshiya/ouroboros) | MIT |
| `omd-kr-writer` | Korean writing with 12 voice presets | `plugins/omd/skills/omd-kr-writer` in the fork [ramtoshiya/oh-my-design](https://github.com/ramtoshiya/oh-my-design) | MIT |

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

The two `claude-codex-settings` entries have different licenses. The
repository is Apache-2.0, and the `test-audit` folder has its own MIT
`LICENSE`.

`omd-kr-writer` writes or revises Korean text with 12 voice presets and defaults
to `toss-tech-design`. Explicit instructions and project voice override presets.
It uses the caller's output paths and document schema. Other locales remain
caller-owned.

The marketplace source points at the OmD skills directory but exposes only
`omd-kr-writer`. It does not load OmD's design-system workflows, roles,
preference hooks, Pi extension, or native Hermes plugin. Claude Code and Codex
use the marketplace's `skills` selection. Pi should list only the pinned
`plugins/omd/skills/omd-kr-writer` directory. Hermes should register that same
directory through a writing-only adapter. Restart or reload the affected agent
after changing the installation.

The `humanize` skill handles English writing and existing code/configuration
changes. Korean text, including new publication drafts, goes to
`humanize-korean`. Both skills load for bilingual text. Select by source or
output language, not the language of the instructions. Ordinary private chat,
research, explanations, and read-only reviews do not invoke either unless also
writing files, publishing, or explicitly humanizing text.

Its hook checks file writes, commits, pull requests, and Slack or Linear
posts for AI-sounding wording. Findings are advisory warnings and do not block
the call or override normal permissions. The fork runs the hook through
uv-managed Python instead of a bare `python3` and includes a Pi adapter
(`hooks/pi.ts`). These changes are included at the pinned commit.
When the hook itself fails, it lets the call through, as upstream does.
For Codex patches, the hook skips files it cannot read or reconstruct and
checks the remaining files. Codex reports any patch errors.

`humanize-korean` packages a pinned commit from the
[ramtoshiya/im-not-ai fork](https://github.com/ramtoshiya/im-not-ai), not a local
source path. Claude Code, Codex, Pi, and Hermes load the paired skills. The
managed host selection in `setup/agents/hosts.json` enables the Korean companion
where the English skill delegates to it.

For new Korean publication text, including issue replies without an editing
request, the Korean skill reads its rulebook and drafts from the caller's facts.
It does not create an empty editing source or claim source-relative gate results.
Supplied-source editing keeps the upstream Korean rules, light/standard/heavy
routing, diagnosis and finalizer roles, chunk reassembly, and deterministic
verification scripts. The advisory English-wording hook remains separate.

The fork builds a self-contained package with the upstream MIT license.
`scripts/build_hermes_plugin.py --check` checks the packaged copies against
their source files. Run it after merging upstream changes, then exercise the
packaged helpers and a fresh Hermes session before updating the marketplace
pin. A matching rulebook alone does not prove that the workflow still works.

## Measure humanizer routing

Measure source/output-language routing separately from conversation language.
Korean publication and source editing should use `humanize-korean`, English
text should use `humanize`, and bilingual text should use both. A private-chat
control means ordinary Q&A without file writing or a separate publication task,
not a platform privacy or access-control guarantee.

Run the routing evaluator with local `SKILL.md` files from the exact marketplace
pins. It needs Node.js, Claude Code, and a configured model provider:

```sh
node scripts/humanizer-trigger-eval.mjs \
  test/fixtures/humanizer-trigger-cases.json \
  /path/to/english/SKILL.md /path/to/korean/SKILL.md \
  /path/outside/repository/results.json gpt-6.1-sol 3
```

The corpus has paired Korean and English requests, cross-language editing, and
bilingual text. The runner loads both skills' frontmatter together in a temporary
plugin, uses isolated settings, and records actual `Skill` calls in the first
assistant turn. Skill bodies and hooks do not execute. Claude Code's built-in
skills can remain visible and are recorded with each observation. Timeouts,
missing skills, and failed runs are invalid observations, not non-triggers.

To check implicit writing, use
`test/fixtures/humanizer-implicit-thread-cases.json` as the first argument. It
pairs the same user message in a published Multica thread and a private chat,
in Korean and English, without asking for humanization. Publication context is
stated in the prompt, not discovered through a live Multica tool. Both corpora
carry `expected_skills` for the publication-inclusive contract above. Code-only
changes remain with `humanize`. Combine the corpora and freeze those labels
before evaluating either configuration. Compare baseline and candidate against
the same contract rather than scoring each against its own scope.

`test/fixtures/humanizer-publication-holdout-cases.json` adds cross-language
publication and private discussion that mentions posting without requesting it.
Keep this separate from the optimization corpus when reporting results.

Keep experimental source clones at explicit base commits and record each local
candidate commit. Edit the Korean fork's canonical Claude, Codex, and Hermes
skill sources, then rebuild and check its self-contained package with
`scripts/build_hermes_plugin.py`. Evaluate the rebuilt package, not a generated
file edited by hand. A new-writing mode must not invent an empty editing source
or claim source-relative gate results. Smoke-test the full skill body separately
from description-only routing. Local evaluation does not update marketplace
pins, plugin versions, or installed agents.

Report each skill's calls divided by valid runs, grouped by conversation language
and task type. Also report target-text language, both/neither selections, and
invalid runs. For each skill, compute the true-positive rate on cases that
require it and the false-positive rate on cases that exclude it. Report missed
calls separately from wrong-language calls. A skill with no positive cases has
an undefined true-positive rate, not a zero rate. State whether the reference
contract is the current scope or a proposed language-exclusive writing policy.
Keep generated results outside the repository and attach them to
the review. Three repetitions of a small synthetic corpus are a routing check,
not a production usage estimate. This evaluator does not measure later calls,
editing quality, hook warnings, or Codex, Pi, and Hermes behavior. Do not use
Claude Code's `--bare` mode here. It omits automatic skill context even when the
initialization event lists the skills.

## Install

Claude Code and Codex read the marketplace. After adding it as described in
[Agent plugins](agent-pack.md), install each entry by name:

```sh
claude plugin install mattpocock-productivity@ramtoshiya --scope user
codex plugin add mattpocock-productivity@ramtoshiya
```

Codex runs the `humanize` hook only after you trust it in `/hooks`.

Pi does not read the marketplace. Clone each repository at the pinned commit
and list the skill folders in `~/.pi/agent/settings.json`. For example:

```sh
sha=660effa621300eb6c388c7e9347fbf1d4cb3ba4f
dir=~/.pi/agent/skill-sources/ramtoshiya/mattpocock-skills/$sha
git clone https://github.com/ramtoshiya/mattpocock-skills.git "$dir"
git -C "$dir" checkout --detach "$sha"
```

```json
{
  "skills": [
    "skill-sources/ramtoshiya/mattpocock-skills/660effa621300eb6c388c7e9347fbf1d4cb3ba4f/skills/productivity/grilling"
  ]
}
```

Paths in Pi's settings resolve from `~/.pi/agent/`. For `humanize`, also add
`plugins/humanize/hooks/pi.ts` from the fork's checkout to `extensions`.
Changing a pin in the marketplace does not update these checkouts. Clone the
new commit and change the paths.

A loose copy of the same skill makes it load twice, as described in
[Agent plugins](agent-pack.md).

### Hermes

For `humanize-korean`, install the whole package rather than copying its
`SKILL.md`. From this repository, read its marketplace pin and create a detached
checkout under the active Hermes profile:

```sh
home=${HERMES_HOME:-"$HOME/.hermes"}
sha=$(uv run --no-project --managed-python --python '>=3.11' python -c 'import json; from pathlib import Path; entries=json.loads(Path(".claude-plugin/marketplace.json").read_text())["plugins"]; print(next(p["source"]["sha"] for p in entries if p["name"] == "humanize-korean"))')
dir="$home/skill-sources/ramtoshiya/im-not-ai/$sha"
git clone https://github.com/ramtoshiya/im-not-ai.git "$dir"
git -C "$dir" checkout --detach "$sha"
hermes plugins doctor "$dir/plugins/humanize-korean" --ci
mkdir -p "$home/plugins"
ln -s "$dir/plugins/humanize-korean" "$home/plugins/humanize-korean"
hermes plugins enable humanize-korean --no-allow-tool-override
hermes plugins list --plain --no-bundled
```

If that plugin path already exists, inspect it before replacing it. Do not use
`ln -sf` to overwrite another installation. Start a new Hermes conversation to
load `humanize-korean:humanize-korean`. Request Korean editing in natural
language, with `정밀 모드` for the full diagnosis, rewrite, and finalizer route.
Results stay in the working directory's `_workspace/`. On a pin update, verify
the new checkout before changing the link and starting another conversation.

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
  `plugin.json`. This is why the `humanize` entry keeps the upstream name.
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
| `ramtoshiya/im-not-ai:main` | `epoko77-ai/im-not-ai:main` |
| `ramtoshiya/oh-my-design:main` | `kwakseongjae/oh-my-design:main` |

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
   manifests. Claude Code and Codex label the `humanize` install with this
   version, not the marketplace's commit SHA.
4. Change `sha` in the entry, and `path` if upstream moved the folder. That
   commit is the release.
5. Reinstall where needed:
   - Claude Code: `claude plugin marketplace update ramtoshiya`, then
     `claude plugin update <entry>@ramtoshiya` and reload or restart.
   - Codex: finish active turns and close sessions using the plugin. For a
     Git-backed marketplace, run `codex plugin marketplace upgrade ramtoshiya`.
     For a local marketplace, update its checkout instead. Then run
     `codex plugin add <entry>@ramtoshiya`. Start a fresh process and review hook
     trust in `/hooks`. [Agent plugins](agent-pack.md) covers the runtime
     lifecycle, including shared-server considerations.
   - Pi: create new pinned checkouts and change the configured paths, then
     run `/reload`.
6. Check that the installed manifest version and `hooks/hooks.json` match the
   selected commit. A displayed version alone does not prove that the installed
   files or an active runtime are current. Reusing a manifest version can keep
   changed fork contents from reaching an installed copy.

For `humanize`, check a normal shell call and a file write containing a flagged
word in a disposable directory. The shell call should succeed, and the file
write should complete with an advisory warning. Run this check in the fresh
Codex process without links between cached version directories. A direct call
to `humanize.py` does not verify that Codex loaded the updated hook.

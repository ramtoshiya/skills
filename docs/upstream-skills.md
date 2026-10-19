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
| `fcakyon-test-audit` | `test-audit` | `plugins/test-audit/skills` in [fcakyon/claude-codex-settings](https://github.com/fcakyon/claude-codex-settings) | MIT |
| `humanize` | `humanize` and its hook | `plugins/humanize` in the fork [ramtoshiya/claude-codex-settings](https://github.com/ramtoshiya/claude-codex-settings) | Apache-2.0 |
| `ouroboros-interview` | `interview` | `plugins/ouroboros-interview` in the fork [ramtoshiya/ouroboros](https://github.com/ramtoshiya/ouroboros) | MIT |

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

`ouroboros-interview` packages only the interview skill and its bundled
questioning and closure-review prompts. It uses the host's native tools, needs
no additional runtime or server, and ends with an agreed requirements summary.
It does not load the fork's root plugin, start implementation, change agent
configuration, or check for updates. Results stay in the conversation unless
you request a summary file. Invoke `/ouroboros-interview:interview` in Claude
Code after installing the entry.

The two `fcakyon/claude-codex-settings` entries have different licenses. The
repository is Apache-2.0, and the `test-audit` folder has its own MIT
`LICENSE`.

The `humanize` skill applies before creating or modifying any file, including
code and configuration, and when preparing or publishing content such as
commits and pull requests. Ordinary chat, research, explanations, and read-only
reviews do not invoke it unless you explicitly request the skill.

Its hook checks file writes, commits, pull requests, and Slack or Linear
posts for AI-sounding wording. Findings are advisory warnings and do not block
the call or override normal permissions. The fork runs the hook through
uv-managed Python instead of a bare `python3` and includes a Pi adapter
(`hooks/pi.ts`). These changes are included at the pinned commit.
When the hook itself fails, it lets the call through, as upstream does.

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

# Working in this repository

Rules for agents and people who change this repository. `README.md` describes
what the repository contains.

## Public repository {:#public-boundary}

This repository is meant to be public.

- Never commit credentials, tokens, authentication state (`auth.json`,
  `.credentials.json`, `.env`), private SSH or GPG keys, passphrases, session
  transcripts, or other runtime data. `.gitignore` is a safety net, not a
  review.
- Read imported configuration line by line before tracking it. Shared settings
  exclude identity, signing keys, credential helpers, and machine-specific
  trust entries.
- Keep personal machine context out of tracked files: other machines, accounts,
  private repositories, and colleagues. Private notes live outside the
  repository.

## Documentation {:#documentation}

Human-facing docs are `README.md`, `docs/*.md`, and the READMEs under `tools/`
and `bb-plugins/`.
Agent-facing docs are this file and the `SKILL.md` files.

- Write human-facing docs for a stranger on a Mac who has no context.
- Describe the current state only. Leave out history, migration notes, and
  dated decisions, which Git keeps. One "Tested with" line per doc is enough.
- Link to a third-party tool's own install page instead of copying its install
  commands or pinning its version.
- Human-facing docs use no `{:#id}` heading anchors, because GitHub prints them
  as text. Link to files, not sections.
- Agent-facing docs give a `{:#id}` anchor to any heading that another document
  or a later message may cite. Name the id after the topic, and never reuse or
  renumber one.
- Update the doc that owns a behavior in the same commit that changes it:

| Topic | Owner |
| --- | --- |
| Plugin contents, host support, install, update, checks | `docs/agent-pack.md` |
| Hook rules and limits | `docs/hooks.md` |
| Marketplace entries for third-party skills, forks, pin updates | `docs/upstream-skills.md` |
| `mise.toml` and `setup/` | `docs/setup.md` |
| Each standalone CLI under `tools/` | `tools/<tool>/README.md` |
| Each bb plugin under `bb-plugins/` | `bb-plugins/<plugin>/README.md` |

## Layout and boundaries {:#layout}

- `plugins/ramtoshiya/` is shared across supported hosts, documented in
  `docs/agent-pack.md`. Hook rules live only in the shared hook program and
  scripts. Host adapters, such as `hooks/hooks.json`, only translate events
  and guard responses and must not add or change rules.
- The package guard and the commit attribution guard are one Go program in
  `plugins/ramtoshiya/hooks`, built into a binary that Git ignores. It takes
  exactly two modules, `mvdan.cc/sh/v3` and `github.com/BurntSushi/toml`, at
  exact versions. A new module or version follows the exact-pin and three-day
  release-age rules in Standalone CLIs.
- The other hook scripts use only the Python standard library and run through
  the uv command shown in `docs/hooks.md`. The plugins take no other
  third-party dependencies and have no `version` field.
- `plugins/ramtoshiya-cc/` is for Claude Code only.
- Third-party skills are never copied into this repository. Add a marketplace
  entry pinned by commit, as `docs/upstream-skills.md` describes.
- `mise.toml` and `setup/` are the machine setup. Files in `setup/` are copied
  or merged into place by mise. Identity, signing, and credentials stay out.
- `bb-plugins/` contains plugins for the bb app, each installed separately
  with `bb plugin install`. They are not agent-pack plugins and follow the
  same exact-pin and release-age rules as `tools/`.
- `tools/` contains independently installed commands and their tests. `dev/`
  contains repository tests, automation, evals, desktop verification scripts, and disabled skills. `docs/`
  contains human-facing repository documentation.

## Standalone CLIs {:#cli-tools}

A CLI under `tools/` is an independently installed program a person runs from a shell.

- It has its own source, dependencies, and install step, and no plugin
  manifest, skill, or hook inside its folder.
- It may operate on agent or plugin environments. Its output and docs serve a
  person at a terminal.
- It follows the same supply-chain rules: exact version pins, a three-day
  minimum release age, and no global package installs.
- A skill that needs a CLI looks it up on `PATH` when it runs. If the command
  is missing, the skill names it and the install step, and stops. A skill never
  installs, updates, or builds a CLI.

## Checks {:#checks}

Run before committing:

```sh
npm test
claude plugin validate ./plugins/ramtoshiya
claude plugin validate ./.claude-plugin/marketplace.json
```

After changing a registered command hook, check an allowed command and a denied
command in each agent that loads it. Take those commands from real transcripts
where you can. After changing the opt-in Git hygiene check, also verify a blocked
first stop in a dirty repository in each agent where it is enabled.
Hooks catch ordinary mistakes by users and agents. Deliberate bypass is out of
scope, so do not add rules for it. The [package and Python
guard](docs/hooks.md) applies to your own shell commands here as well. Run this
repository's Python with `uv run python`, as `npm test` does, because the hooks
need Python 3.11 or newer and the system `python3` can be older.

## Publishing {:#publishing}

Push finished work that passes the checks above to `origin/main` of this
repository without asking first. That push is the standing workflow, and the
hook in `setup/git-hooks` then brings the shared checkout and the local
installs level with it.

## Claims and checks {:#claims}

Hand back work in this repository with the claim checklist that
[`setup/agents/preferences.md`](setup/agents/preferences.md) describes. Read
its claims section if your session did not load those preferences. Cite each
check above that you ran, with its result. Mark each agent, hook path, or host
you did not exercise as unchecked. When a reviewer challenges a change, rerun
the checks the challenge touches before you edit anything.

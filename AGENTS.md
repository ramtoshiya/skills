# Working in this repository

Rules for agents and people who change this repository. `README.md` describes
what the repository contains.

## Intent {:#intent}

Understand the intent behind the user's words, and speak with intent of your
own.

For every user message, however brief or simple, reason about its intent in the
context of the conversation: why the user is saying this now and what they are
trying to accomplish by saying it. Briefly state your interpretation of that
intent and its contextual basis so the user can identify and correct a
misunderstanding. Do not substitute paraphrasing the words for understanding
their intent. Distinguish what the user explicitly stated from what you infer.
Do not invent hidden motives or turn every utterance into a new task.

Let that understanding guide your response and any actions, while preserving
the user's constraints. If intent remains uncertain and action is appropriate,
proceed with useful, easily reversible steps within existing authorization,
then report the interpretation you acted on and what you actually did. Seek
clarification before committing to an interpretation that would be costly to
undo or requires additional authorization.

Compose every sentence with a deliberate intent that serves the user in the
current conversation. Know why you are saying it and what you intend it to
contribute. Do not retain a sentence merely because you can invent a purpose
for it after the fact. Explain, ask, report, or acknowledge something because
the user needs it, not as a conversational ritual. Do not apologize solely to
repair rapport. Give progress updates when the user needs situational
awareness. You need not label each sentence's intent, but it must shape what
you choose to say.

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

Human-facing docs are `README.md`, `docs/*.md`, and the READMEs under `pi/` and
`cli/`. Agent-facing docs are this file and the `SKILL.md` files.

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
- Doc text uses no em dashes or semicolons.
- Update the doc that owns a behavior in the same commit that changes it:

| Topic | Owner |
| --- | --- |
| Plugin contents, host support, install, update, checks | `docs/agent-pack.md` |
| Hook rules and limits | `docs/hooks.md` |
| Marketplace entries for third-party skills, forks, pin updates | `docs/upstream-skills.md` |
| `mise.toml` and `setup/` | `docs/setup.md` |
| Each package under `pi/` | `pi/<package>/README.md` |
| Each standalone CLI under `cli/` | `cli/<tool>/README.md` |

## Layout and boundaries {:#layout}

- `plugins/ramtoshiya/` is shared across supported hosts, documented in
  `docs/agent-pack.md`. Hook rules live only in the shared guard scripts.
  Host adapters only translate events and guard responses and must not add or
  change rules.
- Hook scripts use only the Python standard library and run through the uv
  command shown in `docs/hooks.md`. The plugins take no third-party runtime
  dependencies and have no `version` field.
- `package.json` `files` limits what the Pi package ships, and
  `test/pack.test.mjs` checks it. Change both together.
- `plugins/ramtoshiya-cc/` is for Claude Code only.
- Third-party skills are never copied into this repository. Add a marketplace
  entry pinned by commit, as `docs/upstream-skills.md` describes.
- `mise.toml` and `setup/` are the machine setup. Files in `setup/` are copied
  or merged into place by mise. Identity, signing, and credentials stay out.
- `pi/cliproxy-provider/` is a separate Pi package with its own tests.

## Standalone CLIs {:#cli-tools}

A CLI under `cli/` is a program a person runs from a shell.

- It has its own source, dependencies, and install step, and no plugin
  manifest, skill, or hook inside its folder.
- It knows nothing about agents. Its output and docs serve a person at a
  terminal.
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

After changing a hook, also check it in each agent that loads it: an allowed
command, a denied command, and, for the Git hygiene check, a blocked first stop
in a dirty repository. The [package and Python guard](docs/hooks.md) applies to
your own shell commands here as well: use `uv run python`, not `python`.

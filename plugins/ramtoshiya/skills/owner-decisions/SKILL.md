---
name: owner-decisions
description: >-
  Record the user's decisions for a repository and keep the rules that follow from them current. Use when the user makes, changes, or confirms a decision or a preference that should govern later work in a repository, when you set up a new or empty repository, when a repository has no docs/decisions/ yet, when you cite one of the user's decisions in a plan, brief, or reply, or when you doubt that an old decision still fits.
metadata:
  short-description: Date-named decision records with linked current-rule pages
---

# Owner decisions

A repository keeps two layers. Decision records quote what the owner said, when, and in what situation. They are the source. Topic rule pages state the rules as they apply now, and each rule links to the records it comes from. They are a derived view that agents read while they work. The owner reads and writes neither layer. The owner corrects agents only in the conversation, when something surfaces there.

## Set up a repository {:#set-up}

Run `python3 <skill-dir>/scripts/decisions.py init` from the repository root, including in an empty folder after `git init`. It adds what is missing and leaves existing files alone:

- `tools/decisions/decisions.py`, a copy of this script, so the repository's own check can call it at a fixed path
- `docs/decisions/README.md`, the record format
- `.claude/rules/process.md`, the page for rules that apply to all work
- an "Owner decisions" section in `AGENTS.md`, and a `CLAUDE.md` that imports `AGENTS.md` when there is none

Then add `python3 tools/decisions/decisions.py check` to the repository's check, such as its test command, CI, or pre-commit hook. When the repository has no check yet, run the command yourself before each commit that touches records or rule pages, and add it to the first check the repository gets. When a repository already has a decision log in another format, such as numbered files or an index in `AGENTS.md`, migrate it with a script: rename each record to its date and slug, rewrite every reference to a link with the record's title, and move the index into topic pages.

## Record a decision {:#record}

When the owner makes, changes, or confirms a decision in conversation, record it before you brief work on it, as `docs/decisions/README.md` describes. Name the file after the date of the owner's first quoted words and the decision's content, never a sequential number. Quote the owner verbatim with the source and time, describe the situation, and state the scope. Then write the current rule into the topic page in the same commit, and rewrite an older rule it changes instead of adding a second one.

A topic page other than `process.md` starts with Claude Code `paths:` frontmatter, a YAML list of quoted globs for the files whose work its rules govern. Check each glob against `git ls-files`. List each page in the `AGENTS.md` section with one line. Prefer a type, test or check over a rule on a page when one can hold the rule, and keep the page for what code cannot express.

## Cite a decision {:#cite}

To the owner, name a decision by its content in words, with its date and a link, never by a file name, id or number. In repository text, link to the record with its title as the link text.

## When an old decision may no longer fit {:#recheck}

A decision stays in force until the owner changes it, its own `Until:` deadline passes, or a later record supersedes it. When you doubt that one still fits, judge for yourself whether to follow it, hold the work, or ask the owner. Weigh the work's urgency and importance, and compare the situation the record describes with the situation now. Report the judgment and its grounds in the conversation. No fixed age or schedule decides it. Treat a UI or UX instruction as a prediction that use can overturn.

When work the owner will notice rests on a rule that agents inferred and the owner never confirmed, say so in plain words in the conversation, so the owner can correct it in passing. Never ask the owner to read or review a repository file or a list of rules.

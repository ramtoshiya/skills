# Owner decisions

Each file in this folder records one decision that the owner made. Agents' own rulings and thresholds do not go here. The current rules that follow from these records are in the topic pages under `.claude/rules/`. `python3 tools/decisions/decisions.py list` lists the active records.

## Name

Name a new file `YYYY-MM-DD-short-slug.md`, with the date of the owner's first quoted words and a slug of the decision's content. Do not number decisions. If another branch took the same name, Git reports the clash when the branches meet, and the later one picks another slug.

## Content

A record starts with `# Title`, a sentence that states the decision. Then, each only when it applies:

- `Supersedes:` and a Markdown link, for each earlier record that this one replaces in full. The earlier record stops being active. Do not edit the earlier record.
- `Until: YYYY-MM-DD HH:MM +09:00`, with the owner's UTC offset, only when the owner gave the decision a deadline. The record stops being active then.
- `Relations:`, prose with links for a decision that narrows, extends, or partly replaces another one.

The sections:

- "Owner's words": the owner's words, verbatim, with the date, time and UTC offset, and the source, such as a thread and message number or the owner's commit. Quote only words the owner wrote. When they cannot be found, say so and cite where the decision was recorded.
- "Situation": what the owner was looking at and what had happened, so a later agent can compare it with the situation now.
- "Scope": what the decision covers.
- "Rules out": the methods it rules out, if any.

## After recording

Write the decision's current rule into the `.claude/rules/` page of its topic, with a link to the record, in the same commit. When it replaces or narrows an earlier rule, rewrite that rule on the page instead of adding a second one. `python3 tools/decisions/decisions.py check` fails when an active record has no page that cites it, when a page cites a fully superseded record, when any Markdown link points at a record that does not exist, and when a record is not named by date and slug.

---
name: stable-refs
description: >-
  Use when authoring, restructuring, or reviewing ANY document — internal spec, README, ADR, meeting notes, requirements ledger, client deliverable, in any language — that defines sections, decisions, or items other documents (or later edits) might need to point at. Also applies to ids outside files: a task list or work plan you number in chat replies (T-12, A3, H9) is a reference system the moment anyone can repeat an id back. Trigger this even if the user never says the words "anchor" or "cross-reference" — watch for numbered/lettered schemes (3.1.2, S8-1, D6, §4-1), a doc or a later message that cites an earlier item, or a growing decision/proposal/work-plan log. Prevents reference-chain hell (opaque coordinates nobody can decode without a lookup), renumbering cascades (insert or delete one item, every later coordinate silently drifts or dangles), and dead ids that quietly come back to life. Structural reference stability, not prose style — orthogonal to any audience- or language-specific writing skill.
metadata:
  short-description: Keep identifiers and references stable through change
---

# Stable references

## Why this matters

A coordinate like `3.1.2`, `S8-1`, `§9` is a value computed from where something currently sits — the 9th heading, the 1st sub-item under the 8th screen. Change the document's shape (delete a section, insert an item, split or rename a doc) and every coordinate after the change point points at the wrong thing or at nothing — silently, with nothing to flag it.

This isn't hypothetical: a real project's "living contract" was cited elsewhere as "§9" by three separate files. By the time anyone checked, the contract had been edited down to six sections — §9 didn't exist. The doc's own edit history admits it mid-change: "delete a section, every later number shifts down by one." One anchor ended up literally named `s65`, because the id slug format couldn't hold a decimal point for what should have been "§6.5" — assigned by position instead of by what the section was about. The mechanism for a stable anchor was already available; the anchor was just named after its address instead of its content.

The fix isn't "don't number things" — numbered decision ids and requirement codes can be perfectly stable. The real test is the **assignment policy**, not the label's shape: an identifier is positional if it gets recomputed, renumbered, or reused when neighboring content changes (`§9`, `s65`, "the 3rd bullet"). An identifier assigned once and retired rather than reused — `D6`, `IDR-042`, a changelog entry's permanent id — is durable regardless of whether it looks numeric or coded. Don't reject a coded identifier on sight; check how it's assigned.

Position is not the only fact that can change silently under a label — apply the same test to everything the id encodes. A plan whose ids carry who will do the work (`A5` agent-assigned, `H9` human-assigned) bakes a revisable classification into each item's identity, so the first re-plan forces a rename — "B1 supersedes H9" — and every rename leaves a forwarding hop for readers to chase. Owner, status and priority belong in the item's fields, where they can change without touching its name. A namespace fixed at creation (the `IDR-` in `IDR-042`) is fine; a classification a re-plan can flip is not.

## The rule

Anything another document, a later message, or a future edit might need to point at gets a permanent identifier now — not "we'll fix the reference style later." For a prose anchor, name it by *what it is*, not *where it is*: `calendar-fence-payload`, not `s6` or `§6.5`. When citing another document's location, cite through a real, working link+anchor, or restate the concept in prose ("the calendar fence payload") — never a bare coordinate with nothing backing it. A citation with nothing on the other end is exactly what let the `§9` example above go stale invisibly.

## Give ongoing plans a canonical home

A scheme minted in conversation is still a scheme: "ephemeral" is decided by whether anyone might point at an id again, not by where the id first appeared. Before minting ids for a plan, give it one canonical home — a maintained file, or the project's existing task tracker. If the plan is too small to deserve that home, it is too small to deserve ids; refer to its items by name in prose.

A sequence of independently restated messages is not a canonical home: each retelling is retyped from memory, a fresh fork of the record, and forks eventually disagree about which ids are even alive. Make every change an edit to the home and re-present from it instead of retyping — no redrawn presentation repairs a forked record. When work is merged, cancelled, or replaced, keep its id and record the relation (`T-05 absorbed into T-03`, `T-09 superseded by T-13`) rather than deleting, renumbering, or reusing it: a removed entry is how a dead id silently returns as a live one.

## Mechanism, by what the document already uses

Don't introduce a new toolchain just for this — use whatever the target already supports; only adopt something heavier when the project already has a real docs-as-code pipeline. Pick by the renderer people actually read the document in, not by the one that produced it. The renderer behavior below was last confirmed on 2026-09-18.

| Existing format or toolchain | Use |
| --- | --- |
| Plain Markdown — editor preview, note app, README | Put the id in the heading: `## Coding style {:#coding-style}`, then link to `#coding-style`. Plain Markdown has no id feature, so this is a convention rather than a rendered anchor: a reader that doesn't know it (github.com is one) prints `{:#coding-style}` as text and the link won't jump. Take that trade — the id is visible, greppable, and untouched by a heading rename, where an auto-slug silently breaks every inbound link the moment the text changes. Don't reach for an HTML anchor tag instead; readers that strip or escape HTML print the tag itself. |
| kramdown/Jekyll, Python-Markdown/MkDocs (`attr_list`) | The same `{:#calendar-fence-payload}` form, natively supported — the id is independent of the heading text from then on. |
| Pandoc, Docusaurus MDX | Same idea, no colon: `## Heading {#calendar-fence-payload}`. |
| Raw HTML | You already have `id="..."` available — the usual gap isn't a missing feature, it's a positional name (`s1`, `s65`) chosen out of habit. Name it for the topic instead. |
| reStructuredText/Sphinx, AsciiDoc | Detach the label from the heading entirely — a label can live anywhere (`.. _calendar-fence-payload:` / `[[calendar-fence-payload]]`), referenced independently of nearby text. On an existing Sphinx pipeline, this is the only mechanism here that actively *catches* decay: a broken or duplicate label fails the build instead of rotting silently. |

## Address append-only records by file

When what's being added is a growing, append-only sequence — decisions, changelog entries, proposals — address by *file* instead of by section, the way architecture decision records (ADRs) do: one immutable file per item, filename is the permanent id, never renumbered. Supersede with a new file linking back to the old one; don't reuse or renumber the old identifier. This sidesteps the renumbering cascade entirely, because inserting a new unit never touches an existing one's identity. Apply the same discipline to any addressable unit that doesn't belong to a heading — a label can live wherever the format permits.

## Reconcile after structural edits

Before moving, inserting, deleting, or renaming addressable content, find inbound references across the document set, including identifiers participants already use in conversation. After the edit: verify each target still exists and is unique, each link resolves in the rendered format, and no surrounding document still claims a now-stale section as the source of truth. Run the repository's existing documentation build or link check when one's available — don't invent a heavyweight pipeline for a short-lived or one-off document.

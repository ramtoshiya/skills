---
name: claude-design-direct
description: >-
  Use when reading, editing, verifying or previewing a claude.ai/design project through the
  DesignSync tool — pulling a .dc.html artboard, changing it, pushing it back, rendering it
  locally, or adding a control to the Tweaks panel. Trigger on a claude.ai/design URL or project
  id, on "design project", "design system project", "Tweaks panel", "data-props" or a ".dc.html"
  file; whenever /design status, /design import or /design export refuses with "do it at
  claude.ai/design, not here"; and whenever a .dc.html opened locally shows literal {{ }} bindings
  or every conditional branch at once, or a claudeusercontent.com preview URL will not load.
  Covers the DesignSync path only, not the /design slash commands and not local component-library
  uploads.
---

# Editing a claude.ai/design project from the terminal

## This is a workaround

Anthropic documents none of this. Every fact below came from observed behaviour in a live session
and from reading Claude Design's minified bundle, so any of it can change without notice.

- If an official skill, plugin or documented API exists by the time you read this, prefer it.
- When what you observe contradicts this file, the observation wins. Then fix this file.

Last confirmed against a live Claude Design session on 2026-09-17. When you confirm or correct a
fact here, update this date.

Every step you run is headless — `DesignSync`, plus a local static server when a preview is
needed. You stage a preview; you do not open one. One procedure breaks that rule, and it is
flagged where it appears: "Recovering this vocabulary after a rejection" in [`references/tweaks.md`](references/tweaks.md).

## Load the tool first

`DesignSync` is a deferred tool, so a fresh session has not loaded it.

```
ToolSearch("select:DesignSync")
```

Until you do, `/design status`, `/design import` and `/design export` take a fallback branch and
refuse with "…do it at claude.ai/design, not here". **That refusal is a fact about the session, not
about the account or the project** — do not report it as an access problem.

`/design-sync` is declared `disableModelInvocation: true`: only a human can run it, and its argument
is a project-name hint, not a path. Do not plan a model step around it.

Finish the job in the session that loaded the tool. Handing it to a fresh Claude Code session does
not help: that session hits the same fallback refusal, and one that did load `DesignSync` on
request then declined a bulk download, because the tool's own description frames reads as
single-file checks.

## Find the project

1. **Take the `projectId` from the URL**, `claude.ai/design/p/<projectId>`. `list_projects` returns
   only design-system projects; a regular project never appears there, and its absence is not
   evidence that it is unreachable. Passed directly, `get_project`, `list_files`, `get_file`,
   `finalize_plan` and `write_files` all work on a regular project.
2. **Check `canEdit` before planning any write.** `get_project` returns
   `{name, type, ownerDisplayName, canEdit}`. If `canEdit` is false, stop and say so rather than
   building a plan `write_files` will reject.
3. **Read `type`.** `PROJECT_TYPE_PROJECT` is a regular design or mockup project.
   `PROJECT_TYPE_DESIGN_SYSTEM` is the one shared, organisation-wide design system: writing there
   changes what every project in the org inherits, so get the owner's agreement first. Type is fixed
   at creation, so never offer converting one into the other.

Uploading a local component library as that design system is a different job with an existing skill:
github.com/Chachamaru127/claude-design-sync-skill. Point at it rather than improvising the flow.

## The edit loop

```
list_files     → find the .dc.html
get_file       → content inline, or persisted to a local file
(edit locally)
finalize_plan  → writes: [path], deletes: [], localDir: <dir>
write_files    → planId + files: [{path, localPath}]
get_file       → read back and verify (see below)
```

- `finalize_plan` requires `deletes` even when empty. Omitting it errors with
  `finalize_plan requires: deletes`.
- `finalize_plan` accepts a path that does not exist yet, nested ones included
  (`frames/PipelineList.dc.html`). The new directories then appear in `list_files` as bare entries
  beside the files, so a new subtree needs no separate step.
- `localPath` in `write_files` resolves relative to the plan's `localDir`, which defaults to cwd.
- `get_file` is capped at 256 KiB. An artboard past that cannot be read through this route at
  all — a hard ceiling, and not the reason a read comes back inline.
- When `get_file` persists the content to a local file, work on that file with a script. Re-emitting
  a whole artboard through your context to change one attribute wastes it and invites typos.
- When `get_file` returns the content inline, write it to disk unedited before you change anything.
  `write_files` takes a `localPath`, not a string, so the edit has to land in a file either way.
- Keep every version you pull. There is no undo — your local copies are it.

## Leave the canvas in sync

The canvas is what the user reviews. A local edit you never wrote back does not exist for them, and
a commit in your repo is invisible there. Observed failure: two rounds of edits stayed local, the
user reviewed the stale canvas, and their next round of feedback named a control that had already
been removed.

- **Write back before you report the task done.** "Committed locally, not pushed" is an unfinished
  job, not a safe default. Editing and syncing are one unit of work; a separate instruction to push
  is not required, and waiting for one is how the canvas falls behind. If something genuinely blocks
  the write, say the canvas is stale and name which version it still shows.
- **Diff before you overwrite.** `write_files` replaces the whole file and there is no undo. Pull the
  remote copy and compare it against the version you last pushed. Identical means the canvas is only
  behind you — overwrite. Different means someone edited in the browser: stop and show that diff
  rather than discarding their work. Keep a dated copy of whatever you pulled either way.
- A generated artboard syncs from its generator's output, never by hand-editing the pushed file.
  Regenerate, then write back, so the canvas and the generator cannot disagree.

## Verifying a write

Read the file back with `get_file`. What you can check depends on how the content came back, and
the two cases support different claims:

- **Persisted to a local file.** You have bytes on disk. Diff them against the bytes you sent, and
  report byte-identical or not.
- **Returned inline.** The content reached your context but never the filesystem, so there is
  nothing on disk to diff. Do not re-emit the artboard through your context to manufacture one
  just to reach the stronger wording. Check distinguishing content instead: the values you set,
  **and** a marker the edit should have removed. The absent marker is the stronger half — a write
  that silently did not land still carries it.

You do not choose the mode and cannot reliably predict it. In one session a 43 KB read came back
inline and a 55 KB read persisted. Branch on what you actually received, not on the file size.

Then say which check you ran. "Byte-identical to what I sent" and "contains the values I set" are
different claims, and someone will lean on the difference later. Reporting a byte match after an
inline read is the failure this section exists to prevent.

A design agent's summary of its own work is not evidence either. One reported changes it had not
made, and asserted data the source system cannot supply. Only what you read back counts.

## An artboard is a prototype

Do not carry production concerns into one. Semantic `<table>` markup or ARIA moves the artboard's
content out of the template and into the script block, where it is neither readable as a
specification nor click-to-edit in the canvas — and canvas editing is usually why the user is in
Claude Design at all. Accessibility belongs in the real application.

## Tweaks

The Tweaks panel is the canvas's control strip. It renders one editor per prop the artboard
declares, so a reviewer can explore alternatives — another sort order, another accent colour —
without editing code.

Its schema lives in the `data-props` attribute on the `<script data-dc-script>` tag — **never** on
`<x-dc>`. No separate file and no hidden state, so editing that attribute from outside the browser
produces a working control.

Declare or change a prop only when the task asks for one. Knobs added during an unrelated edit hand
the reviewer controls nobody asked for. When the task does ask, read [`references/tweaks.md`](references/tweaks.md) for the
editor vocabulary, the runtime traps, and how to refresh both from the bundle.

## Previewing an artboard outside the canvas

Opened straight from disk, a `.dc.html` shows literal `{{ }}` bindings, every `sc-if` branch at
once, and the page repeated. **That is a missing runtime file, not a broken artboard.** `support.js`
owns `hideRawTemplate()`, and a browser treats unknown `sc-for` / `sc-if` elements as ordinary
inline wrappers whose children always render. Diagnose the absence before doubting the artboard, or
you will "fix" a file that was already correct.

`support.js` is that runtime. It is in no repo — pull it with `get_file` from the project that
owns the artboard. That read follows the same two modes as any other, so if it comes back inline,
write it to disk before you copy it anywhere. Then put both files in one directory and serve that
directory over HTTP:

```sh
D=$(mktemp -d)
cp path/to/Artboard.dc.html path/to/support.js "$D/"
uv run python -m http.server 8899 --directory "$D" &   # background it; it never returns
preview_pid=$!
# now at http://localhost:8899/Artboard.dc.html — stop it with: kill "$preview_pid"
```

That is the whole harness. Any static server does; `uv run python` is here because the user's
global Python guard hook refuses a bare `python3`.

Do not supply React: `support.js` loads its own, and its loader returns early if `window.React`
and `window.ReactDOM` are already set, so a React you inject renders the page under your version
while it still looks correct.

Do not try to open the canvas's own preview URL. `<projectId>.claudeusercontent.com/_bootstrap` is
an auth handshake, not a page: it waits for a `postMessage` from claude.ai, sets
`__Host-omelette-preview` with `Partitioned`, then redirects to the real file. Every other path 404s
until that cookie exists, and `Partitioned` keys the cookie to claude.ai as the top-level site, so
holding a token would not help.

When the artboard has to be looked at, hand over the local render rather than the canvas. It is a
normal top-level page, so devtools, `getComputedStyle` and element pickers all reach it, and none
of those cross into the canvas iframe. Serving it is your job; opening it is not.

## Why the whole file is your only lever

The bundle names the design agent's own editing tools — `dc_write`, `dc_html_str_replace`,
`dc_js_str_replace`, `dc_set_props`. You cannot call them. That agent streams targeted edits into a
live preview; `write_files` replaces a file entirely. Plan every change as a whole-file rewrite, and
verify it as one.

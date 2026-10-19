---
name: mermaid-check
description: >-
  Run the real Mermaid parser over every Mermaid diagram before delivering it, instead of trusting a
  read-through. Use whenever you write or edit Mermaid anywhere: a `.mmd` file, a ```mermaid fenced block
  in a `.md` / README / docs page, or a diagram drafted in chat that will land in a file — even when the
  user only asked for "a diagram" and never mentioned validation. Also use when a user reports a Mermaid
  diagram that will not render, or when you are about to say a diagram "looks right". Covers `.mmd` files,
  whole Markdown documents with several blocks, and stdin; prints the parse error without the stack trace.
metadata:
  short-description: Validate Mermaid syntax with the real parser before delivering
---

# Mermaid check

Confirmed with `@mermaid-js/mermaid-cli@12.0.0` (npm 11.19.0) on 2026-10-15. When bumping the pin, update the
script, the version named in step 5, and this line together, and re-run a passing and a failing diagram.

An agent reading its own Mermaid sees what it meant, not what the parser will read, and a diagram that
"looks fine" then renders as a red error box. The parser's verdict is the only one that counts, in both
directions: don't ship what it rejects, and don't "fix" what it accepts.

## Procedure

1. Finish the diagram in its real location: the `.mmd` file, or the ```mermaid block inside the Markdown
   file.
2. Run the bundled checker on that file. `<skill-dir>` is the directory holding this `SKILL.md`:

   ```sh
   sh <skill-dir>/scripts/mermaid-check.sh path/to/diagram.mmd          # one diagram
   sh <skill-dir>/scripts/mermaid-check.sh docs/architecture.md         # every mermaid block in the file
   printf '%s\n' "$diagram" | sh <skill-dir>/scripts/mermaid-check.sh - # diagram drafted in chat
   ```

   A `.md` / `.markdown` / `.mdx` path is checked block by block (```mermaid, ~~~mermaid, :::mermaid
   fences); any other path is one diagram. Render output goes to a temp dir that is removed afterwards, so
   nothing appears next to the source.
3. Read the exit code. `0` with an `ok:` line: every diagram parsed. `1`: at least one failed and its parse
   error is printed. `2`: usage error, or a Markdown file with no mermaid block (check the fence spelling).
4. On failure, fix the diagram at its source and re-run until exit `0`. A failing Markdown block is labelled
   `file:LINE`, the file line of the block's first diagram line. Locate the fault by the printed snippet and
   `^` caret. Mermaid's own `line N` is where the parser stopped: the real line for a bad token, but a line
   past the end for an unfinished construct such as an edge with no target, because the parser reads to the
   end of input before it can tell.
5. Say in the delivery that the diagram parsed (`mmdc 12.0.0`), so the reader knows it was validated,
   not eyeballed.

## Notes

- **Command shape.** The script runs `npx --min-release-age=3 @mermaid-js/mermaid-cli@12.0.0 <mmdc args>`.
  Use it directly only when the script is unavailable, keeping the flag *before* the package name: after
  it, `npx` forwards the flag to `mmdc`, which exits 1 with `unknown option`. `-i -` reads stdin;
  `-o - -e svg` writes to stdout and needs the explicit format. Exit `0` = parsed, `1` = parse error.
  Bare `npx @mermaid-js/mermaid-cli` and `npx -p ... mmdc` are denied by the package guard hook, which requires an exact version for one-shot packages.
- **Why block by block.** `mmdc -i doc.md -o out.md` renders every block in one browser launch but stops
  at the first block that fails and does not say which one; it also extracts only ``` and ::: fences, so a
  ~~~mermaid block would pass unchecked. The script runs that fast pass first when the file has no ~~~
  fence; when the pass fails, or the file has one, it checks each extracted block alone, so every broken
  block is reported with its file line.
- **Cost and first run.** Each `mmdc` call launches headless Chromium, about 6 s once cached: one call for a
  clean Markdown file, one per block when something fails or a ~~~ fence is used. The very first call on a
  machine downloads Chromium and can take more than two minutes, longer than a typical tool-call timeout. If
  the check dies with neither a parse error nor an `ok:` line, re-run with a longer timeout rather than
  concluding the diagram is broken.
- **Looks wrong, is valid.** A flowchart edge label continued on the next line (`A -- oops` then
  `B --> C`) is a multi-line label; `B-->` at line end followed by `C-->D` is the chain `B --> C --> D`.
  Syntax is all the parser judges; layout and whether the diagram matches the surrounding text are still
  yours to check.

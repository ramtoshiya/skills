---
name: figma-rest
description: Use when reading anything out of a Figma design file — design tokens, colors, type/spacing scales, node structure, or rendered node images — and when a Figma MCP tool returns a rate-limit or "nothing selected" error. Prefer the REST API over the Figma MCP server, which is capped per seat.
---

# Reading Figma via the REST API

Default to the REST API for reading Figma files. Reach for the MCP server only for what REST cannot do.

Token setup and `GET /v1/me` confirmed on 2026-10-15. Seat limits, endpoint coverage, and the traps below were last reviewed on 2026-08-28; recheck Figma's documentation when one of them disagrees with what you see.

## Why REST first

The Figma **MCP** server is rate-limited by *seat type*, not by plan tier:

| Seat | Limit |
|---|---|
| View, Collab | **6 tool calls per month** (every plan tier) |
| Dev, Full | 200/day (Pro, Org) · 600/day (Enterprise) |

Six calls per month is enough to look around once and then be locked out for weeks — and the cap is silent until hit. The REST API has a far larger budget and covers nearly all reading.

`whoami`, `generate_figma_design`, and `add_code_connect_map` are exempt from MCP rate limits. Run `whoami` to check seat and plan for free; do this before assuming MCP is available.

Two MCP behaviors worth knowing, because they waste calls:
- `get_variable_defs` reads the **live desktop selection**. Passing a `nodeId` does not substitute for the user having selected something in the Figma app.
- A rate-limit error is indistinguishable from a real failure unless read carefully. Check the message before concluding the file or node is wrong.

## Token setup

Reading needs a personal access token (Figma → Settings → Security → Personal access tokens). Keep it in `~/.config/agent-secrets/figma.env` as a `FIGMA_TOKEN=` line, mode 600. If that file is missing, ask the user to create it; do not ask them to paste the token into the conversation. The path is absolute and outside any repository, so it resolves identically from every working directory and every runtime — there is no per-project setup, and no reason to add `FIGMA_TOKEN` to a project's env file.

It deliberately does not live beside this file: the skill ships in a version-controlled plugin that each agent copies into its plugin cache, so a secret placed here would be committed and copied everywhere the skill goes.

Resolve it in this order, preferring an already-exported value so a caller can override without touching the store:

```bash
TOKEN="${FIGMA_TOKEN:-}"
[ -z "$TOKEN" ] && TOKEN=$(sed -n 's/^FIGMA_TOKEN=//p' ~/.config/agent-secrets/figma.env | head -1 | tr -d '"'"'"'\r')
curl -s -H "X-Figma-Token: $TOKEN" "https://api.figma.com/v1/files/$KEY?depth=1"
```

Never let the value reach the transcript, an echoed command line, or a tracked file. Redact before showing output that could carry it: `sed -E 's/figd_[A-Za-z0-9_-]+/figd_<redacted>/'`.

A revoked or under-scoped token returns 403, which is indistinguishable from a wrong file key. When anything 403s, check the token before doubting the key:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Figma-Token: $TOKEN" https://api.figma.com/v1/me
```

200 means the token is good and the fault is the file key, the node id, or that endpoint's scope.

## What REST can and cannot do

Works on any plan:

| Need | Endpoint |
|---|---|
| Enumerate pages | `GET /v1/files/:key?depth=1` |
| Node subtree with fills, text, `boundVariables` | `GET /v1/files/:key/nodes?ids=<id>&depth=N` |
| Render a node to PNG/SVG | `GET /v1/images/:key?ids=<id>&format=png&scale=N` |
| Published styles | `GET /v1/files/:key/styles` |

**Variables are Enterprise-only.** `GET /v1/files/:key/variables/local` needs the `file_variables:read` scope, which is grantable only to full members of an Enterprise org — on other plans the scope does not appear in the token UI at all, and requesting it in an OAuth flow errors before callback. Do not treat its absence as a misconfiguration. Read resolved values off the canvas instead (below).

Also not available through REST: Code Connect mappings, and any write/generate operation.

## Reading tokens off the canvas

When the variables endpoint is out of reach, the design file itself usually carries the values in a machine-readable way. Inspect the tree before writing an extractor — conventions vary per file:

- **Scales as CSS text layers.** Many token pages paste an authored `:root { --space-4: 4px; … }` block as a text node. Walk for `type === "TEXT"` and match `characters` against `/--[a-z-]+:/`. This is the highest-fidelity source: it is what the designer intends, already in CSS syntax.
- **Swatch frames.** Colors typically appear as named frames wrapping a rectangle, e.g. `Chip/gray-700` → `RECTANGLE` whose `fills[0].color` is the value. Convert with `Math.round(channel * 255)` per channel; `fills[0].opacity` carries alpha (it is separate from `color.a`).
- **Alias documentation.** A semantic token card often nests a frame naming the primitive it points at (e.g. `Card/color-text-secondary` containing `PrimRef/color-gray-700`). That recovers the semantic→primitive mapping the variables endpoint would have given.
- `boundVariables` on a node confirms a value is variable-driven and gives the variable id, but ids cannot be resolved to names without the variables endpoint. Use the frame names instead.

Write the extractor to a file and run `node /tmp/x.js` rather than `node -e` with a long inline script — nested quotes in shell heredocs break easily.

## Verifying rather than trusting

Page and node ids are **not stable**; files get restructured and pages renamed. Always re-enumerate pages instead of reusing recorded ids, and treat any id written in a doc as a hint.

**Hidden-layer trap.** REST returns hidden nodes by default — no special flag needed — marked only by `"visible": false`. Before calling a visually redundant node (the same text or content appearing twice in one instance) a stray duplicate or a design mistake, check that node's `visible` field first: `visible: false` means the designer turned it off on purpose, not evidence of an error.

**Depth-cutoff trap.** `GET /v1/files/:key/nodes?ids=<id>&depth=N` stops recursing at depth `N`; a node sitting at or near that cutoff can come back with `"children": []` or fewer children than it actually has, with nothing distinguishing "the API stopped here" from "this is genuinely empty." Before concluding a node's content was removed because `children` came back empty or short, check how deep that node sits relative to the requested `depth` — if it's near the limit, re-fetch that node id directly, or the same root with a larger `depth`, before trusting the emptiness.

When comparing design values to code, diff programmatically and report all four buckets: matches, value mismatches, present-in-design-only, present-in-code-only. A count of matches alone hides missing tokens. Expect some differences to be intentional (naming that collides with a framework namespace, human-readable labels like `black 8%` versus `overlay-black-8`); record those as deliberate rather than re-litigating them each time.

Keep project-specific conventions — actual page ids, frame naming, which differences are intentional — in that project's own docs, not here.

# Tweaks — declaring the props an artboard exposes as controls

Read this when a task asks you to add, change or remove a Tweaks control. `SKILL.md` covers what the
panel is and where its schema lives; this file covers the vocabulary and the traps.

## The schema

One JSON object in the `data-props` attribute on the `<script data-dc-script>` tag. Each key is a
prop the artboard reads; each value describes the editor to render for it.

```json
"timeFormat": {"editor":"enum","options":["relative","absolute"],
               "default":"relative","tsType":"'relative'|'absolute'","section":"Time format"}
```

| Key | Values / where it applies |
|---|---|
| `editor` | `"text"` `"color"` `"int"` `"float"` `"range"` `"boolean"` `"enum"` `null` |
| `options` | enum only |
| `min` / `max` / `step` / `unit` | numbers and range |
| `section` | groups props under a heading |
| `editor: null` | callbacks, ReactNode, objects |

Declare a prop, read it in `renderVals()`, and the control appears.

- The attribute is HTML-escaped in the file (`&quot;`). Match that when you patch it.
- For `color`, a 3–4 item list of hex strings, or 2–5-hex palette arrays, renders curated swatches.
- `$preview: {"width","height"}` sets the preview size for sized fragments such as cards and modals;
  omit it for full pages. Keys beginning with `$` are meta and are stripped from `props` — see
  `parseDataProps` in the project's `support.js`.
- **`default` seeds the editor, not the runtime.** Read every prop as `this.props.x ?? fallback`, or
  a standalone render gets `undefined`. The panel's **Save as defaults** button is what writes a
  chosen value back into `default`.

Never declare a prop the component does not read. A control that changes nothing reads as a broken
feature, and the reviewer has no way to tell it apart from a bug in the artboard.

## Choosing knobs

Copy text and single colours are already editable in place on the canvas, so a knob for those is
wasted panel space. Reserve tweaks for what in-place editing cannot do:

- functional behaviour, such as sort order or a display mode
- alternative UI treatments of the same data
- one flag that changes copy or colour across many elements at once

Parameterising an `accent` colour earns its place twice over: it also forces hardcoded colour
literals into a derived palette, which is design-token work that ports to a real application.

## Recovering this vocabulary after a rejection

The table above is a snapshot of an undocumented surface. When a value is rejected as a syntax
error, refresh it from the bundle rather than guessing.

**This is the one procedure in this skill that cannot run headless** — it needs an open canvas to
read the entry-bundle URL. Run the step 1 expression in the canvas page through any browser
devtools console or browser-eval tool you have.

```bash
# 1. the entry bundle is only a loader; read its URL from the open canvas:
#    JSON.stringify([...document.querySelectorAll('script[src]')].map(e=>e.src))

# 2. pull it, list the chunks it references
curl -sL -o app.js "<entry-url>"
grep -oE "assets/v1/[A-Za-z0-9_.-]+\.js" app.js | sort -u > chunks.txt

# 3. fetch them all — about 115 files, ~6 MB
sed 's|^|https://assets-proxy.anthropic.com/design/v2/|' chunks.txt > urls.txt
mkdir -p chunks && (cd chunks && xargs -P 12 -n 1 curl -sL -O < ../urls.txt)

# 4. find the tool definitions
grep -l "tsType" chunks/*.js
```

Chunk filenames do not describe their contents — the props documentation lived in one named
`desktop-auth-wait-*.js`. Search by string, never by filename. Good anchors: `tsType` and
`Save as defaults`.

What you want is the `d_props_json` / `b_props_json` tool description. It states the editor
vocabulary, the per-editor extras and the runtime caveats in prose.

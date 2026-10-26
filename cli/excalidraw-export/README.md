# Headless Excalidraw PNG export

A proof of concept that renders a local `.excalidraw` scene through Excalidraw's
`exportToCanvas` in headless Chromium. It writes one PNG, including content far
outside the browser viewport. It does not scroll, stitch screenshots, open a
visible window, or upload the scene.

This is a separate local-file exporter. It does not read collaboration rooms or
change the `excalidraw-board` command.

## Setup

Install [Node.js](https://nodejs.org/en/download), then run from this directory:

```sh
npm ci --ignore-scripts
node node_modules/playwright/cli.js install chromium
```

Dependencies are local to this directory and pinned in `package-lock.json`.
See [Playwright's browser documentation](https://playwright.dev/docs/browsers)
for browser installation details. Alternatively, pass an existing compatible
Chrome executable with `--executable-path` as shown below. This bypasses the
managed Playwright browser download, not headless mode.

## Export

From this directory:

```sh
node export.mjs example.excalidraw large.png
node export.mjs example.excalidraw detail.png --region 400,300,2000,600 --scale 2
```

On a Mac with Chrome installed:

```sh
node export.mjs example.excalidraw large.png \
  --executable-path '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

Existing output files are never overwritten. The command prints a JSON receipt
with output dimensions, byte count, elapsed time, and loaded font families.
The browser and temporary HTTP server close before the command exits.

`--region x,y,width,height` is relative to the top-left of the full exported
scene, with zero padding, **before scaling**. It is not an absolute Excalidraw
coordinate or a browser viewport coordinate. For example, `80,80,100,100` with
`--scale 2` produces a 200 by 200 PNG. Content beyond the scene is filled with
the scene background. Omitting `--region` exports the entire scene.

To render only the green middle rectangle, or only the heading and rectangle:

```sh
node export.mjs example.excalidraw middle.png --ids middle
node export.mjs example.excalidraw heading-and-middle.png --ids heading,middle
```

`--ids` takes comma-separated exact element IDs and sends only those objects
to the renderer. `--ids middle` produces a 600 by 400 PNG rather than allocating
the sample's full 12,000 by 8,000 canvas. IDs are matched exactly, with surrounding
whitespace trimmed. The original scene stacking order is preserved regardless
of the order of IDs in the argument.

To select everything except the green middle rectangle in the sample:

```sh
node export.mjs example.excalidraw selected.png --exclude-ids middle
```

`--exclude-ids` takes comma-separated exact element IDs and removes those
objects from the renderer's input before the browser draws anything. It does
not crop or paint over an existing PNG. The sample still exports at 12,000 by
8,000 because the remaining objects retain that extent. The original scene
file is not modified. Unknown IDs, empty IDs, and an empty selection are errors.

`--ids` and `--exclude-ids` are mutually exclusive. Neither selection mode
expands through groups, frames, bound text, or arrows. Explicitly name each
object to include or omit. The selected objects determine output bounds, so
selecting a subset or excluding an outermost object can change image dimensions.
When combined with `--region`, the crop is relative to the selected scene's
export bounds. Without either selection flag, all live objects are rendered.

The server binds only to loopback and serves the bundled renderer and fonts
from the installed Excalidraw package. Browser requests to external origins are
blocked. Embedded images must use `data:image/` URLs. Use trusted scene files:
this PoC is not a hostile-input rendering service or a security sandbox.

## Fonts and rendering

The official canvas exporter waits for element fonts before drawing. Fonts are
served locally, including Excalifont and the Xiaolai fallback for Korean text.
Failed font loads stop the export. The PNG has no embedded editable scene JSON.

Installed OS fonts and browser versions can still affect output. Successful
font loading is not proof that every possible glyph is available. This does
not promise pixel identity with the current excalidraw.com deployment, which
may use a different Excalidraw version. Iframes and video are not rendered.

## Size and resource limits

The viewport stays at 800 by 600. The export canvas can be much larger because
this uses the export API instead of a screenshot.

The default limit is 100 million pixels per canvas, with a 32,767-pixel limit
on each axis. `--max-pixels` changes the pixel budget. These are conservative
PoC guardrails, not guarantees that Chromium can allocate every permitted size.
`--timeout-ms` defaults to 120,000 and applies to browser launch and rendering
after the bundle is built.

ID filtering happens before rendering and canvas allocation. The pixel limit
therefore applies to the selected scene, not objects left out of the selection.
A crop currently renders that entire selected scene first, then copies the
region into a second canvas. A 12,000 by 8,000 canvas alone needs about 384 MB
of raw RGBA memory. Cropping can require another canvas of similar size, plus
browser and PNG encoding overhead. The selected-scene limit applies even to a
small crop. Very large selections may need a lower `--scale`. Unbounded-size
export and direct region-only rendering are outside this PoC.

## Checks

```sh
npm test
# Or use an existing Chrome installation:
CHROMIUM_EXECUTABLE_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm test
```

The tests launch a real headless browser, decode the PNG, and check distant
corner pixels on a 12,000 by 8,000 scene. Excluding the green middle rectangle
must replace its pixels with white while every other pixel, including text,
remains identical to the full export. The tests also check local Latin/Korean
font loading, visible text, single-ID export under a reduced pixel budget,
multi-ID stacking order, scaled cropping with frame children, invalid or
conflicting selections, input limits, and output preservation. They do not
contact excalidraw.com.

`npm audit` currently reports 11 findings in the pinned Excalidraw dependency
tree, including two high-severity findings. This is a local PoC, not a
production-ready service. Dependency remediation and hostile-input isolation
are required before exposing it as a service.

Tested with Node.js 24.21.0, Playwright 1.58.2, Excalidraw 0.18.1, and headless
Google Chrome 156.0.8078.47 on macOS arm64.

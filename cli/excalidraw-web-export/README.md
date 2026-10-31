# Excalidraw web PNG export

Export selected objects through an existing Excalidraw deployment in headless
Chrome. The script imports a selected snapshot into an isolated browser context,
opens the app's Export image dialog, and saves its native PNG download. It does
not take a screenshot, stitch tiles, use private React state, or load a local
Excalidraw renderer.

## Setup

Install [Node.js](https://nodejs.org/en/download) 24.21 or newer and npm. From the
repository root:

```sh
sh cli/excalidraw-web-export/install.sh
```

The installer copies the command and lockfile into
`~/.local/share/excalidraw-web-export`, installs pinned production dependencies
locally with a three-day release-age gate, and links
`~/.local/bin/excalidraw-web-export`. Put `~/.local/bin` on `PATH`. Rerun the
installer to update. It refuses to replace an unrelated command and does not
install or update agent plugins, `excalidraw-board`, or browsers.

On macOS, an existing Chrome at its standard application path is used by default.
`--executable-path` overrides `CHROMIUM_EXECUTABLE_PATH`, which overrides that
automatic lookup. Otherwise the command uses Playwright-managed Chromium.
Install that browser explicitly if needed:

```sh
node "$HOME/.local/share/excalidraw-web-export/node_modules/playwright/cli.js" install chromium
```

See [Playwright's browser documentation](https://playwright.dev/docs/browsers).
The only direct runtime npm dependency is `playwright` 1.58.2. `pngjs` 7.0.0 is
used only by tests. React, React DOM, Excalidraw, and esbuild are not installed
by this package. The deployed app supplies its own renderer and fonts.

## Export a saved room

Install `excalidraw-board` separately using its [README](../excalidraw-board/README.md).
The exporter looks it up on `PATH` and never installs or updates it. Use an
already registered room ID prefix:

```sh
excalidraw-web-export --room-id ROOM_PREFIX selected.png --ids a1,b2
```

For a Mac with Chrome installed:

```sh
excalidraw-web-export --room-id ROOM_PREFIX selected.png --ids a1,b2 \
  --executable-path '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

The script requires the `snapshot` command in `excalidraw-board`. Check
`excalidraw-board --help` and update the command separately if it is absent.
It runs `excalidraw-board snapshot --id ROOM_PREFIX`, forwarding the ID filter.
That command reads saved elements, downloads only their referenced image files,
and decrypts those files with the registered room key. The selected scene and
its embedded files are imported into the deployment's blank canvas. No room
key or link is passed to the browser.

The exporter never joins collaboration or writes room elements. The JSON
receipt includes the read revision and exported IDs. Unsaved browser edits
are not captured. Room snapshots use a white background because scene
persistence does not include the room's app state.

## Export a local file

```sh
excalidraw-web-export scene.excalidraw middle.png --ids middle
excalidraw-web-export scene.excalidraw selected.png --ids heading,middle
excalidraw-web-export scene.excalidraw without-middle.png --exclude-ids middle
```

This directory includes the large sample `example.excalidraw`.
Omit both ID options to export every live object. The options are mutually
exclusive. IDs match exactly, with whitespace trimmed. Unknown or deleted IDs,
empty IDs, and an empty result are errors. Stacking order stays in scene order.
Groups, frames, and bound text are not expanded automatically. Name every
object needed by the export. The input file is not modified.

The app exports at its default 1x scale with 10 scene units of padding on each
side. For the repository sample, `--ids middle` produces 620 by 420 pixels,
while the entire scene produces 12,020 by 8,020 pixels. The command has no
`--region`, `--scale`, or preallocation pixel budget options. Selection happens before import, so unselected objects do not enlarge
the export canvas. `Embed scene` is explicitly disabled.

## Why download instead of clipboard

Both paths use the app's PNG renderer. Downloading avoids writing the system
clipboard, requesting clipboard permissions, and reading the PNG back across
the browser boundary. Playwright saves a browser-managed temporary file and
Node copies it without loading the PNG into a JS buffer or base64 string. The
script reads only its 24-byte header to verify the PNG signature and dimensions.

This reduces transfer steps and avoids clipboard interoperability. Peak RAM
has not been benchmarked against clipboard export. The browser's canvas remains
the main memory cost. A 96MP canvas alone is about 384 MB of raw RGBA data, before
preview, encoding, and browser overhead. Arbitrarily large exports are not
guaranteed.

## Limits and safety

- Use trusted scenes and deployments. The default is `https://excalidraw.com`.
  `--url` accepts another deployment without query parameters, room fragments,
  or embedded credentials. Its UI must support the English labels and shortcuts
  used here. The deployment can change independently of this package.
- The browser context is temporary, has no existing login, and closes after
  export. The user's own browser profile and clipboard are not used. File
  picker APIs are disabled in this context to select the app's regular browser
  download fallback instead of an OS save dialog.
- Browser non-GET requests, WebSockets, and cross-origin navigations are blocked.
  Asset GET requests still need network access. This is not a hostile-input
  sandbox or a guarantee against a malicious deployment leaking imported data.
- Room images are fetched by `snapshot` from the encrypted room-file store.
  PNG and JPEG room uploads have been verified end to end. Missing, inaccessible,
  corrupt, or unsupported encrypted files fail instead of producing image
  placeholders. The snapshot reader supports the version-2 AES-GCM/pako file
  format and caps each image data URL at the service's 4 MiB. Image data above
  48 MiB in total, or snapshot output above 64 MiB, produces a stderr warning
  that names the limit and the byte counts. Output above 1 GiB fails. Warnings
  from `excalidraw-board` are passed through to stderr.
- Local scenes can embed PNG/JPEG/WebP/GIF files. SVG image payloads are rejected.
  Iframes and video are not supported by this PoC.
- Existing output files are never overwritten. Browser downloads are copied
  with exclusive creation. The default launch/export deadline is 120 seconds,
  configurable with `--timeout-ms` up to 600,000 ms. There is no hard memory cap.
- Creating test rooms is separate from this script. Exporting only reads an
  explicitly selected existing room. It does not create or delete rooms.

## Checks

From this directory, install test dependencies locally before running checks:

```sh
npm ci --ignore-scripts
npm test
CHROMIUM_EXECUTABLE_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:live
```

The default tests check rejected inputs, output preservation, standalone
installation and updates, and command collision protection without network
access. Installation tests reuse the npm cache populated by `npm ci`. Live tests explicitly opt into the deployed app. They decode actual
PNG downloads, verify single and multiple IDs, visible text, and embedded
raster images, and compare a 96MP full export against an export omitting only
the green middle object.
They do not create or modify shared rooms.

For a separate real-room image check, the existing installed `excalidraw-board`
must also support `image` uploads:

```sh
CHROMIUM_EXECUTABLE_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:room-live -- --output-dir /path/to/new-artifacts
```

This opt-in check creates a disposable remote room and uploads PNG and JPEG
patterns. It installs the checkout's snapshot-capable board CLI and web exporter
only into a private test HOME, leaving the user's installed commands untouched.
It invokes that installed exporter from PATH and verifies recovered source bytes,
selected PNG pixels, duplicate image placements, and unchanged room revision and
elements. The printed test HOME contains room
credentials and is retained for inspection. Do not publish it. Remote test
rooms are not deleted by the check and have no expiry guarantee.

Tested with Node.js 24.21.0, Playwright 1.58.2, headless Chrome 156.0.8078.47 on
macOS arm64, and the deployed excalidraw.com UI.

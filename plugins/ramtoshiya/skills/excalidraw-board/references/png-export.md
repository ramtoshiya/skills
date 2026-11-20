# PNG export {:#png-export}

When the user requests a PNG, look up `excalidraw-web-export` on `PATH`. If it
is missing, name the command and `sh tools/excalidraw-web-export/install.sh`, then
stop. Do not install, build, or update it from the skill. Its README owns browser
setup. Room exports also need an `excalidraw-board` version whose help lists
`snapshot`. If absent, report the required CLI update rather than working around
it with room keys or browser internals.

Find the intended registered room and read its outline and relevant objects
before choosing exact element IDs. Ask when the room or selection is ambiguous.
Use the deployed app's native download through the exporter:

```sh
excalidraw-web-export --room-id <prefix> selected.png --ids a1,b2
```

Use `--exclude-ids` only when the user asks for all objects except those IDs.
Omit both filters only for an explicitly requested whole-board export. Groups,
frames, and bound text are not expanded automatically, so include every needed
object ID. PNG and JPEG room images are recovered by `snapshot` along with the
selected elements. Missing or corrupt image files stop the export, not silently
produce placeholders. A complete local scene can be exported without room access.

This exports saved state in a separate headless browser, not unsaved edits in a
collaborator's tab. It does not join or modify the room. Do not substitute a
viewport screenshot, scroll stitching, or a clipboard round trip. Check the JSON
receipt's revision, `elementIds`, dimensions, and `method: "app-download"` before
claiming success. Deliver the PNG through the current surface's file or attachment
mechanism. Do not publish its runtime-local path or imply live room display was
verified. Keep any decrypted scene backups private unless explicitly requested.

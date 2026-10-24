---
name: excalidraw-board
description: Use when a user asks agents to read or draw on a shared excalidraw.com room, or a collaborator references a room id, revision, and element ids. Uses the separately installed excalidraw-board command.
---

# Shared Excalidraw boards

Use structured room elements to exchange sketches with people and other
agents. This command is a proof of concept against the free site's internal
protocol. Use disposable rooms first. It is not the Excalidraw+ CLI and does
not create a design system or implement an application UI.

## Prerequisites {:#prerequisites}

Look up `excalidraw-board` on `PATH`. If missing, stop and tell the user to run
`sh cli/excalidraw-board/install.sh` from their clone of this repository. The
skill must not install, update, or build the command. Its
`cli/excalidraw-board/README.md` owns the install instructions and limitations.

The command needs Node.js 24.21 or newer. Room keys live in its private
per-user SQLite room list, not in projects or installed plugin folders.
Never write a room link into a repository, document, or tool-written log.
Only run `room link` when the user asks for the link, because its output puts
the key into the session transcript. Never navigate or edit the user's own
browser tab without permission. Use a separate tab for rendering checks.

## Drawing protocol {:#drawing-protocol}

1. Run `excalidraw-board room list` to find a registered room. Prefer its
   unique id prefix to a name, since names can repeat. Do not guess which room
   the user means if more than one plausible room exists.
2. Run `excalidraw-board read --id <prefix> --outline` first, then read the
   relevant frame or element ids. Reads show persisted state, not every
   unsaved browser edit.
3. Outline each idea with a plain, transparent rectangle and a separate title
   text element. Keep images, text, annotations, and connectors at board level
   without `frame` membership. Real frames clip their members, which can hide
   arrows between screenshots. Use a real frame only when the user explicitly
   requests its clipping behavior. To replace existing frames, add rectangle
   boundaries, clear members' `frame` fields to null, and delete only the frames.
   Preserve content positions and connector bindings. Supply text width and
   height yourself. Keep batches small. Use `image` for existing PNG/JPEG files,
   not an image element in a `write` batch. Path creation is unsupported.
4. Write a single batch on stdin. Use explicit, unique element ids when a
   retry must not duplicate an add. Send only changed fields in updates, not
   stale whole elements. Never supply managed version, nonce, seed, index,
   deletion, or timestamp fields.
5. Check `saved`, `notified`, the revision, and changed ids in the receipt.
   A save followed by a notification failure is not an unsaved batch. Read
   before retrying. No-op writes have no changed ids and do not notify.
6. Draw first, then message through the agent's existing communication tool:
   `@codex drew in room id EDAL, rev 1790670316138923, ids a1,b2`.
   Use an actual room prefix, revision, and changed ids from the receipt.
7. A recipient runs `excalidraw-board read --id EDAL --ids a1,b2`. If the
   revision is lower than the referenced revision, read again. The command
   does not wait for messages, watch a room, or notify another agent itself.

## Commands {:#commands}

```sh
excalidraw-board room create design-review
excalidraw-board room list design
excalidraw-board read --id <prefix> --outline
excalidraw-board read --id <prefix> --frame <frame-id>
excalidraw-board read --id <prefix> --group <group-id>
excalidraw-board read --id <prefix> --ids a1,b2 --full
excalidraw-board image --id <prefix> --file screenshot.png --element-id capture-home --x 40 --y 80 --width 406
```

Write input is one JSON object, for example:

```json
{
  "add": [
    {"id":"idea-boundary","type":"rectangle","x":0,"y":0,"w":600,"h":400,"backgroundColor":"transparent"},
    {"id":"idea-title","type":"text","x":20,"y":16,"w":240,"h":30,"text":"Login idea"},
    {"id":"a1","type":"rectangle","x":40,"y":80,"w":240,"h":120},
    {"id":"b2","type":"text","x":60,"y":100,"w":200,"h":30,"text":"Login"}
  ],
  "update": [],
  "delete": []
}
```

Pass it through stdin to `excalidraw-board write --id <prefix>`. Keep temporary
batch files in the host's scratch directory, not the repository.

When the user supplies a link and asks to add the room, use `room import
--name <name> --stdin` with the link on stdin. Import only reads the remote
scene. Do not pass raw links to `read` or `write`. A missing saved room reports
`room is gone`. Do not silently create a replacement.

## Image uploads {:#image-uploads}

Only upload files the user authorized for sharing. Files are encrypted with
that room's key, but uploading sends them to an external service and anyone
with the room link can decrypt them. The CLI does not generate or export images.

Use `image --file` for PNG/JPEG uploads with an explicit, unique `--element-id`
for each placement. Use plain rectangle boundaries and separate captions for
screenshot layouts. Omit `--frame` unless the user requested a real clipping
frame. Keep the same file and element id when retrying. Each file's base64 data
URL must fit the service's 4 MiB limit. `--width` changes display size, not the
uploaded file's byte size.

Check `fileSaved` as well as `saved`, `notified`, revision, and changed ids.
The command verifies the uploaded file before creating its image element.
A scene failure can still leave an uploaded file. Read before retrying, and do
not create a second element id to conceal an ambiguous result. The README owns
the complete size limits and receipt semantics.

## Verification {:#verification}

Read back changed ids and verify their fields, not just the count. For a visual
check, open an already authorized room link in a separate browser tab and
inspect the frame. An open browser must show a write without reload before
claiming live browser delivery. Persistence receipts alone do not prove that.
To make a picture, use Excalidraw's own Export image action in the browser.

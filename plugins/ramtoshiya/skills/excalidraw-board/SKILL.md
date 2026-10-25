---
name: excalidraw-board
description: Use when a user asks agents to read or draw on a shared excalidraw.com room, or a collaborator references a room id, revision, and element ids. Uses the separately installed excalidraw-board command.
---

# Shared Excalidraw boards

Use structured room elements to exchange sketches with people and other
agents. This command is a proof of concept against the free site's internal
protocol. Use disposable rooms first. It is not the Excalidraw+ CLI and does
not create a design system or implement an application UI.

## Delivery {:#delivery}

Treat a request to show an Excalidraw board as a shared-room task. Use this
skill even when the user supplies no room link. Find the intended registered
room, or ask which room to use when the choice is unclear. A local
`.excalidraw` file does not fulfill a board request. Create or attach a file
only when the user asks for an export or backup, or agrees to a file fallback.
A file-only request needs no room write.

Report the room name or id prefix, revision, and relevant element ids without
its secret link. Distinguish saved content, sent notifications, and observed
browser display. If browser verification is unavailable, say what was saved
and read back, and that browser display was not verified. Do not call this
live delivery or imply the user has seen the result.

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
3. Put each idea in a named frame. Add shapes and text as separate elements
   with `frame` set to that frame's id. Supply text width and height yourself.
   Keep batches small. Do not use the tool to create images or path elements.
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
```

Write input is one JSON object, for example:

```json
{
  "add": [
    {"id":"idea-frame","type":"frame","name":"Login idea","x":0,"y":0,"w":600,"h":400},
    {"id":"a1","type":"rectangle","frame":"idea-frame","x":40,"y":80,"w":240,"h":120},
    {"id":"b2","type":"text","frame":"idea-frame","x":60,"y":100,"w":200,"h":30,"text":"Login"}
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

## Verification {:#verification}

Read back changed ids and verify their fields, not just the count or revision.
If expected ids are missing or fields differ, stop and report the mismatch.
A newer revision alone is not proof that the intended content still exists.
Do not replace the missing content with a file and call the board complete,
blindly recreate it, or attribute the loss to a browser without evidence.

For a visual check, open an already authorized room link in a separate browser
tab and inspect the frame. An open browser must show a write without reload
before claiming live browser delivery. Persistence receipts alone do not prove
that. To make a picture, use Excalidraw's own Export image action in the browser.

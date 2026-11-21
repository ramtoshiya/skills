---
name: wjrj-board
description: Use when a user asks agents to read, draw on, render, or show a wjrj board, or a collaborator references a wjrj board name, revision, and element ids. wjrj is a local macOS app whose boards hold live Markdown, images, and web pages with markup. Uses the separately installed wjrj command. Not for excalidraw.com rooms, which use excalidraw-board.
---

# wjrj boards

wjrj is an app on this Mac. Its board holds material, which is live Markdown
files, images, and web pages, with markup drawn on top: rectangles, ellipses,
text, arrows, and freehand strokes. The person marks the board up and pins
comments. Agents on the same Mac read and write the board through the `wjrj`
command, which talks to the running app's local API. Nothing leaves this Mac,
and an agent on another machine cannot use it.

## Delivery {:#delivery}

Treat a request to show something on a wjrj board as a board task. Find the
intended board, or ask which board to use when the choice is unclear. Create a
new board only when the user asks for one. A local file does not fulfill a
board request.

Report the board name, the revision, and the changed element ids. Keep three
claims apart:

- Saved. The write receipt and a read-back confirm the elements.
- Rendered. `wjrj image` drew the saved board in wjrj's own renderer.
- Seen. Open wjrj windows show a write without reload, but no command tells
  you what the person's screen shows. Do not claim the person saw it.

## Prerequisites {:#prerequisites}

Look up `wjrj` on `PATH`. If it is missing, stop and tell the user to run
`npm run package` and then `npm run install-cli` in their wjrj checkout. Do not
install, build, or update the command yourself.

The wjrj app must be running. When `wjrj` says the app is not answering, ask
the user to start it. When it says the running app is older than the command,
ask the user to quit and reopen wjrj. Do not start or relaunch the app
yourself.

The command reads an agent key from wjrj's `api.json` in the app's support
folder, and reads it again after a refused request. Never print, log, copy, or
quote the agent key. Do not read `api.json` or send requests with the key on
your own command line, because both put the key into the transcript. Use the
`wjrj` command for every board operation.

## Drawing protocol {:#drawing-protocol}

1. Run `wjrj boards` and pick the board by name. Do not guess when more than
   one board fits the request.
2. Run `wjrj read <board> --outline` first, then read the elements you need
   with `--ids`. A read lists the materials its elements show, with file name
   and path or web address. Read `comments` too. They are the person's notes.
   Agents cannot write comments.
3. Draw an idea as a `rectangle` with its title in `label`. Use `text` for
   free-standing words and give it `width` and `height`. Put long notes in a
   Markdown file, register it, and place it as material instead of a large
   text element. Draw a connector as an `arrow`, never as a text glyph.
   Bind its ends with `start` and `end`, such as
   `{"element":"idea-a","fixedPoint":[1,0.5]}`. A fixed point is a fraction
   of the target's box, so `[1,0.5]` is the middle of its right edge. The
   renderer draws a bound end at that point. Set `x` and `y` to the start
   point and give `points` starting at `[0,0]` that end at the end point.
4. Write one batch on stdin: `wjrj write <board> < batch.json`. Give every
   added element an explicit, unique id, so a retried add is a no-op instead
   of a duplicate. Send only changed fields in an update. Never send `seed`.
   Send `index` only to change stacking order. Keep batches small. Keep batch
   files in the host's scratch directory, not in a repository.
5. Check the receipt's `revision` and `changed` ids. A refused batch exits 1,
   prints the problems, and saves nothing. Fix the batch and send it again.
   An empty `changed` list means the batch changed nothing.
6. Tell the other party in the conversation, for example
   `drew on wjrj board calm-otter, rev 17, ids idea-a,idea-b,a-to-b`. Use the
   actual board name, revision, and changed ids from the receipt.
7. A recipient runs `wjrj read <board> --ids <ids>`. If the board's revision
   is past the referenced one, `wjrj read <board> --since <rev>` shows what
   changed after it, including deletions. The command does not watch a board
   or notify anyone.

## Verification {:#verification}

Read back the changed ids and compare their fields, not just the count or the
revision. A read with `--ids` lists ids it did not find under `missing`. If
ids are missing or fields differ, stop and report the mismatch. Do not
recreate the elements blindly. `wjrj history <board>` and
`wjrj read <board> --at <rev>` show when and how the board changed.

For a visual check, run `wjrj image <board> <file.png> --ids <ids>` and look at
the PNG. Check that its `revision` is at least the receipt's revision. The
image shows live material as it currently looks, including unsaved text, and
leaves out comment pins.

## Showing the board {:#showing}

- In bb, run `wjrj snapshot <board> "$BB_THREAD_STORAGE/<name>.html"` and show
  the file with the inline-vis directive, using `source="thread-storage"`.
  The snapshot is a dated, read-only copy with a link that opens the board in
  wjrj.
- Elsewhere, attach the PNG from `wjrj image` through the host's file or
  attachment mechanism.

## References {:#references}

For every command, its output, and the element fields, read
[`references/commands.md`](references/commands.md).

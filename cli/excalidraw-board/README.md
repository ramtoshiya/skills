# excalidraw-board

A proof-of-concept command for reading and editing shared rooms on
excalidraw.com. It saves encrypted elements to the room's persistence service
and sends changes to open collaborators. It needs no browser to write a board.

This uses the free site's internal protocol, not a supported Excalidraw API.
It can break when the site changes. Use disposable rooms before trusting it
with important work.

## Install

Install [Node.js](https://nodejs.org/en/download) and put `node` on `PATH`.
This command requires Node.js 24.21 or newer. From this repository:

```sh
sh cli/excalidraw-board/install.sh
```

The installer copies the command to `~/.local/share/excalidraw-board/` and
links it at `~/.local/bin/excalidraw-board`. Put `~/.local/bin` on `PATH`.
Run the installer again to update. It downloads no packages and does not
install agent plugins. The plugin's separate skill uses this command on `PATH`.

## Rooms

```sh
excalidraw-board room create sketch
excalidraw-board room list
excalidraw-board room link --name sketch
```

Creation saves an empty board immediately. Only `room link` prints its secret
link. Anyone with that link can read and edit the board. Do not put it in
repository files, logs, or issue reports. Link output can enter terminal or
agent transcripts.

To import an existing link without placing it in shell history or process
arguments, copy the link and run this on a Mac:

```sh
pbpaste | excalidraw-board room import --name sketch --stdin
```

Import checks that the saved scene exists and decrypts. It does not write to
the room. Rooms are shared across projects in
`~/.local/state/excalidraw-board/rooms.db`. The directory is private and the
database has mode `0600`. The database contains encryption keys. Back it up as
a secret, not as part of this repository.

Names match exactly. Duplicate names are allowed, with the newest registration
winning and a warning. Prefer the unique room-id prefix shown by `room list`.
An imported room already in the list keeps its existing name. The optional
argument to `room list` filters name prefixes. Using `--name` or `--id` updates
the room's last-used time, including when the remote operation fails.

## Read and write

```sh
excalidraw-board read --name sketch --outline
excalidraw-board read --name sketch
excalidraw-board read --name sketch --ids box
printf '%s\n' '{"add":[{"id":"box","type":"rectangle","x":100,"y":100,"w":240,"h":120,"backgroundColor":"#a5d8ff"}]}' |
  excalidraw-board write --name sketch
printf '%s\n' '{"update":[{"id":"box","x":160}],"delete":[]}' |
  excalidraw-board write --name sketch
```

Read emits a revision header followed by one JSON object per live element.
The revision is a decimal string of microseconds from Firestore's `updateTime`,
not the sum of element versions. Short output uses `w`, `h`, `frame`, and
`groups`, omits managed and default-valued fields, and rounds top-level numbers
to two decimal places. Use `--full` for stored fields and precision. Filters
`--frame`, `--group`, and `--ids` select a part of the board. `--outline` lists
frames and top-level groups, their bounding boxes, and member counts.
Outline ids and labels are JSON strings. Control characters in terminal output
are escaped. Outline boxes do not account for rotated elements.

Write accepts one JSON object with optional `add`, `update`, and `delete`
arrays. Updates carry an id and just the fields to change. Deletes carry ids
and save tombstones. Adds need a type and may omit the id. Text elements need
explicit dimensions, because this command does not measure fonts. Existing
unknown fields and element types survive updates. Updates cannot change an
element's type, including replacing it with a null or empty value. Element
versions, nonces, seeds, indices, deletion state, and timestamps are managed
by the command.

A write reads the saved scene, collects available peer updates, and saves with
an `updateTime` precondition. On conflict it rereads and reapplies the original
field patches, up to six attempts. A no-op does not save or broadcast. A missing
saved room is an error, never a request to recreate it.

After saving, the command rereads persistence and requires every changed
element to match its authored content, version, and nonce. JSON object key
order does not matter. If any changed element is missing, altered, or
superseded by a higher version, the command reports that the save succeeded
but verification failed and sends no live notification. Read before retrying.
This verifies one saved snapshot, not subsequent changes or active browser edits.

The write receipt distinguishes persistence (`saved`) from sending the live
notification (`notified`). A notification failure after saving exits with code
2. Read before retrying. A successful notification means the socket sent the
message, not that every browser applied it.

## Images

```sh
excalidraw-board image --id <room-prefix> --file screenshot.png \
  --element-id capture-home --x 40 --y 80 --width 406 --frame review-frame
```

`image` accepts PNG and JPEG files. It reads dimensions from the file header,
keeps the aspect ratio, and uses the original pixel width unless `--width` is
set. Coordinates default to zero. An optional `--frame` must name an existing
live frame. Image bytes are not resized or re-encoded.

The command compresses the image data URL and metadata, encrypts them with the
room key, and uploads them to Excalidraw's file storage. It downloads and
verifies the encrypted file before saving an image element with `status:
"saved"`. Only then does it notify collaborators. Ordinary `write` batches
cannot add image elements without this file upload.

The service's 4 MiB limit applies to the base64 data URL, so the source image
must be slightly smaller than 3 MiB. The command also rejects empty dimensions
and images larger than 100 million pixels. It does not inspect EXIF orientation
or decode the full image, so export rotated JPEGs in their intended orientation
before uploading.

File ids are SHA-1 hashes of the source bytes. Repeating a command with the same
file and element id reuses the verified file and does not duplicate the image.
The default element id is `image-<file-id>`. Set different `--element-id` values
to place the same image more than once. Reusing an element id for different
file contents is rejected. Reusing it for the same file updates placement and
size, so read the room before retrying after another person edits that image.

Receipts include `elementId`, `fileId`, `fileSaved`, and `uploaded` alongside the
scene revision, changed ids, `saved`, and `notified`. File upload and scene save
are separate operations. A failed scene save can leave an unreferenced encrypted
file. Read the room before retrying, and use the same element id. Uploading is
publication to an external service, even though the bytes are encrypted. Anyone
with the room link can decrypt them. There is no file deletion command or
expiry guarantee.

## Batch image uploads

Use one batch instead of running many `image` commands in parallel:

```sh
excalidraw-board images --id <room-prefix> --concurrency 4 < manifest.json
```

The manifest has this shape. Paths are relative to the command's working
directory, not the manifest file:

```json
{
  "images": [
    {"file":"home.png","elementId":"capture-home","x":40,"y":80,"width":406},
    {"file":"contest.png","elementId":"capture-contest","x":486,"y":80,"width":406}
  ]
}
```

Each entry accepts the same placement fields as `image`: `file`, `elementId`,
`x`, `y`, `width`, and optional `frame`. The command validates every entry before
uploading. It accepts 1 to 128 placements. Unique image data URLs above 128 MiB
in total produce a size warning, and only a total above 1 GiB stops the
command. Repeated content is uploaded and verified once, even when it has
several placements. Give each placement a unique `elementId`.

The default concurrency is four, adjustable from one to eight. This is a local
bound, not a measured service limit. Each worker checks, uploads, downloads,
and verifies a file before taking another. Once all files are verified, one
scene writer saves all elements together and sends one relay notification.
Scene contention can still require the writer's existing compare-and-swap
retries. There is no separate scene writer or socket per image.

On a file failure, the command stops scheduling more files and waits for active
workers to finish. It saves no image elements from that batch. Exit code 1
includes a JSON progress receipt on stdout with `saved:false`, verified images,
and file counts, plus an error on stderr. Unverified files can still have reached
storage. Read the room and retry the same manifest, rather than assigning new
ids. A later scene-save failure may be ambiguous, so read before retrying it.

Successful receipts contain an ordered `images` array, `files` counts for
`unique`, `verified`, and `uploaded`, the configured `concurrency`, and `retries`.
`timings` reports `prepareMs`, `fileTransferMs`, `sceneWriteMs`, and `totalMs`.
These are wall-clock phases, not sums of parallel workers' durations. The
single-image command uses the same path and retains its top-level image fields.

Scene reads and content-addressed file requests retry network failures and HTTP
408, 429, 500, 502, 503, and 504 responses. Each request has at most four attempts
within a 60-second budget, with exponential backoff and jitter. `Retry-After`
can lengthen the delay. A requested wait above ten seconds or beyond the budget
stops the command instead of retrying early. Scene writes are never blindly
retried by this HTTP policy because a failed response can hide a successful save.

## Scene snapshots with images

```sh
excalidraw-board snapshot --name sketch --ids screenshot,caption > selected.excalidraw
excalidraw-board snapshot --id ROOM_PREFIX --exclude-ids draft > selected.excalidraw
```

`snapshot` returns one scene JSON object with `revision`, full `elements`, and
embedded `files`. Unlike `read --full`, it retrieves image binaries from room
storage and decrypts them with the registered room key. It fetches only files
referenced by selected live elements, once per distinct file ID. Scene and file
requests are read-only. Groups, frames, and bound text are not expanded.

The output contains decrypted board content and images, but no room key or
secret link. Keep it out of repositories and public logs unless the content
is meant to be shared. Room background state is unavailable and defaults to
white. No image placeholders are returned after a file read or decrypt failure.

Supported encrypted files use the version-2 AES-GCM/pako envelope. Each image
data URL is limited to the service's 4 MiB. A total above 48 MiB produces a size
warning, and only a total above 1 GiB stops the command. Unknown formats, corrupt
envelopes, missing files, and inaccessible files fail explicitly. Downloads
are sequential to bound concurrent transfer memory.

The separate [web exporter](../excalidraw-web-export/README.md) consumes this
snapshot to render selected objects through a deployed Excalidraw app.

## Limits

This is a small usable proof of concept, not the full handoff specification.

- Size limits the command sets itself are soft. Standard input above
  5,000,000 bytes, batch image data above 128 MiB, and snapshot image data
  above 48 MiB still run, with a stderr warning that names the limit, the actual
  byte count, and the soft limit. Only data above 1 GiB is rejected. The
  service's 4 MiB image limit and the relay's payload limit stay hard.
- New rectangles, ellipses, diamonds, text, frames, and PNG/JPEG uploads cover
  the tested drawing path. New line, arrow, and freehand paths are unsupported.
  The tool does not render or export pictures.
- Reads return saved state. A browser can have unsaved edits. The short peer
  bootstrap window on write does not guarantee capture of every in-flight
  browser edit or protect an element being actively edited in the browser.
- The persistence service and live relay are separate. Saving and notifying
  are not one transaction. Network ambiguity after sending a save requires a
  read before repeating an add with a generated id.
- New elements get append-only fractional indices. The command does not repair
  malformed or duplicate indices imported from another client.
- There is no room expiry guarantee, cleanup command, watcher, or messaging
  integration. Deleting a local registration would not delete a remote board.

Tested with Node.js 24.21.0, encrypted persistence and socket delivery, a live
browser update without reload, and independent Node processes writing ten
shapes each into one room and into two rooms with no browser in those rooms.
Image upload is checked against encrypted file storage with readback and an
idempotent retry. A synthetic comparison measures sequential versus four-worker
batch uploads. Neither image check proves browser rendering.

## Run the checks

From the repository root, `node --test test/excalidraw*.test.mjs` runs offline
checks. `node test/excalidraw-live.mjs --live` opts into a service integration
check. It creates three disposable remote boards, runs concurrent installed
CLI processes, verifies saved elements and no-op revisions, checks encrypted
relay delivery, uploads synthetic PNGs with verified retries, compares sequential
and batched image transfers, and checks per-room last-used timestamps. It does
not open a browser or run coding agents. Its private test home is retained at the printed
path, including room keys, so treat that directory as secret.

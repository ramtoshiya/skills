# Image uploads {:#image-uploads}

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

import { webcrypto } from "node:crypto";
import { inflateSync } from "node:zlib";
import { loadScene } from "./protocol.mjs";
import { checkSize } from "./size-limit.mjs";

// excalidraw.com caps each image data URL at 4 MiB. Downloads and decompression stay within it.
const maxFileBytes = 4 * 1024 * 1024;
const snapshotName = "excalidraw-board snapshot image data";
const storage = "https://firebasestorage.googleapis.com/v0/b/excalidraw-room-persistence.appspot.com/o/";

function unpack(bytes, count) {
  const buffer = Buffer.from(bytes);
  if (buffer.length < 4 || buffer.readUInt32BE(0) !== 1) throw new Error("Invalid image envelope");
  const chunks = [];
  let offset = 4;
  while (offset < buffer.length) {
    if (offset + 4 > buffer.length) throw new Error("Invalid image envelope");
    const size = buffer.readUInt32BE(offset);
    offset += 4;
    if (size > buffer.length - offset) throw new Error("Invalid image envelope");
    chunks.push(buffer.subarray(offset, offset + size));
    offset += size;
    if (chunks.length > count) throw new Error("Invalid image envelope");
  }
  if (chunks.length !== count) throw new Error("Invalid image envelope");
  return chunks;
}

async function loadFile(room, fileId) {
  if (typeof fileId !== "string" || !/^[a-zA-Z0-9_-]{1,128}$/.test(fileId)) throw new Error("Invalid image file ID");
  const object = `files/rooms/${room.id}/${fileId}`;
  const response = await fetch(`${storage}${encodeURIComponent(object)}?alt=media`, { signal: AbortSignal.timeout(30_000) });
  if (!response.ok) {
    await response.body?.cancel();
    throw new Error(`Image ${fileId} read failed (HTTP ${response.status})`);
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Image download has no body");
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > maxFileBytes + 8192) throw new Error("Downloaded image exceeds the size limit");
      chunks.push(Buffer.from(value));
    }
  } finally { await reader.cancel(); }
  try {
    const [header, iv, ciphertext] = unpack(Buffer.concat(chunks), 3);
    const format = JSON.parse(header);
    if (format.version !== 2 || format.compression !== "pako@1" || format.encryption !== "AES-GCM" || iv.length !== 12) throw new Error();
    const key = await webcrypto.subtle.importKey("jwk", { kty: "oct", k: room.key, alg: "A128GCM", ext: true }, { name: "AES-GCM" }, false, ["decrypt"]);
    const compressed = await webcrypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ciphertext);
    const [metadata, data] = unpack(inflateSync(Buffer.from(compressed), { maxOutputLength: maxFileBytes + 4096 }), 2);
    const file = JSON.parse(metadata);
    const dataURL = data.toString("utf8");
    if (file.id !== fileId || typeof file.mimeType !== "string" || !file.mimeType.startsWith("image/")
        || data.length > maxFileBytes || !dataURL.startsWith(`data:${file.mimeType};base64,`)) throw new Error();
    return { ...file, dataURL };
  } catch { throw new Error(`Image ${fileId} could not be decrypted or has an unsupported file format`); }
}

export async function readSnapshot(room, { ids, excludeIds } = {}) {
  if (ids !== undefined && excludeIds !== undefined) throw new Error("Choose only one of --ids or --exclude-ids");
  const saved = await loadScene(room);
  let elements = saved.elements.filter(element => !element.isDeleted);
  const selection = ids ?? excludeIds;
  if (selection !== undefined) {
    const requested = selection.split(",").map(id => id.trim());
    if (requested.some(id => !id)) throw new Error("Selection IDs must be nonempty comma-separated IDs");
    const live = new Set(elements.map(element => element.id));
    if (requested.some(id => !live.has(id))) throw new Error("Selection includes an unknown or deleted element ID");
    const wanted = new Set(requested);
    elements = elements.filter(element => ids !== undefined ? wanted.has(element.id) : !wanted.has(element.id));
  }
  if (!elements.length) throw new Error("Selection contains no live elements");
  const files = {};
  let totalBytes = 0;
  for (const fileId of new Set(elements.filter(element => element.type === "image").map(element => element.fileId))) {
    const file = await loadFile(room, fileId);
    totalBytes += Buffer.byteLength(file.dataURL);
    // Stop downloading at the hard limit, and warn once about the soft limit afterwards.
    checkSize(snapshotName, totalBytes, Infinity);
    files[fileId] = file;
  }
  checkSize(snapshotName, totalBytes, 48 * 1024 * 1024);
  return { type: "excalidraw", version: 2, revision: saved.revision, elements, files,
    appState: { viewBackgroundColor: "#ffffff", exportEmbedScene: false } };
}

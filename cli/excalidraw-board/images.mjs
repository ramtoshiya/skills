import { createHash, webcrypto } from "node:crypto";
import { open } from "node:fs/promises";
import { deflateSync, inflateSync } from "node:zlib";
import { applyBatch } from "./scene.mjs";
import { loadScene, writeScene } from "./protocol.mjs";

const maxBytes = 4 * 1024 * 1024;
const storage = "https://firebasestorage.googleapis.com/v0/b/excalidraw-room-persistence.appspot.com/o";

function dimensions(bytes) {
  if (bytes.length >= 33 && bytes.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex"))
      && bytes.readUInt32BE(8) === 13 && bytes.toString("ascii", 12, 16) === "IHDR") {
    return { mimeType: "image/png", width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  }
  if (bytes.length >= 4 && bytes.readUInt16BE(0) === 0xffd8) {
    let offset = 2;
    while (offset < bytes.length) {
      if (bytes[offset++] !== 0xff) break;
      while (bytes[offset] === 0xff) offset++;
      const marker = bytes[offset++];
      if (marker === 0xd9 || marker === 0xda || marker === undefined) break;
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
      if (offset + 2 > bytes.length) break;
      const length = bytes.readUInt16BE(offset);
      if (length < 2 || offset + length > bytes.length) break;
      if ([0xc0, 0xc1, 0xc2].includes(marker) && length >= 8) {
        return { mimeType: "image/jpeg", width: bytes.readUInt16BE(offset + 5), height: bytes.readUInt16BE(offset + 3) };
      }
      offset += length;
    }
  }
  throw new Error("Expected a PNG or JPEG with a readable image header");
}

async function readImage(path) {
  let file;
  try {
    file = await open(path, "r");
    const stat = await file.stat();
    if (!stat.isFile() || stat.size > maxBytes) throw new Error("Image must be a regular file no larger than 4 MiB");
    const bytes = Buffer.alloc(Math.min(stat.size + 1, maxBytes + 1));
    let size = 0;
    while (size < bytes.length) {
      const { bytesRead } = await file.read(bytes, size, bytes.length - size, null);
      if (!bytesRead) break;
      size += bytesRead;
    }
    if (size !== stat.size) throw new Error("Image changed while reading");
    const data = bytes.subarray(0, size);
    const info = dimensions(data);
    if (!info.width || !info.height || info.width * info.height > 100000000) throw new Error("Image dimensions exceed 100 million pixels or are empty");
    const dataURL = `data:${info.mimeType};base64,${data.toString("base64")}`;
    if (Buffer.byteLength(dataURL) > maxBytes) throw new Error("Image data URL exceeds the service's 4 MiB limit");
    return { ...info, dataURL, id: createHash("sha1").update(data).digest("hex") };
  } catch (error) {
    if (error.code) throw new Error("Cannot read image file");
    throw error;
  } finally { await file?.close(); }
}

function pack(chunks) {
  const version = Buffer.alloc(4);
  version.writeUInt32BE(1);
  return Buffer.concat([version, ...chunks.flatMap(chunk => {
    const size = Buffer.alloc(4);
    size.writeUInt32BE(chunk.length);
    return [size, chunk];
  })]);
}
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
  }
  if (chunks.length !== count) throw new Error("Invalid image envelope");
  return chunks;
}
const json = value => Buffer.from(JSON.stringify(value));
const keyFor = key => webcrypto.subtle.importKey("jwk", { kty: "oct", k: key, alg: "A128GCM", ext: true }, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);

async function encodeFile(key, file) {
  const iv = webcrypto.getRandomValues(new Uint8Array(12));
  const created = Date.now();
  const metadata = { id: file.id, mimeType: file.mimeType, created, lastRetrieved: created };
  const compressed = deflateSync(pack([json(metadata), Buffer.from(file.dataURL)]));
  const encrypted = Buffer.from(await webcrypto.subtle.encrypt({ name: "AES-GCM", iv }, await keyFor(key), compressed));
  return pack([json({ version: 2, compression: "pako@1", encryption: "AES-GCM" }), iv, encrypted]);
}
async function verifyFile(key, bytes, file) {
  try {
    const [encoding, iv, encrypted] = unpack(bytes, 3);
    const format = JSON.parse(encoding);
    if (format.version !== 2 || format.compression !== "pako@1" || format.encryption !== "AES-GCM" || iv.length !== 12) throw new Error();
    const compressed = await webcrypto.subtle.decrypt({ name: "AES-GCM", iv }, await keyFor(key), encrypted);
    const [metadata, data] = unpack(inflateSync(Buffer.from(compressed), { maxOutputLength: maxBytes + 4096 }), 2);
    const decoded = JSON.parse(metadata);
    if (decoded.id !== file.id || decoded.mimeType !== file.mimeType || data.toString("utf8") !== file.dataURL) throw new Error();
  } catch { throw new Error("Uploaded image verification failed. No image element was saved."); }
}
async function fileBytes(response) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Image download has no body");
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) return Buffer.concat(chunks);
      size += value.length;
      if (size > maxBytes + 8192) throw new Error("Downloaded image exceeds the size limit");
      chunks.push(Buffer.from(value));
    }
  } finally { await reader.cancel(); }
}

export async function uploadImage(room, { file: path, elementId, x = 0, y = 0, width, frame = null }) {
  for (const number of [x, y, width ?? 1]) if (typeof number !== "number" || !Number.isFinite(number)) throw new Error("Image coordinates and width must be finite numbers");
  if (width !== undefined && width <= 0) throw new Error("Image width must be positive");
  const file = await readImage(path);
  const imageWidth = width ?? file.width;
  const element = { id: elementId ?? `image-${file.id}`, type: "image", fileId: file.id, status: "saved", scale: [1, 1], crop: null,
    x, y, width: imageWidth, height: imageWidth * file.height / file.width, frameId: frame };
  const current = await loadScene(room);
  if (frame !== null && !current.elements.some(item => item.id === frame && !item.isDeleted && ["frame", "magicframe"].includes(item.type))) throw new Error("Image frame not found");
  const existing = current.elements.find(item => item.id === element.id);
  if (existing && (existing.isDeleted || existing.type !== "image" || existing.fileId !== file.id)) throw new Error("Element id already belongs to another element");
  const batch = existing ? { update: [element] } : { add: [element] };
  applyBatch(current.elements, batch, { imageFiles: [file.id] });
  const objectName = `files/rooms/${room.id}/${file.id}`;
  const url = `${storage}/${encodeURIComponent(objectName)}?alt=media`;
  let response = await fetch(url, { signal: AbortSignal.timeout(15000) });
  let uploaded = false;
  if (response.status === 404) {
    const encrypted = await encodeFile(room.key, file);
    const boundary = `excalidraw-${webcrypto.randomUUID()}`;
    const metadata = { name: objectName, contentType: "application/octet-stream", cacheControl: "public, max-age=31536000" };
    const body = Buffer.concat([
      Buffer.from(`--${boundary}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n${JSON.stringify(metadata)}\r\n--${boundary}\r\nContent-Type: application/octet-stream\r\n\r\n`),
      encrypted, Buffer.from(`\r\n--${boundary}--\r\n`),
    ]);
    const saved = await fetch(`${storage}?name=${encodeURIComponent(objectName)}`, {
      method: "POST", signal: AbortSignal.timeout(30000),
      headers: { "Content-Type": `multipart/related; boundary=${boundary}`, "X-Goog-Upload-Protocol": "multipart" }, body,
    });
    if (!saved.ok) throw new Error(`Image upload failed (HTTP ${saved.status}). No image element was saved.`);
    uploaded = true;
    response = await fetch(url, { signal: AbortSignal.timeout(15000) });
  }
  if (!response.ok) throw new Error(`Image read failed (HTTP ${response.status}). No image element was saved.`);
  await verifyFile(room.key, await fileBytes(response), file);
  try {
    const receipt = await writeScene(room, batch, { imageFiles: [file.id] });
    return { ...receipt, elementId: element.id, fileId: file.id, fileSaved: true, uploaded };
  } catch (error) {
    throw new Error(`Image file saved, but scene update failed. Read the room before retrying. ${error.message}`);
  }
}

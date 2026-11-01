import { createHash, webcrypto } from "node:crypto";
import { open } from "node:fs/promises";
import { deflateSync, inflateSync } from "node:zlib";
import { applyBatch } from "./scene.mjs";
import { loadScene, writeScene } from "./protocol.mjs";
import { request } from "./request.mjs";
import { checkSize } from "./size-limit.mjs";

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

async function saveFile(room, file, onRetry) {
  const objectName = `files/rooms/${room.id}/${file.id}`;
  const url = `${storage}/${encodeURIComponent(objectName)}?alt=media`;
  let response = await request(url, {}, { onRetry });
  let uploaded = false;
  if (response.status === 404) {
    await response.body?.cancel();
    const encrypted = await encodeFile(room.key, file);
    const boundary = `excalidraw-${webcrypto.randomUUID()}`;
    const metadata = { name: objectName, contentType: "application/octet-stream", cacheControl: "public, max-age=31536000" };
    const body = Buffer.concat([
      Buffer.from(`--${boundary}\r\nContent-Type: application/json; charset=utf-8\r\n\r\n${JSON.stringify(metadata)}\r\n--${boundary}\r\nContent-Type: application/octet-stream\r\n\r\n`),
      encrypted, Buffer.from(`\r\n--${boundary}--\r\n`),
    ]);
    const saved = await request(`${storage}?name=${encodeURIComponent(objectName)}`, {
      method: "POST", timeout: 30000,
      headers: { "Content-Type": `multipart/related; boundary=${boundary}`, "X-Goog-Upload-Protocol": "multipart" }, body,
    }, { onRetry });
    if (!saved.ok) throw new Error(`Image upload failed (HTTP ${saved.status}). No image element was saved.`);
    await saved.body?.cancel();
    uploaded = true;
    response = await request(url, {}, { onRetry });
  }
  if (!response.ok) throw new Error(`Image read failed (HTTP ${response.status}). No image element was saved.`);
  await verifyFile(room.key, await fileBytes(response), file);
  return { fileId: file.id, fileSaved: true, uploaded };
}

export async function uploadImages(room, images, { concurrency = 4 } = {}) {
  const started = performance.now();
  let retries = 0;
  const onRetry = () => { retries++; };
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 8) throw new Error("Concurrency must be an integer from 1 to 8");
  if (!Array.isArray(images) || images.length < 1 || images.length > 128) throw new Error("Expected 1 to 128 images");
  const files = new Map(), elements = [], ids = new Set();
  let bytes = 0;
  for (const image of images) {
    if (!image || typeof image !== "object" || Array.isArray(image)
        || Object.keys(image).some(key => !["file", "elementId", "x", "y", "width", "frame"].includes(key))) throw new Error("Invalid image entry");
    const { file: path, elementId, x = 0, y = 0, width, frame = null } = image;
    if (elementId !== undefined && (typeof elementId !== "string" || !elementId || /[\x00-\x1f]/.test(elementId))) throw new Error("Image elementId must be a nonempty string without control characters");
    if (frame !== null && (typeof frame !== "string" || !frame)) throw new Error("Image frame must be a nonempty string or null");
    if (typeof path !== "string" || !path) throw new Error("Image needs a file path");
    for (const number of [x, y, width ?? 1]) if (typeof number !== "number" || !Number.isFinite(number)) throw new Error("Image coordinates and width must be finite numbers");
    if (width !== undefined && width <= 0) throw new Error("Image width must be positive");
    const file = await readImage(path);
    if (!files.has(file.id)) {
      bytes += Buffer.byteLength(file.dataURL);
      files.set(file.id, file);
    }
    const imageWidth = width ?? file.width;
    const element = { id: elementId ?? `image-${file.id}`, type: "image", fileId: file.id, status: "saved", scale: [1, 1], crop: null,
      x, y, width: imageWidth, height: imageWidth * file.height / file.width, frameId: frame };
    if (ids.has(element.id)) throw new Error("Repeated image element id. Use a unique elementId for each placement.");
    ids.add(element.id);
    elements.push(element);
  }
  checkSize("excalidraw-board batch image data URLs", bytes, 128 * 1024 * 1024);
  const current = await loadScene(room, { onRetry });
  const batch = { add: [], update: [] };
  for (const element of elements) {
    if (element.frameId !== null && !current.elements.some(item => item.id === element.frameId && !item.isDeleted && ["frame", "magicframe"].includes(item.type))) throw new Error("Image frame not found");
    const existing = current.elements.find(item => item.id === element.id);
    if (existing && (existing.isDeleted || existing.type !== "image" || existing.fileId !== element.fileId)) throw new Error("Element id already belongs to another element");
    batch[existing ? "update" : "add"].push(element);
  }
  const imageFiles = [...files.keys()];
  applyBatch(current.elements, batch, { imageFiles });
  const prepared = performance.now();
  const pending = files.values(), verified = new Map();
  let failure;
  // Stop taking new work after a failure, then settle active uploads before returning.
  await Promise.all(Array.from({ length: Math.min(concurrency, files.size) }, async () => {
    while (!failure) {
      const next = pending.next();
      if (next.done) return;
      try { verified.set(next.value.id, await saveFile(room, next.value, onRetry)); }
      catch (error) { failure ??= error; }
    }
  }));
  const transferred = performance.now();
  const progress = () => ({ images: elements.filter(element => verified.has(element.fileId))
    .map(element => ({ elementId: element.id, ...verified.get(element.fileId) })),
    files: { unique: files.size, verified: verified.size, uploaded: [...verified.values()].filter(file => file.uploaded).length },
    concurrency, retries,
    timings: { prepareMs: prepared - started, fileTransferMs: transferred - prepared,
      sceneWriteMs: performance.now() - transferred, totalMs: performance.now() - started } });
  if (failure) {
    const error = new Error(`Image batch failed after ${verified.size}/${files.size} files verified. No image elements were saved. Retry the same manifest. ${failure.message}`);
    error.receipt = { ...progress(), saved: false, notified: false };
    throw error;
  }
  try {
    const receipt = await writeScene(room, batch, { imageFiles, onRetry });
    return { ...receipt, ...progress() };
  } catch (error) {
    // The scene writer reports ambiguous or verified saves. Do not turn them into saved:false.
    throw new Error(`Image files saved, but scene update failed. Read the room before retrying. ${error.message}`);
  }
}

export async function uploadImage(room, image) {
  const receipt = await uploadImages(room, [image], { concurrency: 1 });
  return { ...receipt, ...receipt.images[0] };
}

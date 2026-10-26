import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { deflateSync } from "node:zlib";
import { test } from "node:test";
import { encrypt } from "../cli/excalidraw-board/protocol.mjs";
import { readSnapshot } from "../cli/excalidraw-board/snapshot.mjs";

const room = { id: "snapshot-test", key: "AAAAAAAAAAAAAAAAAAAAAA" };
const dataURL = "data:image/png;base64,iVBORw0KGgo=";
const metadata = { id: "file-a", mimeType: "image/png", created: 1 };
const pack = chunks => {
  const parts = [Buffer.from([0, 0, 0, 1])];
  for (const chunk of chunks) {
    const size = Buffer.alloc(4);
    size.writeUInt32BE(chunk.length);
    parts.push(size, chunk);
  }
  return Buffer.concat(parts);
};
async function encryptedFile() {
  const key = await webcrypto.subtle.importKey("raw", new Uint8Array(16), "AES-GCM", false, ["encrypt"]);
  const iv = new Uint8Array(12);
  const body = deflateSync(pack([Buffer.from(JSON.stringify(metadata)), Buffer.from(dataURL)]));
  const ciphertext = Buffer.from(await webcrypto.subtle.encrypt({ name: "AES-GCM", iv }, key, body));
  return pack([Buffer.from(JSON.stringify({ version: 2, compression: "pako@1", encryption: "AES-GCM" })), Buffer.from(iv), ciphertext]);
}
async function serve(t, fileResponse) {
  const elements = [
    { id: "image-a", type: "image", fileId: "file-a" },
    { id: "image-b", type: "image", fileId: "file-a" },
    { id: "unselected", type: "image", fileId: "must-not-fetch" },
  ];
  const { iv, ciphertext } = await encrypt(room.key, elements);
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    assert.equal(options.method ?? "GET", "GET");
    const target = new URL(url);
    requests.push(target);
    if (target.hostname === "firestore.googleapis.com") return Response.json({
      updateTime: "2026-01-01T00:00:00.000001Z",
      fields: { iv: { bytesValue: Buffer.from(iv).toString("base64") }, ciphertext: { bytesValue: Buffer.from(ciphertext).toString("base64") } },
    });
    assert.equal(decodeURIComponent(target.pathname.split("/o/")[1]), "files/rooms/snapshot-test/file-a");
    return fileResponse();
  });
  return requests;
}

test("snapshot decrypts selected image files once without fetching omitted files", async t => {
  const bytes = await encryptedFile();
  const requests = await serve(t, () => new Response(bytes));
  const snapshot = await readSnapshot(room, { ids: "image-b,image-a" });
  assert.equal(snapshot.revision, "1767225600000001");
  assert.deepEqual(snapshot.elements.map(element => element.id), ["image-a", "image-b"]);
  assert.deepEqual(snapshot.files, { "file-a": { ...metadata, dataURL } });
  assert.equal(requests.length, 2);
});

test("snapshot refuses missing or corrupted image payloads instead of returning placeholders", async t => {
  const bytes = await encryptedFile();
  const corrupt = Buffer.from(bytes);
  corrupt[corrupt.length - 1] ^= 1;
  for (const [name, response, expected] of [
    ["missing", () => new Response(null, { status: 404 }), /HTTP 404/],
    ["authentication failure", () => new Response(corrupt), /could not be decrypted/],
    ["truncated envelope", () => new Response(bytes.subarray(0, 10)), /could not be decrypted/],
  ]) {
    await t.test(name, async t => {
      await serve(t, response);
      await assert.rejects(readSnapshot(room, { ids: "image-a" }), expected);
    });
  }
});

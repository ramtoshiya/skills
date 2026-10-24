import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash, webcrypto } from "node:crypto";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { inflateSync } from "node:zlib";
import { decrypt, encrypt, writeScene } from "../cli/excalidraw-board/protocol.mjs";
import { uploadImage, uploadImages } from "../cli/excalidraw-board/images.mjs";

const room = { id: "offline-protocol", key: "AAAAAAAAAAAAAAAAAAAAAA" };
const before = "2026-01-01T00:00:00.000001Z";
const after = "2026-01-01T00:00:00.000002Z";
const later = "2026-01-01T00:00:00.000003Z";
const original = [{ id: "a", type: "rectangle", index: "a0", version: 1, versionNonce: 20, x: 1, y: 2, customData: { left: 1, right: 2 } }];
const batch = { update: [{ id: "a", x: 30, customData: { left: 3, right: 4 } }] };

async function document(elements, updateTime = before) {
  const { ciphertext, iv } = await encrypt(room.key, elements);
  return { updateTime, fields: {
    ciphertext: { bytesValue: Buffer.from(ciphertext).toString("base64") },
    iv: { bytesValue: Buffer.from(iv).toString("base64") },
  } };
}

async function elementsIn(request) {
  const { ciphertext, iv } = request.body.fields;
  return decrypt(room.key, Buffer.from(ciphertext.bytesValue, "base64"), Buffer.from(iv.bytesValue, "base64"));
}

// Script HTTP replies and the relay handshake, without applying or reconciling edits.
function transport(t, steps) {
  const requests = [];
  const sent = [];
  const sockets = [];
  const previousWebSocket = Object.getOwnPropertyDescriptor(globalThis, "WebSocket");
  class Relay extends EventTarget {
    static OPEN = 1;
    readyState = 1;
    bufferedAmount = 0;
    constructor() {
      super();
      sockets.push(this);
      queueMicrotask(() => this.reply('0{"maxPayload":1000000}'));
    }
    reply(data) { this.dispatchEvent(new MessageEvent("message", { data })); }
    send(data) {
      sent.push(data);
      if (data === "40") this.reply('42["init-room"]');
      if (typeof data === "string" && data.startsWith('42["join-room",')) this.reply('42["first-in-room"]');
    }
    close() { this.readyState = 3; }
  }
  Object.defineProperty(globalThis, "WebSocket", { configurable: true, writable: true, value: Relay });
  t.mock.method(globalThis, "fetch", async (url, options = {}) => {
    const request = { url: new URL(url), method: options.method || "GET", headers: options.headers,
      body: Buffer.isBuffer(options.body) ? options.body : options.body && JSON.parse(options.body) };
    requests.push(request);
    if (typeof steps === "function") return steps(request, requests);
    const step = steps.shift();
    assert.ok(step, `Unexpected ${request.method}`);
    assert.equal(request.method, step[0]);
    return typeof step[1] === "function" ? step[1](request, requests) : Response.json(step[1]);
  });
  t.after(() => {
    if (previousWebSocket) Object.defineProperty(globalThis, "WebSocket", previousWebSocket);
    else delete globalThis.WebSocket;
    if (Array.isArray(steps)) assert.equal(steps.length, 0, "All scripted responses must be consumed");
    assert.ok(sockets.every(socket => socket.readyState === 3), "Sockets must close on success and failure");
  });
  return {
    requests, sockets,
    broadcasts: () => sent.filter(packet => typeof packet === "string" && packet.startsWith("452-")),
    async broadcastElements() {
      const index = sent.findIndex(packet => typeof packet === "string" && packet.startsWith("452-"));
      assert.notEqual(index, -1, "Expected a binary scene broadcast");
      const message = await decrypt(room.key, sent[index + 1], sent[index + 2]);
      assert.equal(message.type, "SCENE_UPDATE");
      return message.payload.elements;
    },
  };
}

test("writeScene rejects superseded or altered saved elements before broadcasting", async t => {
  const mutations = [
    ["same version, different nonce", element => { element.versionNonce += 1; }],
    ["same version and nonce, changed authored field", element => { element.customData.left = 99; }],
    ["higher version", element => { element.version += 1; }],
    ["missing element", (_, elements) => { elements.length = 0; }],
  ];
  for (const [name, mutate] of mutations) {
    await t.test(name, async t => {
      const initial = await document(original);
      let authored;
      const fixture = transport(t, [
        ["GET", initial], ["GET", initial],
        ["PATCH", async request => {
          authored = await elementsIn(request);
          return Response.json({ updateTime: after });
        }],
        ["GET", async () => {
          const elements = structuredClone(authored);
          mutate(elements[0], elements);
          return Response.json(await document(elements, later));
        }],
      ]);
      await assert.rejects(writeScene(room, batch), /^Error: Save succeeded at revision 1767225600000002, but verification failed\. Read before retrying\.$/);
      assert.equal(fixture.broadcasts().length, 0);
      assert.equal(fixture.requests.filter(request => request.method === "PATCH").length, 1);
    });
  }
});

test("writeScene retries CAS against fresh fields and verifies structural content before notifying", async t => {
  const initial = await document(original);
  const concurrent = await document([{ ...original[0], y: 90, version: 2, versionNonce: 10, future: { retained: true } }], after);
  let authored;
  const fixture = transport(t, [
    ["GET", initial], ["GET", initial],
    ["PATCH", () => Response.json({ error: { status: "FAILED_PRECONDITION" } }, { status: 400 })],
    ["GET", concurrent],
    ["PATCH", async request => {
      authored = await elementsIn(request);
      return Response.json({ updateTime: later });
    }],
    ["GET", async () => {
      // JSON object order is not content. An unrelated addition can advance the scene revision.
      const reordered = Object.fromEntries(Object.entries(authored[0]).reverse());
      reordered.customData = { right: 4, left: 3 };
      return Response.json(await document([reordered, { id: "unrelated", type: "ellipse", version: 1 }], "2026-01-01T00:00:00.000004Z"));
    }],
  ]);
  const receipt = await writeScene(room, batch);
  assert.deepEqual(receipt, { updateTime: later, revision: "1767225600000003", changed: ["a"], attempts: 2, saved: true, notified: true });
  const patches = fixture.requests.filter(request => request.method === "PATCH");
  assert.equal(patches.length, 2);
  assert.equal(patches[0].url.searchParams.get("currentDocument.updateTime"), before);
  assert.equal(patches[1].url.searchParams.get("currentDocument.updateTime"), after);
  assert.equal(patches[1].url.searchParams.has("currentDocument.exists"), false);
  assert.equal((await elementsIn(patches[0]))[0].y, 2);
  assert.equal(authored[0].x, 30);
  assert.equal(authored[0].y, 90);
  assert.equal(authored[0].version, 3);
  assert.deepEqual(authored[0].future, { retained: true });
  assert.deepEqual(authored[0].customData, { left: 3, right: 4 });
  assert.deepEqual(await fixture.broadcastElements(), authored);
  assert.equal(fixture.broadcasts().length, 1);
});

test("writeScene verifies and broadcasts negative zero after JSON normalization", async t => {
  const initial = await document(original);
  let authored;
  const fixture = transport(t, [
    ["GET", initial], ["GET", initial],
    ["PATCH", async request => {
      authored = await elementsIn(request);
      return Response.json({ updateTime: after });
    }],
    ["GET", async () => Response.json(await document(authored, after))],
  ]);
  const receipt = await writeScene(room, { update: [{ id: "a", x: -0, customData: { offset: -0 } }] });
  assert.deepEqual(receipt, { updateTime: after, revision: "1767225600000002", changed: ["a"], attempts: 1, saved: true, notified: true });
  assert.equal(authored[0].x, 0);
  assert.deepEqual(authored[0].customData, { offset: 0 });
  assert.deepEqual(await fixture.broadcastElements(), authored);
  assert.equal(fixture.broadcasts().length, 1);
});

test("writeScene no-op does not PATCH or broadcast", async t => {
  const initial = await document(original);
  const fixture = transport(t, [["GET", initial], ["GET", initial]]);
  const receipt = await writeScene(room, { update: [{ id: "a", x: 1 }] });
  assert.deepEqual(receipt, { revision: "1767225600000001", changed: [], saved: true, notified: false });
  assert.deepEqual(fixture.requests.map(request => request.method), ["GET", "GET"]);
  assert.equal(fixture.broadcasts().length, 0);
});

const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64");
function imageFixture(t, bytes = png) {
  const directory = mkdtempSync(join(tmpdir(), "excalidraw-image-"));
  const file = join(directory, "image.png");
  writeFileSync(file, bytes);
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return file;
}
function chunks(bytes) {
  // Decode the upstream length-prefixed wire format independently of the uploader.
  assert.equal(bytes.readUInt32BE(0), 1);
  const values = [];
  for (let offset = 4; offset < bytes.length;) {
    const length = bytes.readUInt32BE(offset);
    offset += 4;
    assert.ok(offset + length <= bytes.length);
    values.push(bytes.subarray(offset, offset += length));
  }
  return values;
}
function uploadedBytes(request) {
  assert.equal(request.headers["X-Goog-Upload-Protocol"], "multipart");
  const boundary = request.headers["Content-Type"].split("boundary=")[1];
  const first = request.body.indexOf("\r\n\r\n") + 4;
  const second = request.body.indexOf(`\r\n--${boundary}`, first);
  assert.deepEqual(JSON.parse(request.body.subarray(first, second)), {
    name: `files/rooms/${room.id}/${request.url.searchParams.get("name").split("/").at(-1)}`,
    contentType: "application/octet-stream", cacheControl: "public, max-age=31536000",
  });
  const data = request.body.indexOf("\r\n\r\n", second) + 4;
  return request.body.subarray(data, request.body.length - Buffer.byteLength(`\r\n--${boundary}--\r\n`));
}

test("image upload uses the browser's encrypted file format before persisting an image and reuses it on retry", async t => {
  const file = imageFixture(t);
  const initial = await document([]);
  let encrypted, authored, savedDocument;
  const fixture = transport(t, [
    ["GET", initial],
    ["GET", () => new Response(null, { status: 404 })],
    ["POST", async request => {
      encrypted = uploadedBytes(request);
      assert.equal(request.url.origin, "https://firebasestorage.googleapis.com");
      assert.match(request.url.searchParams.get("name"), /^files\/rooms\/offline-protocol\/[a-f0-9]{40}$/);
      const [format, iv, ciphertext] = chunks(encrypted);
      assert.deepEqual(JSON.parse(format), { version: 2, compression: "pako@1", encryption: "AES-GCM" });
      const key = await webcrypto.subtle.importKey("raw", Buffer.alloc(16), { name: "AES-GCM" }, false, ["decrypt"]);
      const compressed = await webcrypto.subtle.decrypt({ name: "AES-GCM", iv }, key, ciphertext);
      const [metadata, data] = chunks(inflateSync(Buffer.from(compressed)));
      assert.equal(data.toString(), `data:image/png;base64,${png.toString("base64")}`);
      assert.equal(JSON.parse(metadata).mimeType, "image/png");
      assert.equal(JSON.parse(metadata).id, request.url.searchParams.get("name").split("/").at(-1));
      assert.equal(encrypted.includes(png), false);
      return Response.json({});
    }],
    ["GET", request => {
      assert.equal(request.url.searchParams.get("alt"), "media");
      return new Response(encrypted);
    }],
    ["GET", initial], ["GET", initial],
    ["PATCH", async request => {
      authored = await elementsIn(request);
      savedDocument = await document(authored, after);
      return Response.json({ updateTime: after });
    }],
    ["GET", () => Response.json(savedDocument)],
    ["GET", () => Response.json(savedDocument)],
    ["GET", () => new Response(encrypted)],
    ["GET", () => Response.json(savedDocument)], ["GET", () => Response.json(savedDocument)],
  ]);
  const first = await uploadImage(room, { file, elementId: "capture", x: 20, y: 30, width: 400 });
  assert.equal(first.saved, true);
  assert.equal(first.notified, true);
  assert.equal(first.uploaded, true);
  assert.deepEqual(first.changed, ["capture"]);
  assert.equal(authored[0].fileId, first.fileId);
  assert.equal(authored[0].status, "saved");
  assert.equal(authored[0].width, 400);
  assert.equal(authored[0].height, 400);
  assert.deepEqual(authored[0].scale, [1, 1]);
  assert.deepEqual(await fixture.broadcastElements(), authored);
  const retry = await uploadImage(room, { file, elementId: "capture", x: 20, y: 30, width: 400 });
  assert.equal(retry.uploaded, false);
  assert.deepEqual(retry.changed, []);
  assert.equal(fixture.requests.filter(request => request.method === "POST").length, 1);
  assert.equal(fixture.requests.filter(request => request.method === "PATCH").length, 1);
});

test("transient file upload failures retry identical encrypted bytes and publish once", async t => {
  const file = imageFixture(t);
  const initial = await document([]);
  let encrypted, firstBody, authored;
  const fixture = transport(t, [
    ["GET", initial], ["GET", () => new Response(null, { status: 404 })],
    ["POST", request => { firstBody = request.body; return new Response(null, { status: 503 }); }],
    ["POST", request => {
      assert.deepEqual(request.body, firstBody);
      encrypted = uploadedBytes(request);
      return Response.json({});
    }],
    ["GET", () => new Response(encrypted)], ["GET", initial], ["GET", initial],
    ["PATCH", async request => { authored = await elementsIn(request); return Response.json({ updateTime: after }); }],
    ["GET", async () => Response.json(await document(authored, after))],
  ]);
  const receipt = await uploadImage(room, { file, elementId: "capture" });
  assert.equal(receipt.retries, 1);
  assert.equal(receipt.fileSaved, true);
  assert.equal(fixture.requests.filter(request => request.method === "PATCH").length, 1);
  assert.equal(fixture.broadcasts().length, 1);
});

test("image batches bound parallel file work, deduplicate bytes and publish once after all readbacks", { timeout: 5000 }, async t => {
  const paths = [0, 1, 2].map(value => imageFixture(t, Buffer.concat([png, Buffer.from([value])])));
  const images = [...paths, paths[0]].map((file, index) => ({ file, elementId: `capture-${index}`, x: index * 20 }));
  const gate = Promise.withResolvers();
  t.after(() => gate.resolve());
  let active = 0, peak = 0, readbacks = 0, sceneReads = 0, authored;
  let scene = await document([]);
  const files = new Map();
  const fixture = transport(t, async request => {
    if (request.url.hostname === "firestore.googleapis.com") {
      if (request.method === "GET") { sceneReads++; return Response.json(scene); }
      assert.equal(request.method, "PATCH");
      assert.equal(readbacks, 3, "Publish only after every unique file has been downloaded");
      authored = await elementsIn(request);
      scene = await document(authored, after);
      return Response.json({ updateTime: after });
    }
    if (request.method === "POST") {
      files.set(request.url.searchParams.get("name").split("/").at(-1), uploadedBytes(request));
      return Response.json({});
    }
    const id = decodeURIComponent(request.url.pathname).split("/").at(-1);
    if (files.has(id)) { readbacks++; return new Response(files.get(id)); }
    active++;
    peak = Math.max(peak, active);
    if (active === 2) gate.resolve();
    await gate.promise;
    active--;
    return new Response(null, { status: 404 });
  });
  const receipt = await uploadImages(room, images, { concurrency: 2 });
  assert.equal(peak, 2, "Two concurrent file operations, never three");
  assert.deepEqual(receipt.files, { unique: 3, verified: 3, uploaded: 3 });
  assert.equal(receipt.images.length, 4);
  assert.equal(receipt.images[0].fileId, receipt.images[3].fileId);
  assert.deepEqual(authored.map(element => element.id), images.map(image => image.elementId));
  assert.equal(sceneReads, 4);
  assert.equal(fixture.requests.filter(request => request.method === "POST").length, 3);
  assert.equal(fixture.requests.filter(request => request.method === "PATCH").length, 1);
  assert.equal(fixture.sockets.length, 1);
  assert.equal(fixture.broadcasts().length, 1);
  assert.deepEqual(await fixture.broadcastElements(), authored);
  for (const value of Object.values(receipt.timings)) assert.ok(Number.isFinite(value) && value >= 0);
});

test("failed image batches settle active uploads, stop scheduling and never publish partial scenes", { timeout: 5000 }, async t => {
  const bytes = [0, 1, 2].map(value => Buffer.concat([png, Buffer.from([value])]));
  const images = bytes.map((data, index) => ({ file: imageFixture(t, data), elementId: `capture-${index}` }));
  const hashes = bytes.map(data => createHash("sha1").update(data).digest("hex"));
  const started = Promise.withResolvers(), finish = Promise.withResolvers();
  t.after(() => finish.resolve());
  const initial = await document([]);
  let encrypted;
  const fixture = transport(t, async request => {
    if (request.url.hostname === "firestore.googleapis.com") return Response.json(initial);
    if (request.method === "POST") { encrypted = uploadedBytes(request); return Response.json({}); }
    const id = decodeURIComponent(request.url.pathname).split("/").at(-1);
    assert.notEqual(id, hashes[2], "Do not schedule another file after failure");
    if (id === hashes[0]) return new Response(null, { status: 403 });
    if (encrypted) return new Response(encrypted);
    started.resolve();
    await finish.promise;
    return new Response(null, { status: 404 });
  });
  let settled = false;
  const work = uploadImages(room, images, { concurrency: 2 });
  work.then(() => { settled = true; }, () => { settled = true; });
  await started.promise;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(settled, false, "Wait for active work before returning failure");
  finish.resolve();
  await assert.rejects(work, error => {
    assert.match(error.message, /No image elements were saved/);
    assert.equal(error.receipt.saved, false);
    assert.equal(error.receipt.files.verified, 1);
    assert.equal(error.receipt.images[0].elementId, "capture-1");
    return true;
  });
  assert.equal(fixture.requests.some(request => request.method === "PATCH"), false);
  assert.equal(fixture.sockets.length, 0);
});

test("image retry rejects a concurrent replacement before overwriting its file identity", async t => {
  const file = imageFixture(t);
  const image = { id: "capture", type: "image", fileId: createHash("sha1").update(png).digest("hex"),
    status: "saved", index: "a0", version: 1, versionNonce: 20 };
  const initial = await document([image]);
  const replacement = await document([{ ...image, fileId: "b".repeat(40), version: 2 }], after);
  let encrypted;
  const fixture = transport(t, [
    ["GET", initial], ["GET", () => new Response(null, { status: 404 })],
    ["POST", request => { encrypted = uploadedBytes(request); return Response.json({}); }],
    ["GET", () => new Response(encrypted)],
    ["GET", replacement], ["GET", replacement],
  ]);
  await assert.rejects(uploadImage(room, { file, elementId: "capture" }), /Image element changed during upload/);
  assert.equal(fixture.requests.some(request => request.method === "PATCH"), false);
  assert.equal(fixture.broadcasts().length, 0);
});

test("image failures never persist or broadcast an image element", async t => {
  for (const failure of ["missing room", "upload denied", "corrupt file", "invalid frame", "occupied id"]) {
    await t.test(failure, async t => {
      const file = imageFixture(t);
      const initial = await document(failure === "occupied id" ? original : []);
      const steps = failure === "missing room" ? [["GET", () => new Response(null, { status: 404 })]] : [["GET", initial]];
      if (failure === "upload denied") steps.push(["GET", () => new Response(null, { status: 404 })], ["POST", () => new Response(null, { status: 403 })]);
      if (failure === "corrupt file") steps.push(["GET", () => new Response(Buffer.alloc(32))]);
      const fixture = transport(t, steps);
      const error = { "missing room": /room is gone/, "upload denied": /Image upload failed/, "corrupt file": /verification failed/, "invalid frame": /frame not found/, "occupied id": /already belongs/ }[failure];
      await assert.rejects(uploadImage(room, { file, elementId: failure === "occupied id" ? "a" : "capture", frame: failure === "invalid frame" ? "missing" : null }), error);
      assert.equal(fixture.requests.some(request => request.method === "PATCH"), false);
      assert.equal(fixture.sockets.length, 0);
    });
  }
});

test("image validation rejects unsupported, oversized and unbounded inputs before network access", async t => {
  const fixture = transport(t, []);
  for (const [bytes, options, error] of [
    [Buffer.from("not an image"), {}, /PNG or JPEG/],
    [Buffer.alloc(4 * 1024 * 1024 + 1), {}, /4 MiB/],
    [Buffer.concat([png, Buffer.alloc(3200000)]), {}, /data URL/],
    [png, { x: NaN }, /finite/], [png, { width: 0 }, /positive/],
  ]) {
    const file = imageFixture(t, bytes);
    await assert.rejects(uploadImage(room, { file, ...options }), error);
  }
  const file = imageFixture(t);
  for (const [images, options, error] of [
    [[], {}, /1 to 128/], [Array(129).fill({ file }), {}, /1 to 128/],
    [[{ file }], { concurrency: 0 }, /Concurrency/], [[{ file }], { concurrency: 9 }, /Concurrency/],
    [[{ file }], { concurrency: 1.5 }, /Concurrency/],
    [[{ file, unknown: true }], {}, /Invalid image entry/],
    [[{ file, elementId: "" }], {}, /elementId/], [[{ file, elementId: null }], {}, /elementId/],
    [[{ file, elementId: false }], {}, /elementId/], [[{ file, frame: 12 }], {}, /frame/],
    [[{ file }, { file }], {}, /Repeated image element id/],
    [[{ file }, { file: imageFixture(t, Buffer.from("invalid")) }], {}, /PNG or JPEG/],
  ]) await assert.rejects(uploadImages(room, images, options), error);
  assert.equal(fixture.requests.length, 0);
});

test("ordinary scene writes cannot create an image without uploading its file", async t => {
  const initial = await document([]);
  const fixture = transport(t, [["GET", initial], ["GET", initial]]);
  await assert.rejects(writeScene(room, { add: [{ id: "image", type: "image", fileId: "missing", status: "saved" }] }), /image command/);
  assert.equal(fixture.broadcasts().length, 0);
});

test("scene save errors are not blindly retried by HTTP backoff", async t => {
  const initial = await document(original);
  const fixture = transport(t, [["GET", initial], ["GET", initial],
    ["PATCH", () => Response.json({ error: { status: "UNAVAILABLE" } }, { status: 503 })]]);
  await assert.rejects(writeScene(room, batch), /Room save failed/);
  assert.equal(fixture.requests.filter(request => request.method === "PATCH").length, 1);
  assert.equal(fixture.broadcasts().length, 0);
});

test("writeScene missing room does not create persistence or open a relay", async t => {
  const fixture = transport(t, [["GET", () => Response.json({}, { status: 404 })]]);
  await assert.rejects(writeScene(room, { add: [{ id: "new", type: "rectangle" }] }), /^Error: room is gone$/);
  assert.deepEqual(fixture.requests.map(request => request.method), ["GET"]);
  assert.equal(fixture.sockets.length, 0);
  assert.equal(fixture.broadcasts().length, 0);
});
import assert from "node:assert/strict";
import { test } from "node:test";
import { decrypt, encrypt, writeScene } from "../cli/excalidraw-board/protocol.mjs";

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
    const request = { url: new URL(url), method: options.method || "GET", body: options.body && JSON.parse(options.body) };
    requests.push(request);
    const step = steps.shift();
    assert.ok(step, `Unexpected ${request.method}`);
    assert.equal(request.method, step[0]);
    return typeof step[1] === "function" ? step[1](request, requests) : Response.json(step[1]);
  });
  t.after(() => {
    if (previousWebSocket) Object.defineProperty(globalThis, "WebSocket", previousWebSocket);
    else delete globalThis.WebSocket;
    assert.equal(steps.length, 0, "All scripted responses must be consumed");
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

test("writeScene missing room does not create persistence or open a relay", async t => {
  const fixture = transport(t, [["GET", () => Response.json({}, { status: 404 })]]);
  await assert.rejects(writeScene(room, { add: [{ id: "new", type: "rectangle" }] }), /^Error: room is gone$/);
  assert.deepEqual(fixture.requests.map(request => request.method), ["GET"]);
  assert.equal(fixture.sockets.length, 0);
  assert.equal(fixture.broadcasts().length, 0);
});
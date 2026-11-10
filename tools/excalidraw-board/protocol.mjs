import { webcrypto } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { reconcile, applyBatch, revision } from "./scene.mjs";
import { request } from "./request.mjs";

const sceneEndpoint = "https://firestore.googleapis.com/v1/projects/excalidraw-room-persistence/databases/(default)/documents/scenes/";
const relayEndpoint = "wss://oss-collab.excalidraw.com/socket.io/?EIO=4&transport=websocket";
const origin = "https://excalidraw.com";
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function aesKey(key) {
  return webcrypto.subtle.importKey("jwk", { kty: "oct", k: key, alg: "A128GCM", ext: true }, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}
export async function encrypt(key, value) {
  const iv = webcrypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(await webcrypto.subtle.encrypt({ name: "AES-GCM", iv }, await aesKey(key), new TextEncoder().encode(JSON.stringify(value))));
  return { iv, ciphertext };
}
export async function decrypt(key, ciphertext, iv) {
  try {
    const plaintext = await webcrypto.subtle.decrypt({ name: "AES-GCM", iv }, await aesKey(key), ciphertext);
    return JSON.parse(new TextDecoder().decode(plaintext));
  } catch { throw new Error("Cannot decrypt room data. Check the room key or saved scene format."); }
}

export async function loadScene(room, { missing = false, onRetry } = {}) {
  const response = await request(sceneEndpoint + encodeURIComponent(room.id), {}, { onRetry });
  if (response.status === 404) {
    if (missing) return null;
    throw new Error("room is gone");
  }
  if (!response.ok) throw new Error(`Room read failed (HTTP ${response.status})`);
  const document = await response.json();
  const elements = await decrypt(room.key, Buffer.from(document.fields.ciphertext.bytesValue, "base64"), Buffer.from(document.fields.iv.bytesValue, "base64"));
  if (!Array.isArray(elements)) throw new Error("Unexpected saved scene format");
  return { elements, updateTime: document.updateTime, revision: revision(document.updateTime) };
}

async function saveScene(room, elements, updateTime) {
  const encrypted = await encrypt(room.key, elements);
  const url = new URL(sceneEndpoint + encodeURIComponent(room.id));
  url.searchParams.set(updateTime ? "currentDocument.updateTime" : "currentDocument.exists", updateTime || "false");
  for (const field of ["sceneVersion", "ciphertext", "iv"]) url.searchParams.append("updateMask.fieldPaths", field);
  const response = await fetch(url, {
    method: "PATCH", signal: AbortSignal.timeout(15000), headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fields: {
      sceneVersion: { integerValue: String(elements.reduce((sum, element) => sum + element.version, 0)) },
      ciphertext: { bytesValue: Buffer.from(encrypted.ciphertext).toString("base64") },
      iv: { bytesValue: Buffer.from(encrypted.iv).toString("base64") },
    } }),
  });
  const document = await response.json();
  if (!response.ok) {
    if (document.error?.status === "FAILED_PRECONDITION" || document.error?.status === "ALREADY_EXISTS") return null;
    throw new Error(`Room save failed (HTTP ${response.status}, ${document.error?.status || "unknown"})`);
  }
  return { updateTime: document.updateTime, revision: revision(document.updateTime) };
}

export async function createScene(room) {
  const result = await saveScene(room, [], null);
  if (!result) throw new Error("Room already exists");
  const verified = await loadScene(room);
  if (verified.updateTime !== result.updateTime || verified.elements.length !== 0) throw new Error("New room verification failed");
  return verified;
}

// Socket.IO binary events over Engine.IO 4. Node's WebSocketInit supplies Origin.
export class RoomSocket {
  constructor(room) {
    this.room = room;
    this.elements = [];
    this.incoming = Promise.resolve();
    this.initialized = false;
    this.joined = false;
    this.alone = false;
    this.pending = null;
    this.events = [];
  }

  async waitFor(predicate) {
    const until = Date.now() + 12000;
    while (!predicate()) {
      if (this.error) throw this.error;
      if (Date.now() > until) throw new Error("Collaboration relay handshake timed out");
      await sleep(25);
    }
  }
  async open() {
    this.ws = new WebSocket(relayEndpoint, { headers: { Origin: origin } });
    this.ws.binaryType = "arraybuffer";
    this.ws.addEventListener("error", () => { this.error = new Error("Collaboration WebSocket failed. Use a Node release with WebSocketInit headers support."); });
    this.ws.addEventListener("close", () => { if (!this.closing) this.error = new Error("Collaboration relay closed the session"); });
    this.ws.addEventListener("message", ({ data }) => {
      this.incoming = this.incoming.then(() => this.packet(data)).catch(error => { this.error = error; });
    });
    await this.waitFor(() => this.initialized);
    this.ws.send(`42${JSON.stringify(["join-room", this.room.id])}`);
    await this.waitFor(() => this.joined);
    if (!this.alone) await sleep(1000);
    return this;
  }
  async packet(packet) {
    if (typeof packet !== "string") {
      if (!this.pending) throw new Error("Unexpected binary attachment");
      this.pending.buffers.push(new Uint8Array(packet));
      if (this.pending.buffers.length === this.pending.count) {
        const pending = this.pending;
        this.pending = null;
        await this.event(pending.event.map(value => value?._placeholder ? pending.buffers[value.num] : value));
      }
    } else if (packet.startsWith("0")) {
      this.maxPayload = JSON.parse(packet.slice(1)).maxPayload || 1000000;
      this.ws.send("40");
    } else if (packet === "2") this.ws.send("3");
    else if (packet === "1") throw new Error("Collaboration relay closed the session");
    else if (packet.startsWith("42")) await this.event(JSON.parse(packet.slice(2)));
    else if (packet.startsWith("45")) {
      if (this.pending) throw new Error("Overlapping binary events");
      const split = packet.indexOf("-", 2);
      const count = Number(packet.slice(2, split));
      if (!Number.isInteger(count) || count < 1 || count > 8) throw new Error("Unexpected binary event");
      this.pending = { count, event: JSON.parse(packet.slice(split + 1)), buffers: [] };
    }
  }
  async event([name, ...args]) {
    this.events.push(name);
    if (name === "init-room") this.initialized = true;
    if (name === "first-in-room") { this.joined = true; this.alone = true; }
    if (name === "room-user-change") this.joined = true;
    if (name === "client-broadcast") {
      const message = await decrypt(this.room.key, args[0], args[1]);
      if (["SCENE_INIT", "SCENE_UPDATE"].includes(message.type) && Array.isArray(message.payload?.elements)) {
        this.elements = reconcile(this.elements, message.payload.elements);
      }
    }
  }
  async broadcast(elements) {
    if (this.error) throw this.error;
    const { ciphertext, iv } = await encrypt(this.room.key, { type: "SCENE_UPDATE", payload: { elements } });
    const header = `452-${JSON.stringify(["server-broadcast", this.room.id, { _placeholder: true, num: 0 }, { _placeholder: true, num: 1 }])}`;
    if (Buffer.byteLength(header) + ciphertext.length + iv.length > this.maxPayload) throw new Error("Live update exceeds relay payload limit");
    if (this.ws.readyState !== WebSocket.OPEN) throw new Error("Collaboration socket is not open");
    this.ws.send(header);
    this.ws.send(ciphertext);
    this.ws.send(iv);
    await this.waitFor(() => this.ws.bufferedAmount === 0);
  }
  async close() {
    this.closing = true;
    if (!this.ws) return;
    this.ws.close();
    await this.incoming;
  }
}

export async function writeScene(room, input, options = {}) {
  // Stabilize generated add ids across retries.
  const batch = structuredClone(input);
  if (Array.isArray(batch?.add)) {
    for (const element of batch.add) if (element && !element.id) element.id = webcrypto.randomUUID();
  }
  const socket = new RoomSocket(room);
  let saved;
  try {
    await loadScene(room, { onRetry: options.onRetry });
    await socket.open();
    for (let attempt = 0; attempt < 6; attempt++) {
      const current = await loadScene(room, { onRetry: options.onRetry });
      const merged = reconcile(current.elements, socket.elements);
      const result = applyBatch(merged, batch, options);
      if (!result.changed.length) return { revision: current.revision, changed: [], saved: true, notified: false };
      const receipt = await saveScene(room, result.elements, current.updateTime);
      if (!receipt) { await sleep(40 + Math.random() * 100 * (attempt + 1)); continue; }
      saved = { ...receipt, changed: result.changed, attempts: attempt + 1, saved: true, notified: false };
      // Verify exact authored elements survived a readback, even if another writer already advanced the revision.
      const verified = await loadScene(room, { onRetry: options.onRetry });
      for (const id of result.changed) {
        const expected = JSON.parse(JSON.stringify(result.elements.find(element => element.id === id)));
        const actual = verified.elements.find(element => element.id === id);
        if (!isDeepStrictEqual(actual, expected)) throw new Error("Saved change could not be verified");
      }
      try {
        await socket.broadcast(result.elements.filter(element => result.changed.includes(element.id)));
        saved.notified = true;
      } catch { saved.warning = "Saved successfully, but live notification failed. Reopen or read the room before retrying."; }
      return saved;
    }
    throw new Error("Room kept changing. No batch was saved after 6 attempts.");
  } catch (error) {
    if (saved) throw new Error(`Save succeeded at revision ${saved.revision}, but verification failed. Read before retrying.`);
    throw error;
  } finally { await socket.close(); }
}

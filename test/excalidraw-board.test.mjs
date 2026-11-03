import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { applyBatch, compact, nextIndex, reconcile, revision } from "../cli/excalidraw-board/scene.mjs";
import { encrypt, decrypt } from "../cli/excalidraw-board/protocol.mjs";

test("patches reapply to fresh elements without overwriting a concurrent field", () => {
  const original = applyBatch([], { add: [{ id: "a", type: "rectangle", x: 1, y: 2, w: 30, h: 40, future: true }] }).elements;
  const concurrent = applyBatch(original, { update: [{ id: "a", y: 50 }] }).elements;
  const result = applyBatch(concurrent, { update: [{ id: "a", x: 20 }] });
  assert.equal(result.elements[0].x, 20);
  assert.equal(result.elements[0].y, 50);
  assert.equal(result.elements[0].future, true);
  assert.equal(result.elements[0].version, 3);
  assert.deepEqual(applyBatch(result.elements, { update: [{ id: "a", x: 20 }] }).changed, []);
  const removed = applyBatch(result.elements, { delete: ["a"] });
  assert.equal(removed.elements[0].isDeleted, true);
  assert.equal(removed.elements[0].version, 4);
  assert.throws(() => applyBatch(original, { update: [{ id: "missing", x: 0 }] }), /not found/);
  assert.throws(() => applyBatch(original, { add: [{ id: "a", type: "rectangle" }] }), /already exists/);
  assert.throws(() => applyBatch(original, { update: [{ id: "a", version: 99 }] }), /managed/);
  assert.throws(() => applyBatch(original, { updates: [] }), /Unknown batch/);
});

test("updates reject every different type, including falsy values", async t => {
  const original = applyBatch([], { add: [{ id: "a", type: "rectangle" }] }).elements;
  for (const type of [null, "", false, 0, "ellipse"]) {
    await t.test(`type ${JSON.stringify(type)}`, () => {
      assert.throws(() => applyBatch(original, { update: [{ id: "a", type }] }), /Cannot change an element type/);
      assert.equal(original[0].type, "rectangle");
    });
  }
  assert.deepEqual(applyBatch(original, { update: [{ id: "a", type: "rectangle" }] }).changed, []);
});

test("arrows and lines take points, arrowheads, and two-sided bindings", () => {
  const shapes = applyBatch([], { add: [
    { id: "from", type: "rectangle", x: 0, y: 0, w: 100, h: 50 },
    { id: "to", type: "image", fileId: "f", status: "saved", x: 300, y: 0, w: 100, h: 50 },
  ] }, { imageFiles: ["f"] }).elements;
  const added = applyBatch(shapes, { add: [
    { id: "link", type: "arrow", x: 100, y: 25, points: [[0, 0], [200, -10], [150, 30]],
      startBinding: { elementId: "from" }, endBinding: { elementId: "to", mode: "inside", fixedPoint: [0, 0.5] } },
    { id: "rule", type: "line", x: 0, y: 80, points: [[0, 0], [400, 0]] },
  ] });
  const byId = id => added.elements.find(element => element.id === id);
  assert.deepEqual(added.changed, ["link", "rule", "from", "to"]);
  assert.equal(byId("link").width, 200);
  assert.equal(byId("link").height, 40);
  assert.equal(byId("link").endArrowhead, "arrow");
  assert.equal(byId("link").startArrowhead, null);
  assert.deepEqual(byId("link").startBinding, { elementId: "from", mode: "orbit", fixedPoint: [0.5, 0.5] });
  assert.deepEqual(byId("link").endBinding, { elementId: "to", mode: "inside", fixedPoint: [0, 0.5] });
  assert.equal(byId("rule").endArrowhead, null);
  assert.equal(byId("rule").polygon, false);
  assert.deepEqual(byId("from").boundElements, [{ id: "link", type: "arrow" }]);
  assert.deepEqual(byId("to").boundElements, [{ id: "link", type: "arrow" }]);

  const rebound = applyBatch(added.elements, { update: [{ id: "link", endBinding: null, points: [[0, 0], [50, 0]] }] });
  const after = id => rebound.elements.find(element => element.id === id);
  assert.deepEqual(rebound.changed, ["link", "to"]);
  assert.equal(after("link").width, 50);
  assert.deepEqual(after("to").boundElements, []);
  assert.deepEqual(after("from").boundElements, [{ id: "link", type: "arrow" }]);

  const targetGone = applyBatch(rebound.elements, { delete: ["from"] });
  assert.equal(targetGone.elements.find(element => element.id === "link").startBinding, null);
  const arrowGone = applyBatch(rebound.elements, { delete: ["link"] });
  assert.deepEqual(arrowGone.elements.find(element => element.id === "from").boundElements, []);
});

test("paths reject missing or malformed points and invalid bindings", () => {
  const shapes = applyBatch([], { add: [{ id: "box", type: "rectangle" }, { id: "other", type: "line", points: [[0, 0], [1, 1]] }] }).elements;
  const add = element => () => applyBatch(shapes, { add: [{ id: "new", type: "arrow", points: [[0, 0], [10, 0]], ...element }] });
  assert.throws(() => applyBatch(shapes, { add: [{ type: "arrow" }] }), /need points/);
  assert.throws(add({ points: [[0, 0]] }), /at least two/);
  assert.throws(add({ points: [[5, 5], [10, 0]] }), /first point/);
  assert.throws(add({ w: 10 }), /come from points/);
  assert.throws(add({ elbowed: true }), /Elbow/);
  assert.throws(add({ startBinding: { elementId: "missing" } }), /Cannot bind/);
  assert.throws(add({ startBinding: { elementId: "other" } }), /Cannot bind/);
  assert.throws(add({ startBinding: { elementId: "new" } }), /Cannot bind/);
  assert.throws(add({ startBinding: { elementId: "box", mode: "edge" } }), /orbit or inside/);
  assert.throws(add({ startBinding: { elementId: "box", focus: 0 } }), /Unknown startBinding field/);
  assert.throws(() => applyBatch(shapes, { add: [{ type: "line", points: [[0, 0], [1, 0]], startBinding: { elementId: "box" } }] }), /Only arrows/);
  assert.throws(() => applyBatch(shapes, { add: [{ type: "freedraw", points: [[0, 0], [1, 0]] }] }), /Freehand/);
  assert.throws(() => applyBatch(shapes, { add: [{ id: "new", type: "arrow", points: [[0, 0], [10, 0]], endBinding: { elementId: "box" } }], delete: ["box"] }), /Cannot bind/);
});

test("scene reconciliation uses version then lower nonce and retains tombstones", () => {
  const local = [{ id: "a", index: "a0", version: 2, versionNonce: 50 }, { id: "b", index: "a1", version: 1, versionNonce: 1 }];
  const remote = [{ id: "a", index: "a0", version: 2, versionNonce: 20, isDeleted: true }];
  assert.deepEqual(reconcile(local, remote), [remote[0], local[1]]);
  assert.equal(reconcile(remote, local)[0].isDeleted, true);
});

test("fractional successors and timestamp revisions preserve the wire contracts", () => {
  assert.equal(nextIndex(null), "a0");
  assert.equal(nextIndex("a0V"), "a1");
  assert.equal(nextIndex("az"), "b00");
  assert.equal(nextIndex("Zz"), "a0");
  assert.equal(revision("2026-01-01T00:00:00.123456789Z"), "1767225600123456");
  assert.deepEqual(compact({ id: "a", type: "rectangle", x: 1.23456, width: 10, height: 20, version: 3, seed: 123, future: true }), { id: "a", type: "rectangle", x: 1.23, w: 10, h: 20, future: true });
});

test("outline escapes remote ids, labels, and malformed coordinate strings", t => {
  const home = mkdtempSync(join(tmpdir(), "excalidraw-outline-"));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const frameId = "frame\u001b]52;c;payload\u0007";
  const groupId = "group\u009b2J\u007f";
  const elements = [
    { id: frameId, type: "frame", name: "name\n\u001b[2J\u009b", x: "\u001b[2J", y: 0, width: 10, height: 20 },
    { id: "a", type: "text", text: "label\t\u001b[31m", groupIds: [groupId], x: 1, y: 2, width: 3, height: 4 },
  ];
  const script = `
    import { openRooms } from ${JSON.stringify(new URL("../cli/excalidraw-board/rooms.mjs", import.meta.url).href)}
    import { encrypt } from ${JSON.stringify(new URL("../cli/excalidraw-board/protocol.mjs", import.meta.url).href)}
    const room = { name: "outline", id: "offline", key: "AAAAAAAAAAAAAAAAAAAAAA" }
    const registry = openRooms()
    registry.add(room)
    registry.close()
    const encrypted = await encrypt(room.key, ${JSON.stringify(elements)})
    globalThis.fetch = async () => Response.json({ updateTime: "2026-01-01T00:00:00.000001Z", fields: {
      ciphertext: { bytesValue: Buffer.from(encrypted.ciphertext).toString("base64") },
      iv: { bytesValue: Buffer.from(encrypted.iv).toString("base64") }
    } })
    process.argv = [process.execPath, "excalidraw-board", "read", "--name", "outline", "--outline"]
    await import(${JSON.stringify(new URL("../cli/excalidraw-board/excalidraw-board.mjs", import.meta.url).href)})
  `;
  const result = spawnSync(process.execPath, ["--input-type=module", "-e", script], {
    env: { ...process.env, HOME: home }, encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  assert.doesNotMatch(result.stdout, /[\x00-\x08\x0b-\x1f\x7f-\x9f]/);
  const lines = result.stdout.trimEnd().split("\n");
  assert.equal(lines.length, 3);
  assert.equal(JSON.parse(lines[1].split("\t")[1]), frameId);
  assert.equal(JSON.parse(lines[2].split("\t")[1]), groupId);
  assert.equal(JSON.parse(lines[1].split("\t")[2]), elements[0].name);
  assert.equal(JSON.parse(lines[2].split("\t")[2]), elements[1].text);
});

test("encrypted scenes round-trip and reject a different room key", async () => {
  const key = "AAAAAAAAAAAAAAAAAAAAAA";
  const message = [{ id: "a", text: "shared board 한글" }];
  const encrypted = await encrypt(key, message);
  assert.equal(encrypted.iv.length, 12);
  assert.deepEqual(await decrypt(key, encrypted.ciphertext, encrypted.iv), message);
  await assert.rejects(decrypt("AQEBAQEBAQEBAQEBAQEBAQ", encrypted.ciphertext, encrypted.iv));
});

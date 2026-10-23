import { randomBytes, randomInt } from "node:crypto";

const digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const managed = new Set(["version", "versionNonce", "updated", "index", "seed", "isDeleted"]);
const defaults = {
  x: 0, y: 0, width: 100, height: 60, angle: 0, strokeColor: "#1e1e1e",
  backgroundColor: "transparent", fillStyle: "solid", strokeWidth: 2,
  strokeStyle: "solid", roughness: 1, opacity: 100, groupIds: [], frameId: null,
  roundness: null, boundElements: null, link: null, locked: false, isDeleted: false,
};

// Append-only fractional indices. A new integer sorts after every fraction of its predecessor.
export function nextIndex(previous) {
  if (!previous) return "a0";
  const head = previous[0];
  const length = head >= "a" && head <= "z" ? head.charCodeAt(0) - 97 + 2
    : head >= "A" && head <= "Z" ? 90 - head.charCodeAt(0) + 2 : 0;
  if (!length || previous.length < length) throw new Error("Invalid existing fractional index");
  const integer = previous.slice(0, length).split("");
  for (let i = integer.length - 1; i > 0; i--) {
    const digit = digits.indexOf(integer[i]);
    if (digit < 0) throw new Error("Invalid existing fractional index");
    if (digit < 61) { integer[i] = digits[digit + 1]; return integer.join(""); }
    integer[i] = "0";
  }
  if (head === "Z") return "a0";
  if (head === "z") throw new Error("Fractional index space exhausted");
  const nextHead = String.fromCharCode(head.charCodeAt(0) + 1);
  return nextHead + "0".repeat(head >= "a" ? length : length - 2);
}

export function revision(timestamp) {
  const match = /^(.*?)(?:\.(\d+))?Z$/.exec(timestamp);
  if (!match) throw new Error("Invalid server revision");
  return (BigInt(Date.parse(`${match[1]}Z`)) * 1000n + BigInt((match[2] || "").padEnd(6, "0").slice(0, 6))).toString();
}

export function reconcile(local, remote) {
  const map = new Map(local.map(element => [element.id, element]));
  for (const element of remote) {
    const old = map.get(element.id);
    if (!old || old.version < element.version || (old.version === element.version && old.versionNonce > element.versionNonce)) map.set(element.id, element);
  }
  return [...map.values()].sort((a, b) => a.index < b.index ? -1 : a.index > b.index ? 1 : a.id < b.id ? -1 : 1);
}

function expand(input) {
  const result = { ...input };
  for (const [short, full] of [["w", "width"], ["h", "height"], ["frame", "frameId"], ["groups", "groupIds"]]) {
    if (Object.hasOwn(result, short)) {
      if (Object.hasOwn(result, full)) throw new Error(`Use ${short} or ${full}, not both`);
      result[full] = result[short];
      delete result[short];
    }
  }
  for (const key of Object.keys(result)) if (managed.has(key)) throw new Error(`${key} is managed by the tool`);
  for (const key of ["x", "y", "width", "height", "angle", "opacity", "strokeWidth", "fontSize"]) {
    if (Object.hasOwn(result, key) && (typeof result[key] !== "number" || !Number.isFinite(result[key]))) throw new Error(`${key} must be a finite number`);
  }
  if (result.width < 0 || result.height < 0) throw new Error("Dimensions must not be negative");
  return result;
}

export function applyBatch(elements, batch) {
  if (!batch || typeof batch !== "object" || Array.isArray(batch)) throw new Error("Expected a batch object");
  for (const key of Object.keys(batch)) if (!["add", "update", "delete"].includes(key)) throw new Error(`Unknown batch field: ${key}`);
  for (const key of ["add", "update", "delete"]) if (batch[key] !== undefined && !Array.isArray(batch[key])) throw new Error(`${key} must be an array`);
  const map = new Map(elements.map(element => [element.id, element]));
  const changed = [];
  const seen = new Set();
  let tail = elements.reduce((last, element) => element.index > last ? element.index : last, "");
  for (const operation of ["add", "update", "delete"]) {
    for (const value of batch[operation] || []) {
      if (operation !== "delete" && (!value || typeof value !== "object" || Array.isArray(value))) throw new Error("Elements must be objects");
      const patch = operation === "delete" ? { id: value } : expand(value);
      const id = patch.id || (operation === "add" ? randomBytes(10).toString("hex") : null);
      if (typeof id !== "string" || !id || /[\x00-\x1f]/.test(id)) throw new Error("Expected a nonempty element id");
      if (seen.has(id)) throw new Error(`Repeated element in batch: ${id}`);
      seen.add(id);
      const old = map.get(id);
      if (operation === "add" && old) throw new Error(`Element already exists: ${id}`);
      if (operation !== "add" && !old) throw new Error(`Element not found: ${id}`);
      if (operation === "add" && (typeof patch.type !== "string" || !patch.type)) throw new Error("New elements need a type");
      if (operation === "add" && patch.type === "image") throw new Error("Image creation is not supported");
      if (operation === "update" && Object.hasOwn(patch, "type") && patch.type !== old.type) throw new Error("Cannot change an element type");
      const changes = operation === "delete" ? { isDeleted: true } : patch;
      if (old && Object.entries(changes).every(([key, value]) => JSON.stringify(old[key]) === JSON.stringify(value))) continue;
      let base = old;
      if (!base) {
        tail = nextIndex(tail);
        base = { ...structuredClone(defaults), id, index: tail, seed: randomInt(2147483647), version: 0 };
        if (patch.type === "text") Object.assign(base, { text: "", originalText: "", fontSize: 20, fontFamily: 1, textAlign: "left", verticalAlign: "top", containerId: null, autoResize: true, lineHeight: 1.25 });
        if (patch.type === "frame" || patch.type === "magicframe") base.name = null;
        if (["line", "arrow", "freedraw"].includes(patch.type)) throw new Error("The proof of concept supports new shapes, text, and frames, not path creation");
      }
      const updated = { ...base, ...changes, id, version: base.version + 1, versionNonce: randomInt(2147483647), updated: Date.now() };
      if (updated.type === "text" && Object.hasOwn(changes, "text")) updated.originalText = updated.text;
      map.set(id, updated);
      changed.push(id);
    }
  }
  return { elements: [...map.values()], changed };
}

export function compact(element) {
  const result = {};
  for (const [key, value] of Object.entries(element)) {
    if (["seed", "version", "versionNonce", "updated", "index"].includes(key)) continue;
    if (Object.hasOwn(defaults, key) && JSON.stringify(defaults[key]) === JSON.stringify(value)) continue;
    const name = ({ width: "w", height: "h", frameId: "frame", groupIds: "groups" })[key] || key;
    result[name] = typeof value === "number" ? Math.round(value * 100) / 100 : value;
  }
  return result;
}

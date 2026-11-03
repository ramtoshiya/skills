import { randomBytes, randomInt } from "node:crypto";

const digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const managed = new Set(["version", "versionNonce", "updated", "index", "seed", "isDeleted"]);
const defaults = {
  x: 0, y: 0, width: 100, height: 60, angle: 0, strokeColor: "#1e1e1e",
  backgroundColor: "transparent", fillStyle: "solid", strokeWidth: 2,
  strokeStyle: "solid", roughness: 1, opacity: 100, groupIds: [], frameId: null,
  roundness: null, boundElements: null, link: null, locked: false, isDeleted: false,
};
const pathDefaults = {
  line: { startBinding: null, endBinding: null, startArrowhead: null, endArrowhead: null, polygon: false },
  arrow: { startBinding: null, endBinding: null, startArrowhead: null, endArrowhead: "arrow", elbowed: false },
};
const bindable = new Set(["rectangle", "diamond", "ellipse", "text", "image", "frame", "magicframe", "embeddable", "iframe"]);

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

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

// Paths store points relative to x and y, starting at [0, 0]. Their width and height are the points' extent.
function normalizePath(changes, type) {
  if (Object.hasOwn(changes, "width") || Object.hasOwn(changes, "height")) throw new Error("Path dimensions come from points");
  if (Object.hasOwn(changes, "elbowed") && changes.elbowed !== false) throw new Error("Elbow arrows are unsupported");
  if (Object.hasOwn(changes, "points")) {
    const points = changes.points;
    if (!Array.isArray(points) || points.length < 2 || !points.every(point => Array.isArray(point) && point.length === 2 && point.every(finite))) {
      throw new Error("points must be at least two [x, y] pairs of finite numbers");
    }
    if (points[0][0] !== 0 || points[0][1] !== 0) throw new Error("The first point must be [0, 0]. Move the path with x and y");
    const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
    changes.width = Math.max(...xs) - Math.min(...xs);
    changes.height = Math.max(...ys) - Math.min(...ys);
  }
  for (const key of ["startArrowhead", "endArrowhead"]) {
    if (Object.hasOwn(changes, key) && changes[key] !== null && (typeof changes[key] !== "string" || !changes[key])) throw new Error(`${key} must be null or an arrowhead name`);
  }
  for (const key of ["startBinding", "endBinding"]) {
    if (!Object.hasOwn(changes, key) || changes[key] === null) continue;
    if (type !== "arrow") throw new Error("Only arrows bind to elements");
    const binding = changes[key];
    if (!binding || typeof binding !== "object" || Array.isArray(binding)) throw new Error(`${key} must be null or an object`);
    for (const field of Object.keys(binding)) if (!["elementId", "mode", "fixedPoint"].includes(field)) throw new Error(`Unknown ${key} field: ${field}`);
    if (typeof binding.elementId !== "string" || !binding.elementId) throw new Error(`${key} needs an elementId`);
    const mode = binding.mode ?? "orbit";
    if (!["orbit", "inside"].includes(mode)) throw new Error(`${key} mode must be orbit or inside`);
    const fixedPoint = binding.fixedPoint ?? [0.5, 0.5];
    if (!Array.isArray(fixedPoint) || fixedPoint.length !== 2 || !fixedPoint.every(finite)) throw new Error(`${key} fixedPoint must be two finite numbers`);
    changes[key] = { elementId: binding.elementId, mode, fixedPoint };
  }
}

function bindingTargets(element) {
  if (!element || element.isDeleted || element.type !== "arrow") return [];
  return [element.startBinding, element.endBinding].filter(binding => binding?.elementId).map(binding => binding.elementId);
}

export function applyBatch(elements, batch, { imageFiles = [] } = {}) {
  if (!batch || typeof batch !== "object" || Array.isArray(batch)) throw new Error("Expected a batch object");
  for (const key of Object.keys(batch)) if (!["add", "update", "delete"].includes(key)) throw new Error(`Unknown batch field: ${key}`);
  for (const key of ["add", "update", "delete"]) if (batch[key] !== undefined && !Array.isArray(batch[key])) throw new Error(`${key} must be an array`);
  const map = new Map(elements.map(element => [element.id, element]));
  const before = new Map(map);
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
      if (operation === "update" && imageFiles.includes(patch.fileId)
          && (old.isDeleted || old.type !== "image" || old.fileId !== patch.fileId)) throw new Error("Image element changed during upload. Read the room before retrying.");
      if (operation === "add" && (typeof patch.type !== "string" || !patch.type)) throw new Error("New elements need a type");
      if (operation === "add" && patch.type === "image" && (!imageFiles.includes(patch.fileId) || patch.status !== "saved")) throw new Error("Use the image command to upload and verify image files");
      if (operation === "update" && Object.hasOwn(patch, "type") && patch.type !== old.type) throw new Error("Cannot change an element type");
      const changes = operation === "delete" ? { isDeleted: true } : patch;
      const type = old ? old.type : patch.type;
      if (operation !== "delete" && Object.hasOwn(pathDefaults, type)) normalizePath(changes, type);
      if (old && Object.entries(changes).every(([key, value]) => JSON.stringify(old[key]) === JSON.stringify(value))) continue;
      let base = old;
      if (!base) {
        tail = nextIndex(tail);
        base = { ...structuredClone(defaults), id, index: tail, seed: randomInt(2147483647), version: 0 };
        if (patch.type === "text") Object.assign(base, { text: "", originalText: "", fontSize: 20, fontFamily: 1, textAlign: "left", verticalAlign: "top", containerId: null, autoResize: true, lineHeight: 1.25 });
        if (patch.type === "frame" || patch.type === "magicframe") base.name = null;
        if (patch.type === "freedraw") throw new Error("Freehand paths are unsupported. Use a line or an arrow");
        if (Object.hasOwn(pathDefaults, patch.type)) {
          if (!Object.hasOwn(patch, "points")) throw new Error("New lines and arrows need points");
          Object.assign(base, structuredClone(pathDefaults[patch.type]));
        }
      }
      const updated = { ...base, ...changes, id, version: base.version + 1, versionNonce: randomInt(2147483647), updated: Date.now() };
      if (updated.type === "text" && Object.hasOwn(changes, "text")) updated.originalText = updated.text;
      map.set(id, updated);
      changed.push(id);
    }
  }
  syncBindings(map, before, changed);
  return { elements: [...map.values()], changed };
}

// Excalidraw keeps both sides of a binding: the arrow's start or end binding and the target's boundElements entry.
function syncBindings(map, before, changed) {
  const touch = (id, fields) => {
    const old = map.get(id);
    map.set(id, { ...old, ...fields, version: old.version + 1, versionNonce: randomInt(2147483647), updated: Date.now() });
    if (!changed.includes(id)) changed.push(id);
  };
  const setArrowEntry = (targetId, arrowId, present) => {
    const target = map.get(targetId);
    if (!target) return;
    const entries = Array.isArray(target.boundElements) ? target.boundElements : [];
    const has = entries.some(entry => entry?.id === arrowId);
    if (present && !has) touch(targetId, { boundElements: [...entries, { id: arrowId, type: "arrow" }] });
    if (!present && has) touch(targetId, { boundElements: entries.filter(entry => entry?.id !== arrowId) });
  };
  for (const id of [...changed]) {
    const element = map.get(id);
    if (element.type !== "arrow") continue;
    const targets = bindingTargets(element);
    for (const targetId of targets) {
      const target = map.get(targetId);
      if (targetId === id || !target || target.isDeleted || !bindable.has(target.type)) throw new Error(`Cannot bind ${id} to ${targetId}. Bind arrows to live shapes, text, images, or frames`);
      setArrowEntry(targetId, id, true);
    }
    for (const targetId of bindingTargets(before.get(id))) if (!targets.includes(targetId)) setArrowEntry(targetId, id, false);
  }
  for (const id of [...changed]) {
    const element = map.get(id);
    if (!element.isDeleted || !Array.isArray(element.boundElements)) continue;
    for (const entry of element.boundElements) {
      const arrow = map.get(entry?.id);
      if (!arrow || arrow.isDeleted || arrow.type !== "arrow") continue;
      const fields = {};
      for (const key of ["startBinding", "endBinding"]) if (arrow[key]?.elementId === id) fields[key] = null;
      if (Object.keys(fields).length) touch(arrow.id, fields);
    }
  }
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

import { readFile, mkdir, writeFile, rename, unlink } from 'node:fs/promises';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';

export async function readJson(path) {
  try { return JSON.parse(await readFile(path, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return undefined; throw error; }
}

export async function atomicJson(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temp = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temp, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
    await rename(temp, path);
  } finally { await unlink(temp).catch(() => {}); }
}

export function normalizeBaseUrl(value) {
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash) throw new Error('Proxy URL must not contain credentials, query, or fragment');
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) {
    throw new Error('Use HTTPS for remote proxies (HTTP is allowed only on loopback)');
  }
  url.pathname = url.pathname.replace(/\/+$/, '').replace(/\/v1$/, '');
  return url.toString().replace(/\/$/, '');
}

export function resolveConfig(explicit, legacy, env = process.env) {
  const source = explicit ?? legacy;
  if (!source && !env.CLIPROXY_API_KEY) return undefined;
  let apiKey = env.CLIPROXY_API_KEY ?? source?.apiKey;
  if (typeof apiKey !== 'string' || !apiKey.trim()) throw new Error('Configure a proxy client apiKey');
  const match = apiKey.match(/^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$/);
  if (match) apiKey = env[match[1] ?? match[2]];
  else if (apiKey.startsWith('!') || apiKey.startsWith('$')) throw new Error('Only literal keys or $ENV_VAR key references are supported; shell commands are not executed');
  if (!apiKey) throw new Error('Proxy key environment variable is unset');
  return {
    baseUrl: normalizeBaseUrl(env.CLIPROXY_BASE_URL ?? source?.baseUrl ?? 'http://127.0.0.1:8317'),
    apiKey,
    ...selectionConfig(source),
  };
}

function selectionConfig(source = {}) {
  const result = {};
  for (const field of ['include', 'exclude']) {
    if (source[field] === undefined) continue;
    if (!Array.isArray(source[field]) || source[field].some(p => typeof p !== 'string' || !p.length)) {
      throw new Error(`${field} must be an array of nonempty model-ID globs or version constraints`);
    }
    for (const pattern of source[field]) {
      if (/[<>=]/.test(pattern) && !parseConstraint(pattern)) {
        throw new Error(`Invalid version constraint "${pattern}"; use e.g. claude>=5 or gpt>=6.1`);
      }
    }
    result[field] = source[field];
  }
  if (source.sort !== undefined) {
    if (!['id-asc', 'id-desc'].includes(source.sort)) throw new Error('sort must be id-asc or id-desc');
    result.sort = source.sort;
  }
  return result;
}

function matchesGlob(id, pattern) {
  const escaped = pattern.split('*').map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*');
  return new RegExp(`^${escaped}$`).test(id);
}

// Families served by this provider and the native Pi transport used for each.
export const FAMILIES = {
  claude: { api: 'anthropic-messages', pattern: /^claude-[A-Za-z0-9._-]+$/ },
  // Image-generation and open-weight IDs are not Responses chat models.
  gpt: { api: 'openai-responses', pattern: /^gpt-(?!image-|oss-)[A-Za-z0-9._-]+$/ },
};
export const familyOf = id => Object.keys(FAMILIES).find(f => FAMILIES[f].pattern.test(id));

/**
 * Extract the model version from an ID: the first run of numeric segments.
 * claude-opus-5-5 -> [5, 5]; claude-haiku-4-5-20251001 -> [4, 5] (date ignored);
 * claude-3-7-sonnet -> [3, 7]; gpt-6.1-sol -> [6, 1]; gpt-6-sol -> [6].
 */
export function modelVersion(id) {
  const family = familyOf(id);
  if (!family) return undefined;
  const parts = [];
  for (const token of id.slice(family.length + 1).split(/[-.]/)) {
    if (/^\d{1,4}$/.test(token)) parts.push(Number(token));
    else if (parts.length) break;
  }
  return parts.length ? parts : undefined;
}

function compareVersions(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const diff = (a[i] ?? 0) - (b[i] ?? 0);
    if (diff) return Math.sign(diff);
  }
  return 0;
}

function parseConstraint(pattern) {
  const match = pattern.match(/^\s*([a-z]+)\s*(>=|<=|>|<|==?)\s*(\d+(?:\.\d+)*)\s*$/);
  if (!match || !FAMILIES[match[1]]) return undefined;
  return { family: match[1], op: match[2], version: match[3].split('.').map(Number) };
}

function matches(id, pattern) {
  const constraint = parseConstraint(pattern);
  if (!constraint) return matchesGlob(id, pattern);
  const version = modelVersion(id);
  if (familyOf(id) !== constraint.family || !version) return false;
  const c = compareVersions(version, constraint.version);
  return { '>=': c >= 0, '>': c > 0, '<=': c <= 0, '<': c < 0, '=': c === 0, '==': c === 0 }[constraint.op];
}

export function selectModels(models, { include, exclude = [], sort = 'id-desc' } = {}) {
  return models.filter(m => (include === undefined || include.some(p => matches(m.id, p))) &&
    !exclude.some(p => matches(m.id, p)))
    .sort((a, b) => (sort === 'id-desc' ? -1 : 1) * a.id.localeCompare(b.id, 'en', { numeric: true }));
}

// Per-transport allowlists. OpenAI tool-search/grammar/prompt-cache extensions are
// deliberately omitted: they are not verified through the proxy.
const COMPAT_FLAGS = {
  'anthropic-messages': ['forceAdaptiveThinking', 'supportsMidConvoEffort', 'supportsMidConvoSystemMessages',
    'supportsMidConvoToolChanges', 'supportsTemperature', 'supportsStrictTools'],
  'openai-responses': ['supportsStrictMode'],
};
const THINKING_LEVELS = ['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'];
const positive = (value) => Number.isSafeInteger(value) && value > 0;
export function mapModels(payload, catalog = []) {
  if (!payload || !Array.isArray(payload.data)) throw new Error('Invalid proxy catalog: expected data array');
  const known = new Map(catalog.map(m => [m.id, m]));
  const found = new Map();
  for (const entry of payload.data) {
    const family = entry && typeof entry.id === 'string' ? familyOf(entry.id) : undefined;
    if (!family) continue;
    const api = FAMILIES[family].api;
    if (entry.visibility === 'hide') continue;
    const reference = known.get(entry.id);
    const contextWindow = [entry.context_window, entry.context_length, reference?.contextWindow].find(positive) ?? 200000;
    const maxTokens = Math.min(contextWindow, [entry.max_completion_tokens, entry.max_output_tokens, reference?.maxTokens].find(positive) ?? 16384);
    const levels = entry.thinking?.levels;
    const reasoning = typeof reference?.reasoning === 'boolean' ? reference.reasoning : Array.isArray(levels) && levels.length > 0;
    const model = {
      id: entry.id,
      api,
      name: reference?.name ?? entry.id,
      reasoning,
      input: reference?.input?.includes('image') ? ['text', 'image'] : ['text'],
      contextWindow,
      maxTokens,
      // Subscription billing cannot be inferred from API catalog prices.
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    };
    if (reference?.thinkingLevelMap) model.thinkingLevelMap = reference.thinkingLevelMap;
    else if (Array.isArray(levels) && levels.length) {
      model.thinkingLevelMap = Object.fromEntries(THINKING_LEVELS.map(level => [level, levels.includes(level) ? level : null]));
    }
    // The native driver needs these catalog capabilities as well as the effort map.
    // Never copy endpoints, headers, or arbitrary proxy-supplied compatibility flags.
    if (reference?.compat) {
      model.compat = Object.fromEntries(COMPAT_FLAGS[api].filter(k => typeof reference.compat[k] === 'boolean')
        .map(k => [k, reference.compat[k]]));
    }
    // Do not turn on idle cache warming automatically.
    found.set(entry.id, model);
  }
  return [...found.values()].sort((a, b) => a.id.localeCompare(b.id));
}

export class Discovery {
  constructor({ config, cachePath, catalog = [], fetchImpl = fetch, now = Date.now, ttlMs = 300000, timeoutMs = 5000 }) {
    Object.assign(this, { config, cachePath, catalog, fetchImpl, now, ttlMs, timeoutMs });
    this.models = [];
    this.fetchedAt = 0;
    this.lastError = undefined;
    this.inflight = undefined;
  }
  async restore() {
    try {
      const cache = await readJson(this.cachePath);
      if (cache?.version !== 3 || cache.baseUrl !== this.config.baseUrl || !Array.isArray(cache.models)) return;
      // Project only allowed metadata; never trust cached endpoint/header fields.
      const catalog = [...cache.models.filter(m => m && typeof m.id === 'string'), ...this.catalog];
      this.models = selectModels(mapModels({ data: cache.models }, catalog), this.config);
      this.fetchedAt = Number.isFinite(cache.fetchedAt) ? cache.fetchedAt : 0;
    } catch { this.lastError = 'Could not read catalog cache'; }
  }
  async refresh({ force = false, signal } = {}) {
    signal?.throwIfAborted();
    if (this.inflight) {
      await this.inflight;
      signal?.throwIfAborted();
      return this.models;
    }
    if (!force && this.fetchedAt > 0 && this.now() - this.fetchedAt < this.ttlMs) return this.models;
    this.inflight = this.fetchModels(signal);
    try { return await this.inflight; } finally { this.inflight = undefined; }
  }
  async fetchModels(signal) {
    const combined = signal ? AbortSignal.any([signal, AbortSignal.timeout(this.timeoutMs)]) : AbortSignal.timeout(this.timeoutMs);
    try {
      const response = await this.fetchImpl(`${this.config.baseUrl}/v1/models`, {
        headers: { Authorization: `Bearer ${this.config.apiKey}` },
        signal: combined,
        redirect: 'error',
      });
      if (!response.ok) throw new Error(`Catalog request failed (HTTP ${response.status})`);
      const models = mapModels(await response.json(), this.catalog);
      combined.throwIfAborted();
      this.models = selectModels(models, this.config);
      this.fetchedAt = this.now();
      this.lastError = undefined;
      // Cache stores only sanitized model metadata, never the client key.
      try { await atomicJson(this.cachePath, { version: 3, baseUrl: this.config.baseUrl, fetchedAt: this.fetchedAt, models }); }
      catch { this.lastError = 'Models refreshed, but catalog cache could not be written'; }
      return this.models;
    } catch (error) {
      // Do not expose HTTP bodies, URLs, headers, or arbitrary fetch errors.
      this.lastError = /^Catalog request failed \(HTTP \d+\)$/.test(error.message) ? error.message : 'Catalog unavailable, invalid, or cancelled';
      throw new Error(this.lastError);
    }
  }
}

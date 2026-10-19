import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Discovery, normalizeBaseUrl, resolveConfig, mapModels, selectModels, modelVersion } from '../core.mjs';

const config = { baseUrl: 'http://127.0.0.1:8317', apiKey: 'secret-test-key' };
async function fixture(t, options = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'pi-cliproxy-test-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return new Discovery({ config, cachePath: join(dir, 'cache.json'), ...options });
}
const response = data => new Response(JSON.stringify({ data }));

test('normalizes root and /v1 endpoints; rejects insecure remote endpoints and URL credentials', () => {
  assert.equal(normalizeBaseUrl('http://127.0.0.1:8317/v1/'), config.baseUrl);
  assert.equal(normalizeBaseUrl('https://example.com/proxy/v1'), 'https://example.com/proxy');
  for (const url of ['http://example.com', 'https://user:password@example.com', 'https://example.com/?token=secret', 'file:///tmp/x']) assert.throws(() => normalizeBaseUrl(url));
});
test('resolves config precedence and environment references without executing commands', () => {
  assert.deepEqual(resolveConfig(undefined, config, {}), config);
  assert.equal(resolveConfig({ ...config, apiKey: '$KEY' }, undefined, { KEY: 'abc' }).apiKey, 'abc');
  assert.equal(resolveConfig(config, undefined, { CLIPROXY_API_KEY: 'override' }).apiKey, 'override');
  assert.equal(resolveConfig(undefined, undefined, {}), undefined);
  assert.throws(() => resolveConfig({ ...config, apiKey: '!echo nope' }, undefined, {}));
  assert.throws(() => resolveConfig({ ...config, apiKey: '$MISSING' }, undefined, {}));
});
test('discovers only Claude/GPT chat IDs, deduplicates, filters hidden models and sanitizes metadata', () => {
  const models = mapModels({ data: [
    { id: 'claude-new', headers: { Authorization: 'bad' }, baseUrl: 'https://bad' },
    { id: 'gpt-6-sol' }, { id: 'other-model' }, { id: 'gpt-image-2' }, { id: 'gpt-oss-120b-medium' },
    { id: 'codex-auto-review' }, { id: 'claude-hidden', visibility: 'hide' },
    { id: 'claude-new' }, { id: 'claude-../bad' }, null,
  ] });
  assert.deepEqual(models.map(m => [m.id, m.api]), [['claude-new', 'anthropic-messages'], ['gpt-6-sol', 'openai-responses']]);
  assert.equal(models[0].contextWindow, 200000);
  assert.equal(models[0].maxTokens, 16384);
  assert.equal(models[0].reasoning, false);
  assert.equal(models[0].headers, undefined);
  assert.equal(models[0].baseUrl, undefined);
  assert.throws(() => mapModels({ models: [] }));
  assert.deepEqual(mapModels({ data: [] }), []);
});
test('uses exact catalog matches; positive limits only and output cannot exceed context', () => {
  const models = mapModels({ data: [{ id: 'claude-known', context_window: 1000, max_completion_tokens: 2000 }] }, [
    { id: 'claude-known', reasoning: true, input: ['text', 'image'], thinkingLevelMap: { max: 'max' }, contextWindow: 9999 },
  ]);
  assert.equal(models[0].maxTokens, 1000);
  assert.equal(models[0].reasoning, true);
  assert.deepEqual(models[0].input, ['text', 'image']);
});
test('sends proxy credentials, prevents redirects, caches sanitized models and honors TTL', async t => {
  let calls = 0;
  const d = await fixture(t, { fetchImpl: async (url, options) => {
    calls++;
    assert.equal(url, config.baseUrl + '/v1/models');
    assert.equal(options.headers.Authorization, 'Bearer ' + config.apiKey);
    assert.equal(options.redirect, 'error');
    return response([{ id: 'claude-test' }]);
  } });
  await d.refresh(); await d.refresh();
  assert.equal(calls, 1);
  await d.refresh({ force: true }); assert.equal(calls, 2);
  const text = await readFile(d.cachePath, 'utf8');
  assert.ok(!text.includes(config.apiKey));
  assert.equal((await stat(d.cachePath)).mode & 0o777, 0o600);
  const restored = new Discovery({ config, cachePath: d.cachePath });
  await restored.restore(); assert.deepEqual(restored.models, d.models);
  const other = new Discovery({ config: { ...config, baseUrl: 'http://localhost:9999' }, cachePath: d.cachePath });
  await other.restore(); assert.deepEqual(other.models, []);
});
test('failed refresh preserves stale models and never logs upstream bodies or arbitrary errors', async t => {
  const d = await fixture(t, { fetchImpl: async () => response([{ id: 'claude-test' }]) });
  await d.refresh();
  d.fetchImpl = async () => new Response('secret upstream payload', { status: 401 });
  await assert.rejects(d.refresh({ force: true }), /HTTP 401/);
  assert.equal(d.models.length, 1);
  d.fetchImpl = async () => { throw new Error(config.apiKey); };
  await assert.rejects(d.refresh({ force: true }), /Catalog unavailable/);
  assert.ok(!d.lastError.includes(config.apiKey));
});
test('valid empty catalog replaces old models; malformed catalog does not', async t => {
  const d = await fixture(t, { fetchImpl: async () => response([{ id: 'claude-test' }]) });
  await d.refresh();
  d.fetchImpl = async () => new Response('{}');
  await assert.rejects(d.refresh({ force: true })); assert.equal(d.models.length, 1);
  d.fetchImpl = async () => response([]);
  await d.refresh({ force: true }); assert.equal(d.models.length, 0);
});
test('deduplicates concurrent fetches', async t => {
  let calls = 0;
  const d = await fixture(t, { fetchImpl: async () => { calls++; await new Promise(r => setTimeout(r, 10)); return response([]); } });
  await Promise.all([d.refresh(), d.refresh()]); assert.equal(calls, 1);
});
test('honors cancellation and timeout', async t => {
  const d = await fixture(t, { timeoutMs: 10, fetchImpl: async (_url, { signal }) => {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, 100);
      signal.addEventListener('abort', () => { clearTimeout(timer); reject(signal.reason); }, { once: true });
    });
    return response([]);
  } });
  await assert.rejects(d.refresh(), /cancelled/);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(d.refresh({ signal: controller.signal }));
});
test('xhigh/max capabilities and adaptive effort survive caching and catalog updates', async t => {
  const reference = {
    id: 'claude-opus-5-5', reasoning: true,
    thinkingLevelMap: { off: null, xhigh: 'xhigh', max: 'max' },
    compat: { forceAdaptiveThinking: true, supportsMidConvoEffort: true, supportsTemperature: false, unsafe: true },
  };
  const d = await fixture(t, { catalog: [reference], fetchImpl: async () => response([{ id: reference.id }]) });
  await d.refresh();
  assert.equal(d.models[0].thinkingLevelMap.xhigh, 'xhigh');
  assert.equal(d.models[0].compat.forceAdaptiveThinking, true);
  assert.equal(d.models[0].compat.supportsMidConvoEffort, true);
  assert.equal(d.models[0].compat.supportsTemperature, false);
  assert.equal(d.models[0].compat.unsafe, undefined);
  const restored = new Discovery({ config, cachePath: d.cachePath });
  await restored.restore(); assert.deepEqual(restored.models, d.models);
  const updated = new Discovery({ config, cachePath: d.cachePath, catalog: [{ ...reference, thinkingLevelMap: { xhigh: null, max: 'max' } }] });
  await updated.restore(); assert.equal(updated.models[0].thinkingLevelMap.xhigh, null);
});
test('proxy-advertised effort levels include xhigh but not unsupported levels', () => {
  const [m] = mapModels({ data: [{ id: 'claude-future', thinking: { levels: ['low', 'high', 'xhigh'] } }] });
  assert.equal(m.reasoning, true);
  assert.equal(m.thinkingLevelMap.xhigh, 'xhigh');
  assert.equal(m.thinkingLevelMap.max, null);
});
test('include/exclude globs and descending numeric ID order', () => {
  const models = ['claude-opus-5-5', 'claude-opus-4-6', 'claude-opus-5-10', 'claude-fable-5-1'].map(id => ({ id }));
  assert.deepEqual(selectModels(models).map(m => m.id), ['claude-opus-5-10', 'claude-opus-5-5', 'claude-opus-4-6', 'claude-fable-5-1']);
  assert.deepEqual(selectModels(models, { include: ['claude-opus-5-*', 'claude-fable-*'], exclude: ['*-5-10'] }).map(m => m.id), ['claude-opus-5-5', 'claude-fable-5-1']);
  assert.deepEqual(selectModels(models, { include: [] }), []);
  assert.equal(selectModels(models, { sort: 'id-asc' })[0].id, 'claude-fable-5-1');
  assert.equal(selectModels([{ id: 'claude-a.1' }, { id: 'claude-ab1' }], { include: ['claude-a.1'] }).length, 1);
});
test('validates filter configuration', () => {
  for (const bad of [{ include: 'claude-*' }, { exclude: [42] }, { sort: 'newest' }]) {
    assert.throws(() => resolveConfig({ ...config, ...bad }, undefined, {}));
  }
  assert.deepEqual(resolveConfig({ ...config, include: ['claude-opus-*'], exclude: [], sort: 'id-asc' }, undefined, {}).include, ['claude-opus-*']);
});
test('cache retains excluded models so changed filters work offline', async t => {
  const d = await fixture(t, { config: { ...config, include: ['claude-opus-*'] }, fetchImpl: async () => response([{ id: 'claude-opus-5-5' }, { id: 'claude-fable-5-1' }]) });
  await d.refresh(); assert.equal(d.models.length, 1);
  const restored = new Discovery({ config: { ...config, include: ['claude-fable-*'] }, cachePath: d.cachePath });
  await restored.restore(); assert.equal(restored.models[0].id, 'claude-fable-5-1');
  assert.equal(restored.models.length, 1);
});

test('GPT models use Responses transport and only allowlisted OpenAI compat flags', () => {
  const [m] = mapModels({ data: [{ id: 'gpt-6-sol' }] }, [{
    id: 'gpt-6-sol', name: 'GPT-6 Sol', reasoning: true, input: ['text', 'image'], contextWindow: 272000, maxTokens: 128000,
    thinkingLevelMap: { off: 'none', xhigh: 'xhigh' }, baseUrl: 'https://api.openai.com/v1',
    compat: { supportsStrictMode: true, supportsToolSearch: true, forceAdaptiveThinking: true },
  }]);
  assert.equal(m.api, 'openai-responses');
  assert.equal(m.baseUrl, undefined);
  assert.equal(m.thinkingLevelMap.xhigh, 'xhigh');
  assert.deepEqual(m.compat, { supportsStrictMode: true });
});
test('extracts versions from model IDs', () => {
  const cases = {
    'claude-opus-5-5': [5, 5], 'claude-fable-5': [5], 'claude-haiku-4-5-20251001': [4, 5],
    'claude-3-7-sonnet-20250219': [3, 7], 'claude-opus-4-6-thinking': [4, 6],
    'gpt-6.1-sol': [6, 1], 'gpt-6-sol': [6], 'gpt-5.5': [5, 5], 'gpt-image-2': undefined,
  };
  for (const [id, version] of Object.entries(cases)) assert.deepEqual(modelVersion(id), version, id);
});
test('version constraints select families by version', () => {
  const ids = ['claude-opus-5-5', 'claude-fable-5', 'claude-opus-4-8', 'claude-3-7-sonnet-20250219',
    'gpt-6.1-sol', 'gpt-6-sol', 'gpt-5.6-sol', 'gpt-5.5'];
  const pick = (config) => selectModels(ids.map(id => ({ id })), config).map(m => m.id);
  assert.deepEqual(pick({ include: ['claude>=5', 'gpt>=6'] }), ['gpt-6.1-sol', 'gpt-6-sol', 'claude-opus-5-5', 'claude-fable-5']);
  assert.deepEqual(pick({ include: ['gpt>6'] }), ['gpt-6.1-sol']);
  // include entries are OR-ed; express ranges with include + exclude.
  assert.deepEqual(pick({ include: ['gpt>=5.6'], exclude: ['gpt>=6'] }), ['gpt-5.6-sol']);
  assert.deepEqual(pick({ include: ['claude>=5'], exclude: ['claude=5', 'claude-fable-*'] }), ['claude-opus-5-5']);
  assert.deepEqual(pick({ include: ['claude<4'] }), ['claude-3-7-sonnet-20250219']);
  for (const bad of ['claude>=x', 'llama>=3', 'gpt=>6']) assert.throws(() => resolveConfig({ ...config, include: [bad] }, undefined, {}));
});

test('corrupt and unsupported-version caches are ignored', async t => {
  const d = await fixture(t);
  await writeFile(d.cachePath, '{broken');
  await d.restore(); assert.deepEqual(d.models, []);
  await writeFile(d.cachePath, JSON.stringify({ version: 2, baseUrl: config.baseUrl, fetchedAt: 1, models: [{ id: 'claude-test' }] }));
  await d.restore(); assert.deepEqual(d.models, []); assert.equal(d.fetchedAt, 0);
});

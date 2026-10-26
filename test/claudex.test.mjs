import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';

const command = resolve('cli/claudex/claudex.cjs');

async function fixture(t, catalog, status = 200, codex = { models: [], status: 200 }) {
  const dir = await mkdtemp(join(tmpdir(), 'claudex-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const capture = join(dir, 'capture.json');
  await writeFile(join(dir, 'claude'), `#!${process.execPath}
require('node:fs').writeFileSync(process.env.CAPTURE, JSON.stringify({
  args: process.argv.slice(2), key: process.env.ANTHROPIC_API_KEY,
  token: process.env.ANTHROPIC_AUTH_TOKEN,
  imagegenBaseUrl: process.env.IMAGEGEN_BASE_URL,
  imagegenKey: process.env.IMAGEGEN_API_KEY
}));
process.exitCode = 7;
`, { mode: 0o755 });
  const requests = [];
  const server = createServer((req, res) => {
    requests.push({ url: req.url, authorization: req.headers.authorization });
    const native = req.url === '/v1/models?client_version=0.155.0';
    res.writeHead(native ? codex.status : status, {
      'Content-Type': 'application/json',
      ...(native && codex.status === 302 ? { Location: '/redirected' } : {}),
    });
    res.end(JSON.stringify(native ? { models: codex.models } : { data: catalog }));
  });
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  t.after(() => new Promise(done => { server.close(done); server.closeAllConnections(); }));
  const config = join(dir, 'config.json');
  await writeFile(config, JSON.stringify({
    baseUrl: `http://127.0.0.1:${server.address().port}/v1/`, apiKey: '$TEST_PROXY_KEY',
  }));
  return {
    baseUrl: `http://127.0.0.1:${server.address().port}`,
    requests,
    capture: () => readFile(capture, 'utf8').then(JSON.parse),
    run: (args = [], extra = {}) => new Promise((done, reject) => {
      const child = spawn(process.execPath, [command, ...args], { env: {
        ...process.env, PATH: dir + ':' + process.env.PATH, CAPTURE: capture,
        CLAUDEX_CONFIG: config, TEST_PROXY_KEY: 'test-client-key',
        CLIPROXY_API_KEY: '', CLIPROXY_BASE_URL: '',
        IMAGEGEN_BASE_URL: undefined, IMAGEGEN_API_KEY: undefined,
        ANTHROPIC_API_KEY: 'other-provider-key', ANTHROPIC_AUTH_TOKEN: 'other-token',
        ...extra,
      } });
      let stdout = '', stderr = '';
      child.stdout.on('data', chunk => stdout += chunk);
      child.stderr.on('data', chunk => stderr += chunk);
      child.on('error', reject);
      child.on('close', code => done({ code, stdout, stderr }));
    }),
  };
}

test('discovers role models and forwards CLI arguments, credentials, and exit status', async t => {
  const f = await fixture(t, [
    { id: 'gpt-9-astra', owned_by: 'openai', visibility: 'hide' },
    { id: 'gpt-9-sol', owned_by: 'other' },
    ...['gpt-5.1-astra', 'gpt-6-astra', 'gpt-6.1-sol', 'gpt-6.1-mini', 'gpt-image-9']
      .map(id => ({ id, owned_by: 'openai' })),
  ], 200, { status: 200, models: [{ slug: 'gpt-6.1-sol', context_window: 500000, max_context_window: 872000 }] });
  const args = ['--model', 'gpt-6.1-sol', '-p', 'a prompt with spaces'];
  assert.equal((await f.run(args)).code, 7);
  const child = await f.capture();
  const settings = JSON.parse(child.args[1]);
  assert.equal(settings.model, 'gpt-6.1-sol');
  assert.equal(settings.autoCompactEnabled, true);
  assert.equal(settings.env.CLAUDE_CODE_EXTRA_BODY, undefined);
  assert.equal(settings.env.CLAUDE_CODE_MAX_CONTEXT_TOKENS, '872000');
  assert.equal(settings.env.ANTHROPIC_DEFAULT_FABLE_MODEL, 'gpt-6-astra');
  assert.equal(settings.env.ANTHROPIC_DEFAULT_SONNET_MODEL, 'gpt-6.1-sol');
  assert.equal(settings.env.CLAUDE_CODE_SUBAGENT_MODEL, 'gpt-6.1-sol');
  assert.equal(settings.env.ANTHROPIC_DEFAULT_HAIKU_MODEL, 'gpt-6.1-mini');
  assert.deepEqual(child.args.slice(2), args);
  assert.equal(child.key, 'test-client-key');
  assert.equal(child.token, '');
  assert.ok(!JSON.stringify(child.args).includes('test-client-key'));
  assert.deepEqual(f.requests, ['/v1/models', '/v1/models?client_version=0.155.0']
    .map(url => ({ url, authorization: 'Bearer test-client-key' })));
});

test('passes imagegen connection defaults and independent overrides through the child environment', async t => {
  for (const overrides of [
    {},
    { IMAGEGEN_BASE_URL: 'https://images.example.test/v1' },
    { IMAGEGEN_API_KEY: 'test-imagegen-key' },
    { IMAGEGEN_BASE_URL: 'https://images.example.test/v1', IMAGEGEN_API_KEY: 'test-imagegen-key' },
  ]) {
    const f = await fixture(t, [{ id: 'gpt-6-sol', owned_by: 'openai' }]);
    const result = await f.run([], { CLIPROXY_API_KEY: 'test-resolved-proxy-key', ...overrides });
    assert.equal(result.code, 7);
    const child = await f.capture();
    assert.equal(child.imagegenBaseUrl, overrides.IMAGEGEN_BASE_URL ?? f.baseUrl + '/v1');
    assert.equal(child.imagegenKey, overrides.IMAGEGEN_API_KEY ?? 'test-resolved-proxy-key');
    for (const key of ['test-resolved-proxy-key', 'test-imagegen-key']) {
      assert.ok(!JSON.stringify(child.args).includes(key));
      assert.ok(!result.stdout.includes(key));
      assert.ok(!result.stderr.includes(key));
    }
  }
});

test('resolves startup context from route metadata and falls back when unavailable', async t => {
  const models = [
    { slug: 'gpt-6.1-sol', context_window: 500000, max_context_window: 872000 },
    { slug: 'gpt-6-astra', context_window: 272000, max_context_window: 872000 },
    { slug: 'gpt-6-sol', context_window: 272000, max_context_window: 872000 },
    { slug: 'gpt-6-luna', context_window: 272000, max_context_window: 872000 },
  ];
  const catalog = ['gpt-6.1-sol', 'gpt-6-astra'].map(id => ({ id, owned_by: 'openai' }));
  for (const scenario of [
    { name: 'explicit base model', args: ['--model', 'gpt-6-astra'], models, expected: 872000 },
    { name: 'role alias', args: ['--model=fable'], models, expected: 872000 },
    { name: 'last override wins', args: ['--model=fable', '--model', 'gpt-6.1-sol'], models, expected: 872000 },
    ...['gpt-6-sol', 'gpt-6-luna'].map(model => ({
      name: model + ' maximum', args: ['--model', model], models, expected: 872000,
    })),
    { name: 'smaller maximum wins', models: [{ slug: 'gpt-6.1-sol', context_window: 500000, max_context_window: 400000 }], expected: 400000 },
    { name: 'maximum without default window', models: [{ slug: 'gpt-6.1-sol', max_context_window: 872000 }], expected: 872000 },
    { name: 'invalid maximum uses default window', models: [{ slug: 'gpt-6.1-sol', context_window: 500000, max_context_window: -1 }], expected: 500000 },
    { name: 'ordinary catalog fallback', status: 404, catalog: [{ ...catalog[0], context_length: 320000 }], expected: 320000 },
    { name: 'missing metadata', models: [], expected: 250000, warning: true },
    { name: 'invalid metadata', models: [{ slug: 'gpt-6.1-sol', context_window: '500000' }], expected: 250000, warning: true },
    { name: 'unknown override', args: ['--model=custom'], models, expected: 250000, warning: true },
    { name: 'redirect is refused', status: 302, expected: 250000, warning: true },
  ]) {
    await t.test(scenario.name, async t => {
      const f = await fixture(t, scenario.catalog ?? catalog, 200, {
        status: scenario.status ?? 200, models: scenario.models ?? models,
      });
      const result = await f.run(scenario.args);
      assert.equal(result.code, 7);
      const settings = JSON.parse((await f.capture()).args[1]);
      assert.equal(settings.env.CLAUDE_CODE_MAX_CONTEXT_TOKENS, String(scenario.expected));
      assert.equal(result.stderr.includes('Context metadata unavailable'), !!scenario.warning);
      assert.ok(!result.stderr.includes('test-client-key'));
      assert.equal(f.requests.length, 2);
    });
  }
});

test('uses the main model for missing roles and honors connection overrides', async t => {
  const f = await fixture(t, [{ id: 'gpt-6-codex', owned_by: 'openai' }]);
  assert.equal((await f.run([], { CLIPROXY_API_KEY: 'override-key' })).code, 7);
  const settings = JSON.parse((await f.capture()).args[1]);
  assert.equal(settings.model, 'gpt-6-codex');
  assert.equal(settings.env.ANTHROPIC_DEFAULT_FABLE_MODEL, 'gpt-6-codex');
  assert.equal(settings.env.ANTHROPIC_DEFAULT_SONNET_MODEL, 'gpt-6-codex');
  assert.equal(settings.env.ANTHROPIC_DEFAULT_HAIKU_MODEL, 'gpt-6-codex');
  assert.equal(f.requests[0].authorization, 'Bearer override-key');
});

test('discovery failures never launch Claude or expose the key', async t => {
  for (const [catalog, status] of [[[], 200], [[], 401], [[], 302]]) {
    const f = await fixture(t, catalog, status);
    const result = await f.run();
    assert.equal(result.code, 1);
    assert.match(result.stderr, /Could not resolve models/);
    assert.ok(!result.stderr.includes('test-client-key'));
    await assert.rejects(f.capture(), { code: 'ENOENT' });
  }
});

test('version works without proxy configuration or discovery', async t => {
  const f = await fixture(t, []);
  assert.equal((await f.run(['--version'], { CLAUDEX_CONFIG: '/nonexistent/claudex.json' })).code, 7);
  assert.deepEqual((await f.capture()).args, ['--version']);
  assert.deepEqual(f.requests, []);
});

test('leading --fast requests fast processing without changing effort or forwarding the flag', async t => {
  for (const body of ['', '{"metadata":{"user_id":"test-user"},"speed":"standard"}']) {
    const f = await fixture(t, [{ id: 'gpt-6.1-sol', owned_by: 'openai' }]);
    const args = ['--effort', 'high', '-p', '--fast'];
    assert.equal((await f.run(['--fast', ...args], { CLAUDE_CODE_EXTRA_BODY: body })).code, 7);
    const child = await f.capture();
    const settings = JSON.parse(child.args[1]);
    assert.deepEqual(child.args.slice(2), args);
    assert.deepEqual(JSON.parse(settings.env.CLAUDE_CODE_EXTRA_BODY), {
      ...(body ? { metadata: { user_id: 'test-user' } } : {}), speed: 'fast',
    });
  }
});

test('--fast rejects invalid extra bodies before discovery without exposing their contents', async t => {
  for (const body of ['not-json-private-value', 'null', '[]', 'true']) {
    const f = await fixture(t, []);
    const result = await f.run(['--fast'], { CLAUDE_CODE_EXTRA_BODY: body });
    assert.equal(result.code, 1);
    assert.match(result.stderr, /requires CLAUDE_CODE_EXTRA_BODY to be a JSON object/);
    assert.ok(!result.stderr.includes(body));
    assert.deepEqual(f.requests, []);
    await assert.rejects(f.capture(), { code: 'ENOENT' });
  }
});

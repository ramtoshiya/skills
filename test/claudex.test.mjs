import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';

const command = resolve('cli/claudex/claudex.cjs');

async function fixture(t, catalog, status = 200) {
  const dir = await mkdtemp(join(tmpdir(), 'claudex-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const capture = join(dir, 'capture.json');
  await writeFile(join(dir, 'claude'), `#!${process.execPath}
require('node:fs').writeFileSync(process.env.CAPTURE, JSON.stringify({
  args: process.argv.slice(2), key: process.env.ANTHROPIC_API_KEY,
  token: process.env.ANTHROPIC_AUTH_TOKEN
}));
process.exitCode = 7;
`, { mode: 0o755 });
  const requests = [];
  const server = createServer((req, res) => {
    requests.push({ url: req.url, authorization: req.headers.authorization });
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ data: catalog }));
  });
  await new Promise(done => server.listen(0, '127.0.0.1', done));
  t.after(() => new Promise(done => { server.close(done); server.closeAllConnections(); }));
  const config = join(dir, 'config.json');
  await writeFile(config, JSON.stringify({
    baseUrl: `http://127.0.0.1:${server.address().port}/v1/`, apiKey: '$TEST_PROXY_KEY',
  }));
  return {
    requests,
    capture: () => readFile(capture, 'utf8').then(JSON.parse),
    run: (args = [], extra = {}) => new Promise((done, reject) => {
      const child = spawn(process.execPath, [command, ...args], { env: {
        ...process.env, PATH: dir + ':' + process.env.PATH, CAPTURE: capture,
        CLAUDEX_CONFIG: config, TEST_PROXY_KEY: 'test-client-key',
        CLIPROXY_API_KEY: '', CLIPROXY_BASE_URL: '',
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
  ]);
  const args = ['--model', 'custom-model', '-p', 'a prompt with spaces'];
  assert.equal((await f.run(args)).code, 7);
  const child = await f.capture();
  const settings = JSON.parse(child.args[1]);
  assert.equal(settings.model, 'gpt-6.1-sol');
  assert.equal(settings.autoCompactEnabled, true);
  assert.equal(settings.env.CLAUDE_CODE_MAX_CONTEXT_TOKENS, '500000');
  assert.equal(settings.env.ANTHROPIC_DEFAULT_FABLE_MODEL, 'gpt-6-astra');
  assert.equal(settings.env.ANTHROPIC_DEFAULT_SONNET_MODEL, 'gpt-6.1-sol');
  assert.equal(settings.env.CLAUDE_CODE_SUBAGENT_MODEL, 'gpt-6.1-sol');
  assert.equal(settings.env.ANTHROPIC_DEFAULT_HAIKU_MODEL, 'gpt-6.1-mini');
  assert.deepEqual(child.args.slice(2), args);
  assert.equal(child.key, 'test-client-key');
  assert.equal(child.token, '');
  assert.ok(!JSON.stringify(child.args).includes('test-client-key'));
  assert.deepEqual(f.requests, [{ url: '/v1/models', authorization: 'Bearer test-client-key' }]);
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

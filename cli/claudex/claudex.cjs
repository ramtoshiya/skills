#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { spawn } = require('node:child_process');

function connection() {
  const configPath = process.env.CLAUDEX_CONFIG || [
    path.join(os.homedir(), '.config/claudex/config.json'),
    path.join(os.homedir(), '.pi/agent/cliproxy-provider.json'),
  ].find(file => fs.existsSync(file));
  const config = configPath ? JSON.parse(fs.readFileSync(configPath, 'utf8')) : {};
  let key = process.env.CLIPROXY_API_KEY || config.apiKey;
  if (typeof key === 'string') {
    const reference = /^\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))$/.exec(key);
    if (reference) key = process.env[reference[1] || reference[2]];
  }
  if (typeof key !== 'string' || !key.trim()) throw new Error('Set CLIPROXY_API_KEY or apiKey in ~/.config/claudex/config.json');
  const url = new URL(process.env.CLIPROXY_BASE_URL || config.baseUrl || 'http://127.0.0.1:8317');
  if (url.username || url.password || url.search || url.hash) throw new Error('Proxy URL must not contain credentials, a query, or a fragment');
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
    throw new Error('Remote proxies require HTTPS');
  }
  const baseUrl = url.href.replace(/\/+$/, '').replace(/\/v1$/, '');
  return { key, baseUrl };
}

function selectModels(data) {
  if (!Array.isArray(data)) throw new Error('Invalid proxy model catalog');
  const models = data.flatMap(model => {
    const match = /^gpt-(\d+)(?:\.(\d+))?(?:-(astra|sol|terra|luna|codex|mini|nano))?$/.exec(model?.id);
    return match && model.owned_by === 'openai' && model.visibility !== 'hide'
      ? [{ id: model.id, major: +match[1], minor: +(match[2] || 0), tier: match[3] || '' }]
      : [];
  });
  if (!models.length) throw new Error('Proxy advertises no recognized GPT text models');
  function pick(tiers) {
    const candidates = models.filter(model => tiers.includes(model.tier));
    candidates.sort((a, b) => b.major - a.major || b.minor - a.minor || tiers.indexOf(a.tier) - tiers.indexOf(b.tier));
    return candidates[0]?.id;
  }
  const main = pick(['astra', 'sol', 'codex', '', 'terra']) || models[0].id;
  return { main, fable: pick(['astra']) || main,
    standard: pick(['terra', 'sol', 'codex', '']) || main,
    light: pick(['luna', 'mini', 'nano']) || main };
}

function launch(args, env = process.env) {
  const child = spawn('claude', args, { stdio: 'inherit', env });
  child.on('error', () => {
    console.error('claudex: Could not start claude. Install Claude Code and put it on PATH.');
    process.exitCode = 1;
  });
  child.on('exit', (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exitCode = code;
  });
}

function startupModel(args, selected) {
  let model = selected.main;
  for (let i = 0; i < args.length && args[i] !== '--'; i++) {
    if (args[i] === '--model' && args[i + 1]) model = args[++i];
    else if (args[i].startsWith('--model=')) model = args[i].slice(8);
  }
  return { fable: selected.fable, opus: selected.main,
    sonnet: selected.standard, haiku: selected.light }[model] || model;
}

function advertisedContext(entry) {
  const positive = value => Number.isSafeInteger(value) && value > 0;
  return [entry?.max_context_window, entry?.context_window, entry?.context_length].find(positive);
}

async function contextLimit(baseUrl, key, catalog, model) {
  try {
    const response = await fetch(baseUrl + '/v1/models?client_version=0.155.0', {
      headers: { Authorization: 'Bearer ' + key },
      signal: AbortSignal.timeout(5000), redirect: 'error',
    });
    if (response.ok) {
      const entries = (await response.json()).models;
      const context = Array.isArray(entries)
        ? advertisedContext(entries.find(entry => entry?.slug === model)) : undefined;
      if (context) return context;
    }
  } catch {}
  const context = advertisedContext(catalog.find(entry => entry?.id === model));
  if (context) return context;
  console.error('claudex: Context metadata unavailable. Using a 250,000-token limit.');
  return 250000;
}

async function main() {
  const args = process.argv.slice(2);
  const fast = args[0] === '--fast';
  let extraBody;
  if (fast) {
    args.shift();
    try {
      extraBody = JSON.parse(process.env.CLAUDE_CODE_EXTRA_BODY || '{}');
      if (!extraBody || typeof extraBody !== 'object' || Array.isArray(extraBody)) throw new Error();
    } catch {
      console.error('claudex: --fast requires CLAUDE_CODE_EXTRA_BODY to be a JSON object when set.');
      process.exitCode = 1;
      return;
    }
  }
  if (args.length === 1 && ['--version', '-v', '--help', '-h'].includes(args[0])) {
    launch(args);
    return;
  }
  const { key, baseUrl } = connection();
  const response = await fetch(baseUrl + '/v1/models', {
    headers: { Authorization: 'Bearer ' + key },
    signal: AbortSignal.timeout(5000), redirect: 'error',
  });
  if (!response.ok) throw new Error('Proxy model lookup returned HTTP ' + response.status);
  const catalog = (await response.json()).data;
  const selected = selectModels(catalog);
  const context = await contextLimit(baseUrl, key, catalog, startupModel(args, selected));
  const settings = {
    model: selected.main,
    autoCompactEnabled: true,
    env: {
      ANTHROPIC_BASE_URL: baseUrl,
      ANTHROPIC_DEFAULT_FABLE_MODEL: selected.fable,
      ANTHROPIC_DEFAULT_OPUS_MODEL: selected.main,
      ANTHROPIC_DEFAULT_SONNET_MODEL: selected.standard,
      ANTHROPIC_DEFAULT_HAIKU_MODEL: selected.light,
      CLAUDE_CODE_SUBAGENT_MODEL: selected.standard,
      CLAUDE_CODE_MAX_CONTEXT_TOKENS: String(context),
      CLAUDE_CODE_ALWAYS_ENABLE_EFFORT: '1',
      CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY: '3',
      ENABLE_TOOL_SEARCH: 'false',
      ...(fast ? { CLAUDE_CODE_EXTRA_BODY: JSON.stringify({ ...extraBody, speed: 'fast' }) } : {}),
    },
  };
  launch(['--settings', JSON.stringify(settings), ...args], {
    ...process.env, ANTHROPIC_API_KEY: key, ANTHROPIC_AUTH_TOKEN: '',
    IMAGEGEN_BASE_URL: process.env.IMAGEGEN_BASE_URL ?? baseUrl + '/v1',
    IMAGEGEN_API_KEY: process.env.IMAGEGEN_API_KEY ?? key,
  });
}

main().catch(() => {
  console.error('claudex: Could not resolve models. Check the proxy URL, client key, and GPT model catalog.');
  process.exitCode = 1;
});

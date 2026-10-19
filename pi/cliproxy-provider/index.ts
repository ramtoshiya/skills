import { join } from 'node:path';
import { getAgentDir, type ExtensionAPI, type ProviderChatModelConfig } from '@earendil-works/pi-coding-agent';
import { Discovery, readJson, resolveConfig } from './core.mjs';

const PROVIDER = 'cliproxy-native';

export default async function (pi: ExtensionAPI) {
  const agentDir = getAgentDir();
  const configPath = join(agentDir, 'cliproxy-provider.json');
  // Read existing cliproxy settings without modifying them or invoking credential commands.
  const explicit = await readJson(configPath);
  const legacy = explicit ? undefined : (await readJson(join(agentDir, 'models.json')))?.providers?.cliproxy;
  const config = resolveConfig(explicit, legacy);
  if (!config) {
    pi.registerCommand('cliproxy-status', {
      description: 'Show CLIProxyAPI discovery provider status',
      handler: async (_args, ctx) => ctx.ui.notify(`Not configured. Create ${configPath} with baseUrl and apiKey, then /reload.`, 'warning'),
    });
    return;
  }

  // Reference metadata only (chat entries). Endpoints and headers are never used.
  let catalog = [];
  try {
    const store = await readJson(join(agentDir, 'models-store.json'));
    catalog.push(...(store?.anthropic?.models ?? []), ...(store?.openai?.models ?? []));
  }
  catch { /* Discovery still works with conservative metadata defaults. */ }
  catalog = catalog.filter((m: { type?: string }) => (m.type ?? 'chat') === 'chat');
  const discovery = new Discovery({ config, cachePath: join(agentDir, 'cliproxy-provider-models.json'), catalog });
  await discovery.restore();
  // Cold starts discover before startup model selection. Warm starts use the cache.
  if (!discovery.fetchedAt) {
    try { await discovery.refresh(); } catch { /* Expose status; allow the rest of Pi to start. */ }
  }

  // Anthropic Messages appends /v1/messages to the root. OpenAI Responses expects a /v1 base.
  const withEndpoints = () => discovery.models.map((m: ProviderChatModelConfig) =>
    (m.api === 'openai-responses' ? { ...m, baseUrl: `${config.baseUrl}/v1` } : m)) as ProviderChatModelConfig[];
  const registration = () => ({
    name: 'CLIProxyAPI',
    baseUrl: config.baseUrl,
    api: 'anthropic-messages' as const,
    // ProviderConfig treats $ and leading ! specially. Escape literal credentials.
    apiKey: config.apiKey.startsWith('!') ? `$!${config.apiKey.slice(1)}` : config.apiKey.replaceAll('$', () => '$$'),
    models: withEndpoints(),
    refreshModels: async (context: import('@earendil-works/pi-ai').RefreshModelsContext) => {
      if (context.allowNetwork) await discovery.refresh({ force: context.force, signal: context.signal });
      return withEndpoints();
    },
  });
  pi.registerProvider(PROVIDER, registration());

  pi.on('session_start', async (_event, ctx) => {
    try {
      await discovery.refresh();
      pi.registerProvider(PROVIDER, registration());
    } catch {
      if (ctx.hasUI) ctx.ui.notify(`CLIProxyAPI: ${discovery.lastError}. Keeping ${discovery.models.length} cached models.`, 'warning');
    }
  });
  pi.registerCommand('cliproxy-refresh', {
    description: 'Refresh Claude/GPT models from CLIProxyAPI (no inference requests)',
    handler: async (_args, ctx) => {
      await ctx.waitForIdle();
      try {
        await discovery.refresh({ force: true });
        pi.registerProvider(PROVIDER, registration());
        ctx.ui.notify(`CLIProxyAPI: ${discovery.models.length} models after filters.`, 'info');
      } catch { ctx.ui.notify(`CLIProxyAPI: ${discovery.lastError}. Existing models retained.`, 'error'); }
    },
  });
  pi.registerCommand('cliproxy-status', {
    description: 'Show CLIProxyAPI discovery/cache status (no credentials)',
    handler: async (_args, ctx) => {
      const age = discovery.fetchedAt ? `${Math.max(0, Math.floor((Date.now() - discovery.fetchedAt) / 1000))}s ago` : 'never';
      ctx.ui.notify(`${PROVIDER}: ${discovery.models.length} models after filters; catalog fetched ${age}. ${discovery.lastError ?? 'Ready.'}`, 'info');
    },
  });
}

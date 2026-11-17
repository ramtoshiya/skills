export default function plugin(bb) {
  bb.settings.define({
    memoryEnabled: { type: 'boolean', label: 'Claude Code memory', default: false },
    subagentsDisabled: { type: 'boolean', label: 'Disable provider subagents', default: true },
    workflowsDisabled: { type: 'boolean', label: 'Disable Workflow tool', default: true },
    sandboxEnabled: { type: 'boolean', label: 'Claude Code sandbox', default: true },
  });

  bb.providers.register({
    id: 'claudex',
    displayName: 'Claudex',
    family: 'claude-code',
    icon: 'Zap',
    strings: {
      signInHint: 'Configure the installed Claudex wrapper and its proxy.',
      expiredHint: 'Check the Claudex proxy connection and credentials.',
      installUrl: 'https://github.com/get-bb/bb',
      planModeCopy: 'Claudex will plan before executing.',
    },
    maintenance: { health: true, usage: false, installation: false },
    capabilities: {
      supportsServiceTier: false,
      supportsNativeUserQuestion: true,
      fork: 'checkpoint',
      supportsManualCompaction: true,
      supportsThreadArchive: false,
      supportsThreadRename: false,
      permissionModes: ['accept-edits', 'auto', 'full'],
      reasoningLevels: ['low', 'medium', 'high', 'xhigh', 'max'],
    },
    reasoningLevels: ['low', 'medium', 'high', 'xhigh', 'max'].map(id => ({ id, label: id })),
    composerActions: ['plan'],
    completedTurnDisplay: 'flat',
    experimental_nativeSkillRoots: {
      project: [{ path: '.claude/skills', ancestors: true, skipIfManifest: '.claude-plugin/plugin.json' }],
    },
    experimental_nativeCommandRoots: { project: ['.claude/commands'] },
    experimental_resolvesNativeRoots: true,
    models: { scope: 'host' },
    deriveProviderOptions(context) {
      return {
        memoryEnabled: context.settings.memoryEnabled === true,
        providerSubagentsEnabled: context.settings.subagentsDisabled === false,
        workflowsEnabled: context.settings.workflowsDisabled === false,
        sandboxEnabled: context.settings.sandboxEnabled !== false,
        ...(context.promptMode === 'plan' ? { claudeCodePermissionMode: 'plan' } : {}),
      };
    },
  });
}

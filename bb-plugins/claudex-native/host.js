import { experimental_providerBridge as bridge } from './vendor/claude-host.js';

process.env.BB_CLAUDE_CODE_EXECUTABLE = (await import('node:path')).join((await import('node:os')).homedir(), '.local', 'bin', 'claudex');

export { default } from './vendor/claude-host.js';
export const experimental_providerBridge = bridge;

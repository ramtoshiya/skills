import { homedir } from 'node:os';
import { join } from 'node:path';

process.env.BB_CLAUDE_CODE_EXECUTABLE = join(homedir(), '.local', 'bin', 'claudex');

export { default, experimental_providerBridge } from './claude-host.local.js';

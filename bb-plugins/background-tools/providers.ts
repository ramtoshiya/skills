export const CLAUDE_CODE_PROVIDERS = ["claude-code", "claudex"] as const;

export function isClaudeCodeProvider(providerId: string): boolean {
  return (CLAUDE_CODE_PROVIDERS as readonly string[]).includes(providerId);
}

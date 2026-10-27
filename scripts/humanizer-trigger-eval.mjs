import { mkdtemp, mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawn } from 'node:child_process';

// Measure actual first-turn Skill calls, not a model's claim that it used a skill.
const [casesPath, englishPath, koreanPath, outputPath, model = 'gpt-6.1-sol', repetitions = '3'] = process.argv.slice(2);
if (!outputPath) throw new Error('Usage: node scripts/humanizer-trigger-eval.mjs CASES ENGLISH_SKILL KOREAN_SKILL OUTPUT [MODEL] [REPETITIONS]');
if (!Number.isInteger(Number(repetitions)) || Number(repetitions) < 1) throw new Error('REPETITIONS must be a positive integer');
const cases = JSON.parse(await readFile(casesPath, 'utf8'));
if (!cases.length || new Set(cases.map(item => item.id)).size !== cases.length || cases.some(item => !/^[a-z0-9-]+$/.test(item.id) || typeof item.query !== 'string')) {
  throw new Error('Cases need unique lowercase slug IDs and query strings');
}
const root = await mkdtemp(join(tmpdir(), 'humanizer-trigger-'));
const plugin = join(root, 'plugin');
const skills = ['humanize', 'humanize-korean'];
const sources = [englishPath, koreanPath];
const metadata = [];
await mkdir(join(plugin, '.claude-plugin'), { recursive: true });
await writeFile(join(plugin, '.claude-plugin/plugin.json'), JSON.stringify({ name: 'humanizer-eval', description: 'Isolated humanizer routing evaluation' }));
for (let i = 0; i < skills.length; i++) {
  const source = await readFile(sources[i], 'utf8');
  const frontmatter = source.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!frontmatter) throw new Error(`Missing frontmatter: ${sources[i]}`);
  metadata.push({ name: skills[i], frontmatter: frontmatter[1] });
  const directory = join(plugin, 'skills', skills[i]);
  await mkdir(directory, { recursive: true });
  // Only metadata is needed for the first decision. Do not execute upstream workflows.
  await writeFile(join(directory, 'SKILL.md'), `${frontmatter[0]}\n\nRouting observation complete.\n`);
}
const version = await new Promise((accept, reject) => {
  const child = spawn('claude', ['--version']);
  let text = '';
  child.stdout.on('data', chunk => { text += chunk; });
  child.on('error', reject);
  child.on('close', code => code ? reject(new Error('claude --version failed')) : accept(text.trim()));
});
async function run(item, repetition) {
  const directory = join(root, `${item.id}-${repetition}`);
  await mkdir(directory);
  const env = { ...process.env, CLAUDE_CONFIG_DIR: join(directory, 'config') };
  delete env.CLAUDECODE;
  const args = ['--setting-sources', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
    '--plugin-dir', plugin, '--tools', 'Skill', '--allowedTools', 'Skill', '--permission-mode', 'dontAsk',
    '--no-session-persistence', '--max-turns', '1', '--model', model, '--output-format', 'stream-json', '--verbose', '-p', item.query];
  return new Promise(accept => {
    const child = spawn('claude', args, { cwd: directory, env });
    let stdout = '', stderr = '', expired = false;
    const timer = setTimeout(() => { expired = true; child.kill('SIGTERM'); }, 90000);
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('error', error => { stderr += error.message; });
    child.on('close', code => {
      clearTimeout(timer);
      const events = stdout.split('\n').filter(Boolean).flatMap(line => { try { return [JSON.parse(line)]; } catch { return []; } });
      const init = events.find(event => event.type === 'system' && event.subtype === 'init');
      const available = init?.skills ?? [];
      const calls = events.filter(event => event.type === 'assistant').flatMap(event => event.message?.content ?? [])
        .filter(block => block.type === 'tool_use' && block.name === 'Skill').map(block => block.input?.skill);
      const result = events.find(event => event.type === 'result');
      const assistant = events.some(event => event.type === 'assistant');
      const visible = skills.every(skill => available.includes(`humanizer-eval:${skill}`));
      const valid = !expired && assistant && visible && result && ['success', 'error_max_turns'].includes(result.subtype);
      const row = { id: item.id, repetition, conversation_language: item.conversation_language,
        target_language: item.target_language, category: item.category, valid: Boolean(valid),
        calls, available_skills: available, model: init?.model, exit_code: code,
        result: result?.subtype ?? null, error: valid ? null : (expired ? 'timeout' : stderr.slice(-1500) || result?.errors || 'Missing assistant, result, or skills') };
      console.log(`${item.id} #${repetition}: ${row.valid ? calls.join(',') || 'none' : JSON.stringify(row.error)}`);
      accept(row);
    });
  });
}
try {
  const queue = cases.flatMap(item => Array.from({ length: Number(repetitions) }, (_, index) => [item, index + 1]));
  const results = [];
  await Promise.all(Array.from({ length: Math.min(6, queue.length) }, async () => {
    while (queue.length) { const [item, repetition] = queue.shift(); results.push(await run(item, repetition)); }
  }));
  results.sort((a, b) => a.id.localeCompare(b.id) || a.repetition - b.repetition);
  const output = { schema_version: 1, measured_at: new Date().toISOString(), model, claude_version: version,
    repetitions: Number(repetitions), boundary: 'First assistant turn Skill invocation, metadata-only, two skills visible together', metadata, results };
  await writeFile(resolve(outputPath), JSON.stringify(output, null, 2) + '\n');
  if (results.some(row => !row.valid)) process.exitCode = 1;
} finally {
  await rm(root, { recursive: true, force: true });
}

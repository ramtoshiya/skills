import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, chmod, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

test('routing CLI counts tool calls, ignores prose claims, and rejects incomplete runs', async () => {
  const root = await mkdtemp(join(tmpdir(), 'routing-test-'));
  try {
    const cli = join(root, 'claude');
    await writeFile(cli, `#!/usr/bin/env node
if (process.argv.includes('--version')) { console.log('fixture-cli'); process.exit(0); }
const query = process.argv.at(-1);
console.log(JSON.stringify({type:'system',subtype:'init',skills:['humanizer-eval:humanize','humanizer-eval:humanize-korean'],model:'fixture-model'}));
if (query === 'broken') process.exit(1);
console.log(JSON.stringify({type:'assistant',message:{content:query === 'call' ? [{type:'tool_use',name:'Skill',input:{skill:'humanizer-eval:humanize-korean'}}] : [{type:'text',text:'I invoked humanizer-eval:humanize'}]}}));
console.log(JSON.stringify({type:'result',subtype:query === 'call' ? 'error_max_turns' : 'success'}));
`);
    await chmod(cli, 0o755);
    const skill = join(root, 'SKILL.md');
    await writeFile(skill, '---\nname: fixture\ndescription: Fixture skill.\n---\n');
    const cases = join(root, 'cases.json');
    await writeFile(cases, JSON.stringify(['call', 'claim', 'broken'].map(id => ({ id, query: id, conversation_language: 'ko', target_language: 'ko', category: 'rewrite' }))));
    const output = join(root, 'results.json');
    const child = spawnSync(process.execPath, [resolve('scripts/humanizer-trigger-eval.mjs'), cases, skill, skill, output, 'fixture-model', '1'], {
      env: { ...process.env, PATH: `${root}:${process.env.PATH}` }, encoding: 'utf8', timeout: 15000,
    });
    assert.equal(child.status, 1, child.stderr);
    const { results } = JSON.parse(await readFile(output, 'utf8'));
    assert.deepEqual(results.find(row => row.id === 'call').calls, ['humanizer-eval:humanize-korean']);
    assert.equal(results.find(row => row.id === 'call').valid, true);
    assert.deepEqual(results.find(row => row.id === 'claim').calls, []);
    assert.equal(results.find(row => row.id === 'claim').valid, true);
    assert.equal(results.find(row => row.id === 'broken').valid, false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

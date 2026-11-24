import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { execFile, execFileSync } from 'node:child_process';
import { availableParallelism } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const units = join(root, 'dev/tests/unittest_units.py');
const uv = ['run', '--no-project', '--managed-python', '--python', '>=3.11', 'python'];
const python = [...uv, units];

execFileSync('uv', [...uv, join(root, 'setup/agents/hook_binary.py'), 'build'], { cwd: root, stdio: 'inherit' });

const listed = ['dev/tests/plugins', 'dev/tests/setup'].flatMap(dir =>
  JSON.parse(execFileSync('uv', [...python, 'list', dir], { cwd: root, encoding: 'utf8' })).map(unit => ({ dir, ...unit })));

describe('python', { concurrency: availableParallelism() }, () => {
  for (const { dir, name, ids } of listed) {
    it(`${dir} ${name}`, async t => {
      const { error, output } = await new Promise(done => execFile('uv', [...python, 'run', dir, ...ids],
        { cwd: root, maxBuffer: 64 * 1024 * 1024 }, (error, stdout, stderr) => done({ error, output: stdout + stderr })));
      assert.ok(!error, output);
      const ran = output.match(/^Ran (\d+) tests? /m)?.[1];
      if (ran && output.includes(`OK (skipped=${ran})`)) t.skip(`unittest skipped all ${ran}`);
    });
  }
});

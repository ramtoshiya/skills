import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');

test('decision records, links and rule citations agree', () => {
  const result = spawnSync('uv', ['run', '--no-project', '--managed-python', '--python', '>=3.11', 'python',
    'tools/decisions/decisions.py', 'check'], { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

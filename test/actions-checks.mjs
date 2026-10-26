import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const root = new URL('../', import.meta.url);

for (const [name, task, step, diagnostic] of [
  ['invalid step contract', 'actions:syntax', 'uses: actions/checkout@v7\n        run: echo invalid', /unexpected key "uses".*\[syntax-check\]/],
  ['expression injection', 'actions:security', 'run: echo "${{ github.event.issue.title }}"', /template-injection/],
]) {
  test(`${task} fails visibly for ${name}`, () => {
    const dir = mkdtempSync(join(tmpdir(), 'actions-check-'));
    try {
      writeFileSync(join(dir, 'mise.toml'), readFileSync(new URL('mise.toml', root)));
      writeFileSync(join(dir, 'mise.lock'), readFileSync(new URL('mise.lock', root)));
      mkdirSync(join(dir, '.github/workflows'), { recursive: true });
      writeFileSync(join(dir, '.github/workflows/check.yml'), `name: Fixture
on: issues
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - ${step}
`);
      const git = spawnSync('git', ['init', '--quiet', dir], { encoding: 'utf8' });
      assert.equal(git.status, 0, git.stderr);
      const result = spawnSync('mise', ['--locked', 'run', task], {
        cwd: dir,
        encoding: 'utf8',
        env: { ...process.env, MISE_TRUSTED_CONFIG_PATHS: dir },
      });
      assert.notEqual(result.status, 0, 'a bad workflow must fail the task');
      assert.match(result.stdout + result.stderr, diagnostic);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
}

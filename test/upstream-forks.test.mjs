import assert from 'node:assert/strict';
import test from 'node:test';
import { checkForks, comparisonPath, driftResult, marker, reconcile, validatePairs } from '../scripts/upstream-forks.mjs';

const pair = { fork: 'ramtoshiya/ouroboros', branch: 'main', upstream: 'Q00/ouroboros', upstreamBranch: 'main' };
const comparison = (behind_by, status = 'diverged') => ({ behind_by, status, html_url: 'https://github.com/Q00/ouroboros/compare/main...ramtoshiya:main' });
const issue = (number, overrides = {}) => ({ number, state: 'open', user: { login: 'github-actions[bot]' }, ...driftResult(pair, comparison(2)), ...overrides });

test('compares upstream base against fork head, including encoded branch names', () => {
  assert.equal(comparisonPath(pair), '/repos/Q00/ouroboros/compare/main...ramtoshiya%3Amain');
  assert.equal(comparisonPath({ ...pair, branch: 'feature/a', upstreamBranch: 'release/b' }), '/repos/Q00/ouroboros/compare/release%2Fb...ramtoshiya%3Afeature%2Fa');
});

test('uses behind_by for behind and diverged, and zero for caught-up branches', () => {
  for (const [count, status] of [[3, 'behind'], [5, 'diverged'], [0, 'ahead'], [0, 'identical']]) {
    const result = driftResult(pair, comparison(count, status));
    assert.equal(result.behind, count);
    assert.ok(result.body.includes(`**${count} commits behind**`));
    assert.ok(result.body.includes(comparison(count).html_url));
  }
  for (const value of [-1, undefined, '3', 1.5]) {
    assert.throws(() => driftResult(pair, comparison(value)), /Invalid/);
  }
});

test('validates configuration and keeps identity specific to both branches', () => {
  assert.deepEqual(validatePairs([pair]), [pair]);
  for (const pairs of [[], [pair, pair], [{ ...pair, fork: 'bad' }], [{ ...pair, branch: '' }]]) {
    assert.throws(() => validatePairs(pairs));
  }
  assert.notEqual(marker(pair), marker({ ...pair, upstreamBranch: 'next' }));
});

test('creates drift issue, ignores unrelated issues and PRs, and does nothing when caught up', async () => {
  const calls = [];
  const api = async (...args) => calls.push(args);
  const unrelated = [issue(1, { pull_request: {} }), issue(2, { user: { login: 'human' } }), issue(3, { body: 'other' })];
  await reconcile(api, 'ramtoshiya/skills', pair, comparison(2), unrelated);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], ['POST', '/repos/ramtoshiya/skills/issues', { title: issue(1).title, body: issue(1).body }]);
  calls.length = 0;
  await reconcile(api, 'ramtoshiya/skills', pair, comparison(0), unrelated);
  assert.deepEqual(calls, []);
});

test('updates one issue, closes duplicates, avoids unchanged writes, and closes on catch-up', async () => {
  const calls = [];
  const api = async (...args) => calls.push(args);
  await reconcile(api, 'ramtoshiya/skills', pair, comparison(4), [issue(1), issue(2)]);
  assert.equal(calls.length, 2);
  assert.equal(calls[0][2].body, driftResult(pair, comparison(4)).body);
  assert.deepEqual(calls[1], ['PATCH', '/repos/ramtoshiya/skills/issues/2', { state: 'closed', state_reason: 'not_planned' }]);
  calls.length = 0;
  await reconcile(api, 'ramtoshiya/skills', pair, comparison(2), [issue(1)]);
  assert.deepEqual(calls, []);
  await reconcile(api, 'ramtoshiya/skills', pair, comparison(0, 'ahead'), [issue(1)]);
  assert.deepEqual(calls, [['PATCH', '/repos/ramtoshiya/skills/issues/1', { state: 'closed', state_reason: 'completed' }]]);
});

test('paginates issues before deduplication', async () => {
  const calls = [];
  await checkForks(async (method, path, body) => {
    calls.push([method, path, body]);
    if (path.endsWith('&page=1')) return Array.from({ length: 100 }, (_, number) => issue(number, { body: 'unrelated' }));
    if (path.endsWith('&page=2')) return [issue(101)];
    if (path.includes('/compare/')) return comparison(2);
    throw new Error('Unexpected write');
  }, 'ramtoshiya/skills', [pair]);
  assert.equal(calls.length, 3);
});

test('comparison errors never close issues, and other pairs still run', async () => {
  const calls = [];
  const other = { ...pair, upstreamBranch: 'next' };
  await assert.rejects(checkForks(async (method, path, body) => {
    calls.push([method, path, body]);
    if (path.includes('/issues?')) return [issue(1)];
    if (path === comparisonPath(pair)) throw new Error('GitHub 404');
    if (path === comparisonPath(other)) return comparison(1);
    return {};
  }, 'ramtoshiya/skills', [pair, other]), /GitHub 404/);
  assert.equal(calls.filter(([method]) => method === 'PATCH').length, 0);
  assert.equal(calls.filter(([method]) => method === 'POST').length, 1);
});

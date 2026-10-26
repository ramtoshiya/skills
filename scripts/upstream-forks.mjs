import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

export function validatePairs(pairs) {
  if (!Array.isArray(pairs) || !pairs.length) throw new Error('Expected monitored fork pairs');
  const keys = new Set();
  for (const pair of pairs) {
    for (const key of ['fork', 'upstream']) {
      if (!/^[\w.-]+\/[\w.-]+$/.test(pair[key])) throw new Error(`Invalid ${key}`);
    }
    for (const key of ['branch', 'upstreamBranch']) {
      if (typeof pair[key] !== 'string' || !pair[key].trim()) throw new Error(`Invalid ${key}`);
    }
    const key = marker(pair);
    if (keys.has(key)) throw new Error('Duplicate monitored pair');
    keys.add(key);
  }
  return pairs;
}

export function marker(pair) {
  return `<!-- upstream-fork-drift:${JSON.stringify([pair.fork, pair.branch, pair.upstream, pair.upstreamBranch])} -->`;
}

export function comparisonPath(pair) {
  const owner = pair.fork.split('/')[0];
  return `/repos/${pair.upstream}/compare/${encodeURIComponent(pair.upstreamBranch)}...${encodeURIComponent(`${owner}:${pair.branch}`)}`;
}

export function driftResult(pair, comparison) {
  if (!Number.isSafeInteger(comparison.behind_by) || comparison.behind_by < 0 ||
      !['ahead', 'behind', 'diverged', 'identical'].includes(comparison.status) ||
      typeof comparison.html_url !== 'string' || !comparison.html_url.startsWith('https://github.com/')) {
    throw new Error('Invalid GitHub comparison response');
  }
  return {
    behind: comparison.behind_by,
    title: `Upstream drift: ${pair.fork}:${pair.branch}`,
    body: `${marker(pair)}\n\n${pair.fork}:${pair.branch} is **${comparison.behind_by} commits behind** ${pair.upstream}:${pair.upstreamBranch}.\n\n[Compare branches](${comparison.html_url})\n\nReview and merge upstream manually, then review marketplace pins separately. This check does not change either repository or its pins.`,
  };
}

export async function reconcile(api, repository, pair, comparison, issues) {
  const result = driftResult(pair, comparison);
  const matches = issues.filter(issue => !issue.pull_request && issue.state === 'open' &&
    issue.user?.login === 'github-actions[bot]' && issue.body?.split('\n')[0] === marker(pair));
  const path = `/repos/${repository}/issues`;
  if (result.behind && !matches.length) {
    await api('POST', path, { title: result.title, body: result.body });
  }
  for (const [index, issue] of matches.entries()) {
    if (!result.behind || index > 0) {
      await api('PATCH', `${path}/${issue.number}`, { state: 'closed', state_reason: result.behind ? 'not_planned' : 'completed' });
    } else if (issue.title !== result.title || issue.body !== result.body) {
      await api('PATCH', `${path}/${issue.number}`, { title: result.title, body: result.body });
    }
  }
}

export async function checkForks(api, repository, pairs) {
  validatePairs(pairs);
  const issues = [];
  for (let page = 1; ; page++) {
    const batch = await api('GET', `/repos/${repository}/issues?state=open&per_page=100&page=${page}`);
    issues.push(...batch);
    if (batch.length < 100) break;
  }
  const errors = [];
  for (const pair of pairs) {
    try {
      const comparison = await api('GET', comparisonPath(pair));
      await reconcile(api, repository, pair, comparison, issues);
    } catch (error) {
      errors.push(new Error(`${pair.fork}: ${error.message}`));
    }
  }
  if (errors.length) throw new AggregateError(errors, errors.map(error => error.message).join('\n'));
}

async function main() {
  if (!process.env.GITHUB_TOKEN) throw new Error('GITHUB_TOKEN is required');
  const pairs = JSON.parse(await readFile(new URL('../.github/upstream-forks.json', import.meta.url), 'utf8'));
  const api = async (method, path, body) => {
    const response = await fetch(`https://api.github.com${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(30_000),
    });
    if (!response.ok) throw new Error(`GitHub ${method} ${path}: ${response.status}`);
    return response.json();
  };
  await checkForks(api, 'ramtoshiya/skills', pairs);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}

#!/usr/bin/env node
// Search public X posts through Yahoo! JAPAN realtime search, inside a Chrome
// that the visible-chrome skill opened. Prints one JSON object to stdout.
import { parseArgs } from 'node:util';

const usage = 'Usage: yahoo-realtime.mjs CDP_ENDPOINT [--pages N] [--sort latest|popular] QUERY';
let parsed;
try {
  parsed = parseArgs({
    allowPositionals: true,
    options: { pages: { type: 'string', default: '1' }, sort: { type: 'string', default: 'latest' } },
  });
} catch (error) {
  console.error(`${error.message}\n${usage}`);
  process.exit(2);
}
const [endpoint, query, ...extra] = parsed.positionals;
const pages = Number(parsed.values.pages);
const sort = parsed.values.sort;
if (!endpoint || !query || extra.length || !Number.isInteger(pages) || pages < 1 || pages > 10 || !['latest', 'popular'].includes(sort)) {
  console.error(`${usage}\nPass the query as one argument. --pages is 1 to 10.`);
  process.exit(2);
}
const endpointUrl = new URL(endpoint);
if (!['127.0.0.1', 'localhost', '[::1]'].includes(endpointUrl.hostname)) {
  console.error('The CDP endpoint must be on loopback.');
  process.exit(2);
}

const params = new URLSearchParams({ p: query, ei: 'UTF-8' });
if (sort === 'popular') params.set('md', 'h');
const searchUrl = `https://search.yahoo.co.jp/realtime/search?${params}`;

const targets = await (await fetch(new URL('/json/list', endpointUrl))).json();
let target = targets.find(t => t.type === 'page' && t.url.startsWith('https://search.yahoo.co.jp/realtime'))
  ?? targets.find(t => t.type === 'page' && t.url === 'about:blank');
if (!target) target = await (await fetch(new URL('/json/new?about:blank', endpointUrl), { method: 'PUT' })).json();

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve, { once: true });
  ws.addEventListener('error', () => reject(new Error('Cannot connect to the Chrome page')), { once: true });
});
let nextId = 0;
const pending = new Map();
const listeners = [];
ws.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message);
    pending.delete(message.id);
  } else if (message.method) {
    for (const listener of [...listeners]) if (listener.method === message.method) {
      listeners.splice(listeners.indexOf(listener), 1);
      listener.resolve(message);
    }
  }
});
const send = (method, args = {}) => new Promise(resolve => {
  const id = ++nextId;
  pending.set(id, resolve);
  ws.send(JSON.stringify({ id, method, params: args }));
});
const nextEvent = (method, ms) => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${method}`)), ms);
  listeners.push({ method, resolve: message => { clearTimeout(timer); resolve(message); } });
});

// Runs in the page. Reads the server-rendered results, then requests later
// pages from the same endpoint the page's own "もっと見る" button uses.
async function collect(pages, offsetMode) {
  const node = document.getElementById('__NEXT_DATA__');
  if (!node) return { blocked: true, title: document.title, url: location.href };
  const data = JSON.parse(node.textContent).props.pageProps.pageData;
  const timeline = data.timeline ?? { head: { totalResultsAvailable: 0 }, entry: [] };
  const entries = [...timeline.entry];
  let oldest = data.timelineSettings?.oldestTweetId;
  const offset = offsetMode || data.timelineSettings?.useOffsetTimeline;
  let failed = null;
  for (let b = 1; b < pages && data.pagination && entries.length < timeline.head.totalResultsAvailable; b++) {
    await new Promise(resolve => setTimeout(resolve, 1500 + Math.random() * 1500));
    const query = new URLSearchParams({ ...data.pagination.params, b });
    if (offset) query.set('start', String(entries.length));
    else query.set('oldestTweetId', oldest);
    const response = await fetch(`/realtime/api/v1${data.pagination.path}?${query}`);
    if (!response.ok) { failed = `page ${b + 1}: HTTP ${response.status}`; break; }
    const page = (await response.json()).timeline;
    if (!page?.head?.totalResultsReturned) break;
    entries.push(...page.entry);
    oldest = page.entry.at(-1).id;
  }
  return {
    total: timeline.head.totalResultsAvailable,
    error: data.searchError?.errorType || null,
    failed,
    best: data.bestTweet?.id ? data.bestTweet : null,
    entries,
  };
}

const jst = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo', dateStyle: 'short', timeStyle: 'short' });
const clean = text => text.replace(/\tSTART\t|\tEND\t/g, '');
const simplify = e => ({
  id: e.id,
  url: e.url.split('?')[0],
  time: `${jst.format(new Date(e.createdAt * 1000)).replace(' ', 'T')}+09:00`,
  user: e.screenName,
  name: e.name,
  text: clean(e.displayText),
  links: (e.urls ?? []).map(u => u.expandedUrl),
  media: (e.media ?? []).map(m => m.item?.mediaUrl).filter(Boolean),
  replies: e.replyCount,
  reposts: e.rtCount,
  quotes: e.qtCount,
  likes: e.likesCount,
  inReplyTo: e.inReplyTo || null,
});

try {
  await send('Page.enable');
  const loaded = nextEvent('Page.loadEventFired', 30000);
  const navigation = await send('Page.navigate', { url: searchUrl });
  if (navigation.result?.errorText) throw new Error(`Navigation failed: ${navigation.result.errorText}`);
  await loaded;
  const evaluation = await send('Runtime.evaluate', {
    expression: `(${collect})(${pages}, ${sort === 'popular'})`,
    awaitPromise: true,
    returnByValue: true,
  });
  if (evaluation.result?.exceptionDetails) throw new Error(`Page script failed: ${evaluation.result.exceptionDetails.exception?.description ?? 'unknown error'}`);
  const r = evaluation.result.result.value;
  if (r.blocked) {
    console.error(`No search data on the page. Title: ${r.title}. URL: ${r.url}`);
    process.exitCode = 1;
  } else {
    const seen = new Set();
    const posts = r.entries.filter(e => !seen.has(e.id) && seen.add(e.id)).map(simplify);
    console.log(JSON.stringify({
      query,
      sort,
      searchUrl,
      totalResultsAvailable: r.total,
      returned: posts.length,
      searchError: r.error,
      paginationError: r.failed,
      bestPost: r.best ? simplify(r.best) : null,
      posts,
    }, null, 1));
  }
} finally {
  ws.close();
}

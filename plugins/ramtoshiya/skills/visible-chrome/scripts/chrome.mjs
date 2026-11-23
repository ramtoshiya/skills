#!/usr/bin/env node
import { mkdir, readFile, rm } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

const [action, name, placement] = process.argv.slice(2);
if (!['open', 'close'].includes(action) || !name || !/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(name) || (action === 'open' ? !['front', 'corner'].includes(placement) : placement !== undefined)) {
  console.error('Usage: chrome.mjs open PROFILE front|corner | close PROFILE');
  process.exit(2);
}
const profile = join(homedir(), '.local/share/agent-chrome', name);
const portFile = join(profile, 'DevToolsActivePort');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function endpoint() {
  try {
    const port = Number((await readFile(portFile, 'utf8')).split('\n')[0]);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
    const url = `http://127.0.0.1:${port}`;
    const response = await fetch(`${url}/json/version`, { signal: AbortSignal.timeout(2000) });
    return response.ok ? url : null;
  } catch { return null; }
}
async function cdp(url, commands) {
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  let id = 0;
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const request = ++id;
    const listener = event => {
      const message = JSON.parse(event.data);
      if (message.id !== request) return;
      socket.removeEventListener('message', listener);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    };
    socket.addEventListener('message', listener);
    socket.addEventListener('close', () => reject(new Error('Chrome closed the CDP connection')), { once: true });
    socket.send(JSON.stringify({ id: request, method, params }));
  });
  try { return await commands(send); } finally { socket.close(); }
}
let url = await endpoint();
if (action === 'close') {
  if (url) {
    const version = await (await fetch(`${url}/json/version`)).json();
    await cdp(version.webSocketDebuggerUrl, async send => { await send('Browser.close').catch(() => {}); });
    for (let i = 0; i < 50 && await endpoint(); i++) await sleep(200);
    if (await endpoint()) throw new Error('Chrome did not close');
  }
} else {
  if (!url) {
    await mkdir(profile, { recursive: true });
    await rm(portFile, { force: true });
    const app = process.env.CHROME_APP || '/Applications/Google Chrome.app';
    const args = [...(placement === 'corner' ? ['-g'] : []), '-n', '-a', app, '--args', `--user-data-dir=${profile}`, '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check', '--mute-audio', '--disable-blink-features=AutomationControlled', '--test-type', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--window-size=1100,800', 'about:blank'];
    const opened = spawnSync('open', args, { encoding: 'utf8' });
    if (opened.status !== 0) throw new Error(`open failed: ${opened.stderr}`);
    for (let i = 0; i < 150 && !url; i++) { await sleep(100); url = await endpoint(); }
    if (!url) throw new Error('Chrome did not open a DevTools port within 15 seconds');
  }
  const targets = await (await fetch(`${url}/json/list`)).json();
  const page = targets.find(target => target.type === 'page');
  if (!page) throw new Error('Chrome opened no page');
  await cdp(page.webSocketDebuggerUrl, async send => {
    const { windowId } = await send('Browser.getWindowForTarget', { targetId: page.id });
    const { bounds } = await send('Browser.getWindowBounds', { windowId });
    await send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'normal' } });
    if (bounds.windowState === 'minimized') await sleep(500);
    await send('Browser.setWindowBounds', { windowId, bounds: placement === 'corner' ? { left: 100000, top: 100000 } : { left: 80, top: 60, width: 1100, height: 800 } });
    if (placement === 'front') await send('Page.bringToFront');
  });
  console.log(url);
}

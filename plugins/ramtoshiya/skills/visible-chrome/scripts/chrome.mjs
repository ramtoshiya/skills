#!/usr/bin/env node
import { mkdir, readFile, rm } from 'node:fs/promises';
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const [action, name, placement] = process.argv.slice(2);
if (!['open', 'close'].includes(action) || !name || !/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(name) || (action === 'open' ? !['front', 'corner'].includes(placement) : placement !== undefined)) {
  console.error('Usage: chrome.mjs open PROFILE front|corner | close PROFILE');
  process.exit(2);
}
const profile = join(homedir(), '.local/share/agent-chrome', name);
const portFile = join(profile, 'DevToolsActivePort');
const displayMarker = join(profile, 'virtual-display');
const displayName = `agent-chrome-${name}`;
const displayScript = join(dirname(fileURLToPath(import.meta.url)), 'display.swift');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function activateChrome(url) {
  const port = new URL(url).port;
  const process = spawnSync('/usr/sbin/lsof', ['-n', '-P', '-t', `-iTCP:${port}`, '-sTCP:LISTEN'], { encoding: 'utf8' });
  const pid = Number(process.stdout.trim());
  if (process.status !== 0 || !Number.isInteger(pid) || pid <= 0) throw new Error('Cannot find the Chrome process for the DevTools port');
  const result = spawnSync('/usr/bin/osascript', ['-l', 'JavaScript', '-e', `ObjC.import('AppKit'); $.NSRunningApplication.runningApplicationWithProcessIdentifier(${pid}).activateWithOptions(0)`], { encoding: 'utf8' });
  if (result.status !== 0 || result.stdout.trim() !== 'true') throw new Error(`Cannot activate Chrome: ${result.stderr}`);
}
function betterDisplay(...args) {
  let result = spawnSync('betterdisplaycli', args, { encoding: 'utf8', timeout: 10000 });
  if (result.error?.code === 'ENOENT') {
    const binary = ['/opt/homebrew/bin/betterdisplaycli', '/usr/local/bin/betterdisplaycli'].find(existsSync);
    if (binary) result = spawnSync(binary, args, { encoding: 'utf8', timeout: 10000 });
  }
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(result.stderr || result.stdout || 'BetterDisplay failed');
  return result.stdout.trim();
}
function findDisplay() {
  try {
    const display = JSON.parse(betterDisplay('get', `-name=${displayName}`, '-type=VirtualScreen', '-identifiers'));
    if (display.deviceType !== 'VirtualScreen' || display.name !== displayName || !/^\d+$/.test(display.tagID)) throw new Error('Unexpected display identifier');
    return display;
  } catch (error) {
    if (error.message.trim() === 'Failed.') return null;
    throw error;
  }
}
function discardDisplay() {
  let display;
  try { display = findDisplay(); }
  catch (error) {
    if (error.code === 'ENOENT' && !existsSync(displayMarker)) return;
    throw error;
  }
  if (display) betterDisplay('discard', `-tagID=${display.tagID}`);
  rmSync(displayMarker, { force: true });
}
function displayGeometry(argument) {
  const result = spawnSync('swift', [displayScript, argument], { encoding: 'utf8', timeout: 20000 });
  if (result.error || result.status !== 0) throw new Error(result.error?.message || result.stderr || 'Cannot arrange virtual display');
  return result.stdout;
}
async function prepareDisplay() {
  let display = findDisplay();
  if (!display || !display.displayID || display.displayID === '0') displayGeometry('check');
  mkdirSync(profile, { recursive: true });
  writeFileSync(displayMarker, displayName);
  if (!display) {
    betterDisplay('create', '-type=VirtualScreen', `-virtualScreenName=${displayName}`, '-useResolutionList=on', '-resolutionList=1200x900', '-virtualScreenHiDPI=off');
    display = findDisplay();
    if (!display) throw new Error('Virtual display was not created');
  }
  if (!display.displayID || display.displayID === '0') betterDisplay('set', `-tagID=${display.tagID}`, '-connected=on');
  for (let i = 0; i < 50; i++) {
    display = findDisplay();
    if (display && /^\d+$/.test(display.displayID) && display.displayID !== '0') break;
    await sleep(100);
  }
  if (!display || display.displayID === '0') throw new Error('Virtual display did not connect');
  return JSON.parse(displayGeometry(display.displayID));
}
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
  try { discardDisplay(); } catch (error) { console.error(`Virtual display cleanup failed: ${error.message}`); process.exitCode = 1; }
} else {
  let position = null;
  let cleanupFailed = false;
  if (!url) {
    try { discardDisplay(); } catch (error) { cleanupFailed = true; console.error(`Virtual display cleanup unavailable: ${error.message}`); }
  }
  if (placement === 'corner' && !cleanupFailed) {
    try { position = await prepareDisplay(); }
    catch (error) {
      console.error(`Virtual display unavailable, using corner placement: ${error.message}`);
      try { discardDisplay(); } catch (cleanupError) { console.error(`Virtual display cleanup failed: ${cleanupError.message}`); }
    }
  }
  try {
    if (!url) {
      await mkdir(profile, { recursive: true });
      await rm(portFile, { force: true });
      const app = process.env.CHROME_APP || '/Applications/Google Chrome.app';
      const args = [...(placement === 'corner' ? ['-g'] : []), '-n', '-a', app, '--args', `--user-data-dir=${profile}`, '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check', '--mute-audio', '--disable-blink-features=AutomationControlled', '--test-type', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--window-size=1100,800', ...(position ? [`--window-position=${position.left},${position.top}`] : []), ...(placement === 'corner' ? ['--no-startup-window'] : ['about:blank'])];
      const opened = spawnSync('open', args, { encoding: 'utf8' });
      if (opened.status !== 0) throw new Error(`open failed: ${opened.stderr}`);
      for (let i = 0; i < 150 && !url; i++) { await sleep(100); url = await endpoint(); }
      if (!url) throw new Error('Chrome did not open a DevTools port within 15 seconds');
    }
    const version = await (await fetch(`${url}/json/version`)).json();
    let targets = await (await fetch(`${url}/json/list`)).json();
    if (placement === 'corner' && !targets.some(target => target.type === 'page')) {
      await cdp(version.webSocketDebuggerUrl, send => send('Target.createTarget', { url: 'about:blank', newWindow: true, background: true, ...(position || { left: 100000, top: 100000 }), width: 1100, height: 800 }));
      targets = await (await fetch(`${url}/json/list`)).json();
    }
    const page = targets.find(target => target.type === 'page');
    if (!page) throw new Error('Chrome opened no page');
    await cdp(page.webSocketDebuggerUrl, async send => {
      const { windowId } = await send('Browser.getWindowForTarget', { targetId: page.id });
      const { bounds } = await send('Browser.getWindowBounds', { windowId });
      if (bounds.windowState !== 'normal') await send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'normal' } });
      if (bounds.windowState === 'minimized') await sleep(500);
      await send('Browser.setWindowBounds', { windowId, bounds: placement === 'corner' ? position ? { ...position, width: 1100, height: 800 } : { left: 100000, top: 100000 } : { left: 80, top: 60, width: 1100, height: 800 } });
      if (placement === 'front') await send('Page.bringToFront');
    });
    if (placement === 'front') {
      activateChrome(url);
      try { discardDisplay(); } catch (error) { console.error(`Virtual display cleanup unavailable: ${error.message}`); process.exitCode = 1; }
    }
    console.log(url);
  } catch (error) {
    if (position) try { discardDisplay(); } catch (cleanupError) { console.error(`Virtual display cleanup failed: ${cleanupError.message}`); }
    throw error;
  }
}

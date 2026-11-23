const [url, x, y, width, height] = process.argv.slice(2);
const screen = { left: Number(x), top: Number(y), width: Number(width), height: Number(height) };
if (!url || [x, y, width, height].some(value => value === undefined || !Number.isFinite(Number(value)))) {
  throw new Error('Usage: node window.mjs CDP_URL SCREEN_X SCREEN_Y SCREEN_WIDTH SCREEN_HEIGHT');
}
const page = (await (await fetch(`${url}/json/list`)).json()).find(target => target.type === 'page');
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let id = 0;
async function send(method, params = {}) {
  const request = ++id;
  return new Promise((resolve, reject) => {
    const listener = event => {
      const message = JSON.parse(event.data);
      if (message.id !== request) return;
      socket.removeEventListener('message', listener);
      if (message.error) reject(new Error(message.error.message));
      else resolve(message.result);
    };
    socket.addEventListener('message', listener);
    socket.send(JSON.stringify({ id: request, method, params }));
  });
}
try {
  const { windowId } = await send('Browser.getWindowForTarget', { targetId: page.id });
  const { bounds } = await send('Browser.getWindowBounds', { windowId });
  const { result } = await send('Runtime.evaluate', { expression: 'JSON.stringify({webdriver:navigator.webdriver, title:document.title})', returnByValue: true });
  const pageState = JSON.parse(result.value);
  const intersects = bounds.left < screen.left + screen.width && bounds.left + bounds.width > screen.left && bounds.top < screen.top + screen.height && bounds.top + bounds.height > screen.top;
  console.log(JSON.stringify({ bounds, screen, page: pageState, intersects }));
  if (intersects || pageState.webdriver !== false) process.exitCode = 1;
} finally { socket.close(); }

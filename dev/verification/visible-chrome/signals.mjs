const [url] = process.argv.slice(2);
const page = (await (await fetch(`${url}/json/list`)).json()).find(target => target.type === 'page');
if (!page) throw new Error('Chrome has no page');
const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
try {
  socket.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: {
    expression: `new Promise(resolve => {
      let frames = 0, ticks = 0;
      const frame = () => { frames++; requestAnimationFrame(frame); };
      requestAnimationFrame(frame);
      const timer = setInterval(() => ticks++, 100);
      setTimeout(() => { clearInterval(timer); resolve({visibility: document.visibilityState, focus: document.hasFocus(), webdriver: navigator.webdriver, frames, ticks}); }, 1500);
    })`,
    awaitPromise: true,
    returnByValue: true,
  }}));
  const message = await new Promise((resolve, reject) => {
    socket.onmessage = event => resolve(JSON.parse(event.data));
    socket.onerror = reject;
  });
  if (message.error || message.result.exceptionDetails) throw new Error(JSON.stringify(message));
  const state = message.result.result.value;
  console.log(JSON.stringify(state));
  if (state.visibility !== 'visible' || state.webdriver !== false || state.frames < 2 || state.ticks < 2) process.exitCode = 1;
} finally { socket.close(); }

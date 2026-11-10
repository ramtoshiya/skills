import { setTimeout as sleep } from "node:timers/promises";

// Retry reads and content-addressed file uploads, never ambiguous scene writes.
export async function request(url, { timeout = 15000, ...options } = {}, { onRetry } = {}) {
  const deadline = performance.now() + 60000;
  for (let attempt = 0; attempt < 4; attempt++) {
    let response, failure;
    try {
      response = await fetch(url, { ...options, signal: AbortSignal.timeout(Math.max(1, Math.ceil(Math.min(timeout, deadline - performance.now())))) });
    } catch (error) { failure = error; }
    const retryable = failure || [408, 429, 500, 502, 503, 504].includes(response.status);
    if (!retryable) return response;
    if (attempt === 3) {
      if (failure) throw new Error("Network request failed after 4 attempts");
      return response;
    }
    const retryAfter = response?.headers.get("Retry-After");
    let delay = 250 * 2 ** attempt + Math.random() * 100;
    if (retryAfter !== null && retryAfter !== undefined) {
      const seconds = Number(retryAfter);
      const requested = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(retryAfter) - Date.now();
      if (Number.isFinite(requested)) delay = Math.max(delay, requested);
    }
    await response?.body?.cancel();
    if (delay > 10000 || performance.now() + delay >= deadline) throw new Error("Service retry delay exceeds the request budget. Retry later.");
    onRetry?.();
    await sleep(delay);
  }
}

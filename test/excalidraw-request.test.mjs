import assert from "node:assert/strict";
import { test } from "node:test";
import { request } from "../cli/excalidraw-board/request.mjs";

test("safe requests retry throttling and transient failures with a fixed attempt bound", async t => {
  const statuses = [429, 503, 200];
  let retries = 0;
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: statuses.shift(), headers: { "Retry-After": "0" } }));
  const response = await request("https://example.test/file", {}, { onRetry: () => { retries++; } });
  assert.equal(response.status, 200);
  assert.equal(retries, 2);
  assert.equal(statuses.length, 0);
  let attempts = 0;
  t.mock.method(globalThis, "fetch", async () => { attempts++; throw new TypeError("network disconnected"); });
  await assert.rejects(request("https://example.test/file"), /failed after 4 attempts/);
  assert.equal(attempts, 4);
});

test("safe requests do not retry permanent failures or shorten long Retry-After instructions", async t => {
  for (const status of [400, 401, 403, 404]) {
    let attempts = 0;
    t.mock.method(globalThis, "fetch", async () => { attempts++; return new Response(null, { status }); });
    assert.equal((await request("https://example.test/file")).status, status);
    assert.equal(attempts, 1);
  }
  for (const retryAfter of ["120", new Date(Date.now() + 120000).toUTCString()]) {
    let attempts = 0;
    t.mock.method(globalThis, "fetch", async () => { attempts++; return new Response(null, { status: 429, headers: { "Retry-After": retryAfter } }); });
    await assert.rejects(request("https://example.test/file"), /Retry later/);
    assert.equal(attempts, 1);
  }
});

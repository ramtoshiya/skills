import assert from "node:assert/strict";
import { test } from "node:test";
import { ENGLISH_INSTRUCTION, SERVICE_ID, completeWithRetry, registerAppleTitles } from "../service.js";

const ok = (text) => ({ ok: true, text });
const fail = (code, message = `${code} failed`) => ({ ok: false, code, message });

function scripted(...results) {
  const prompts = [];
  const call = async (prompt) => {
    prompts.push(prompt);
    return results[prompts.length - 1];
  };
  return { call, prompts };
}

test("appends the English instruction to a Korean prompt", async () => {
  const { call, prompts } = scripted(ok("Fix login"));
  const text = await completeWithRetry(call, "로그인 버그를 고쳐줘", new AbortController().signal);
  assert.equal(text, "Fix login");
  assert.equal(prompts[0], `로그인 버그를 고쳐줘${ENGLISH_INSTRUCTION}`);
});

for (const code of ["guardrail", "generation"]) {
  test(`retries once after a ${code} failure`, async () => {
    const { call, prompts } = scripted(fail(code), ok("Second try"));
    assert.equal(await completeWithRetry(call, "p", new AbortController().signal), "Second try");
    assert.equal(prompts.length, 2);
  });
}

test("rejects with the helper's message after two failures", async () => {
  const { call, prompts } = scripted(fail("guardrail", "unsafe"), fail("guardrail", "still unsafe"));
  await assert.rejects(completeWithRetry(call, "p", new AbortController().signal), /still unsafe/);
  assert.equal(prompts.length, 2);
});

for (const code of ["unavailable", "error"]) {
  test(`does not retry a ${code} failure`, async () => {
    const { call, prompts } = scripted(fail(code, "nope"), ok("unused"));
    await assert.rejects(completeWithRetry(call, "p", new AbortController().signal), /nope/);
    assert.equal(prompts.length, 1);
  });
}

test("does not retry once bb has aborted the request", async () => {
  const controller = new AbortController();
  const prompts = [];
  const call = async (prompt) => {
    prompts.push(prompt);
    controller.abort();
    return fail("guardrail");
  };
  await assert.rejects(completeWithRetry(call, "p", controller.signal));
  assert.equal(prompts.length, 1);
});

test("registers one service whose complete and status reach the backend", async () => {
  const registered = [];
  const bb = { experimental_aiServices: { register: (service) => registered.push(service) } };
  const status = async () => ({ ready: false, message: "Apple Intelligence is turned off" });
  registerAppleTitles(bb, { complete: async () => ok("A title"), status });

  assert.equal(registered.length, 1);
  assert.equal(registered[0].id, SERVICE_ID);
  assert.equal(await registered[0].complete("prompt", { signal: new AbortController().signal }), "A title");
  assert.deepEqual(await registered[0].status(), { ready: false, message: "Apple Intelligence is turned off" });
});

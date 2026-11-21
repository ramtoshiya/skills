// Apple on-device model as a bb AI service. `call` is the one place that reaches a model backend.

export const SERVICE_ID = "apple-foundation-models";

export const ENGLISH_INSTRUCTION =
  "\n\nWrite the answer in English, even when the text above is in another language.";

const RETRYABLE = new Set(["guardrail", "generation"]);

export async function completeWithRetry(call, prompt, signal) {
  const request = prompt + ENGLISH_INSTRUCTION;
  let result = await call(request, signal);
  if (!result.ok && RETRYABLE.has(result.code) && !signal.aborted) {
    result = await call(request, signal);
  }
  if (!result.ok) throw new Error(result.message);
  return result.text;
}

/**
 * @param bb plugin API
 * @param backend `{ complete(prompt, signal): Promise<result>, status(): Promise<{ready, message?}> }`
 */
export function registerAppleTitles(bb, backend) {
  bb.experimental_aiServices.register({
    id: SERVICE_ID,
    displayName: "Apple on-device model",
    complete: (prompt, { signal }) => completeWithRetry(backend.complete, prompt, signal),
    status: backend.status,
  });
}

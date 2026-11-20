import type { BbPluginApi } from "@get-bb/plugin-sdk";
import { decide, eligible } from "./decision";

export default function plugin(bb: BbPluginApi) {
  bb.experimental_hooks.on("message.dispatch", async (ctx) => {
    if (!eligible(ctx)) return { action: "proceed" };
    try {
      const signal = AbortSignal.timeout(3000);
      const result = await Promise.race([
        bb.sdk.providers.models({ providerId: ctx.requestedExecution.providerId, preferCached: true, signal }),
        new Promise<never>((_, reject) => signal.addEventListener("abort", () => reject(signal.reason), { once: true })),
      ]);
      return decide(ctx, result.models.map(({ id }) => id));
    } catch (error) {
      bb.log.warn(`Could not check model catalog: ${String(error)}`);
      return { action: "proceed" };
    }
  });
}

import type { BbPluginApi } from "@get-bb/plugin-sdk";
import { rpcContract, threadTag, type CatalogModel } from "./contract";

const READ_CONCURRENCY = 8;

export default function plugin(bb: BbPluginApi) {
  const lastServedModel = new Map<string, string | null | undefined>();
  const rerunRequested = new Map<string, boolean>();

  async function resolveModel(
    threadId: string,
    signal?: AbortSignal,
  ): Promise<string | null> {
    try {
      const options = await bb.sdk.threads.defaultExecutionOptions({
        threadId,
        signal,
      });
      return options?.model ?? null;
    } catch (error) {
      if (signal?.aborted) throw error;
      bb.log.warn(`could not resolve the model of ${threadId}: ${String(error)}`);
      return null;
    }
  }

  async function readCatalog(
    providerId: string,
    signal: AbortSignal,
  ): Promise<CatalogModel[]> {
    try {
      const { models } = await bb.sdk.providers.models({
        providerId,
        preferCached: true,
        signal,
      });
      return models.flatMap(({ id, model, displayName }) =>
        id === model
          ? [{ model, displayName }]
          : [
              { model, displayName },
              { model: id, displayName },
            ],
      );
    } catch (error) {
      if (signal.aborted) throw error;
      bb.log.warn(`could not read the models of ${providerId}: ${String(error)}`);
      return [];
    }
  }

  async function refresh(threadId: string): Promise<void> {
    if (!lastServedModel.has(threadId)) return;
    if (rerunRequested.has(threadId)) {
      rerunRequested.set(threadId, true);
      return;
    }
    try {
      do {
        rerunRequested.set(threadId, false);
        const model = await resolveModel(threadId);
        if (!lastServedModel.has(threadId)) return;
        if (lastServedModel.get(threadId) !== model) {
          lastServedModel.set(threadId, model);
          bb.rpc.experimental_invalidate([threadTag(threadId)]);
        }
      } while (rerunRequested.get(threadId));
    } finally {
      rerunRequested.delete(threadId);
    }
  }

  bb.rpc.register(rpcContract, {
    async threadModels({ keys }, { experimental_signal: signal }) {
      const models = await mapWithConcurrency(keys, READ_CONCURRENCY, (id) =>
        resolveModel(id, signal),
      );
      const result: Record<string, string | null> = {};
      keys.forEach((threadId, index) => {
        const model = models[index] ?? null;
        result[threadId] = model;
        if (lastServedModel.has(threadId)) lastServedModel.set(threadId, model);
      });
      return result;
    },
    async providerModels({ keys }, { experimental_signal: signal }) {
      const catalogs = await Promise.all(
        keys.map((providerId) => readCatalog(providerId, signal)),
      );
      return Object.fromEntries(
        keys.map((providerId, index) => [providerId, catalogs[index] ?? []]),
      );
    },
  });

  bb.rpc.experimental_whileWatched("threadModels", (read, signal) => {
    if (!("key" in read)) return;
    const threadId = read.key;
    lastServedModel.set(threadId, undefined);
    signal.addEventListener("abort", () => lastServedModel.delete(threadId), {
      once: true,
    });
  });

  bb.events.on("experimental_thread.events", ({ thread }) => refresh(thread.id));
}

async function mapWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  map: (item: T) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const index = next++;
      results[index] = await map(items[index]!);
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, worker),
  );
  return results;
}

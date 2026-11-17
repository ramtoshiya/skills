import { useCallback, useEffect, useRef, useState } from "react";
import {
  definePluginApp,
  experimental_THREAD_ACTION_GROUPS,
  useRpc,
  useSdk,
} from "@get-bb/plugin-sdk/app";
import { toast } from "sonner";
import { indexDrafts } from "./drafts.ts";
import type { DraftTarget, rpcContract } from "./server.ts";

function useDraftActions({ threadIds }: { threadIds: readonly string[] }) {
  const sdk = useSdk();
  const rpc = useRpc<typeof rpcContract>();
  const [drafts, setDrafts] = useState<ReadonlyMap<string, DraftTarget>>(new Map());
  const [sending, setSending] = useState<ReadonlySet<string>>(new Set());
  const pending = useRef(new Set<string>());
  const [revision, setRevision] = useState(0);
  const visible = threadIds.length > 0;
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    if (!visible) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = setTimeout(refresh, 100);
    };
    const unsubscribeThreads = sdk.subscribe({
      event: "thread:changed",
      callback: (event) => {
        if (event.changes.some((change) => ["queue-changed", "thread-created", "thread-deleted"].includes(change))) schedule();
      },
    });
    const unsubscribeConnection = sdk.subscribe({
      event: "realtime:connection",
      callback: (event) => {
        if (event.state === "connected") schedule();
      },
    });
    return () => {
      if (timer !== undefined) clearTimeout(timer);
      unsubscribeThreads();
      unsubscribeConnection();
    };
  }, [sdk, visible, refresh]);

  useEffect(() => {
    if (!visible) {
      setDrafts(new Map());
      return;
    }
    const controller = new AbortController();
    sdk.threads.queue.list({ signal: controller.signal }).then(
      (messages) => {
        if (!controller.signal.aborted) setDrafts(indexDrafts(messages));
      },
      (cause: unknown) => {
        if (!controller.signal.aborted) {
          setDrafts(new Map());
          toast.error("Could not load held drafts", { description: cause instanceof Error ? cause.message : String(cause) });
        }
      },
    );
    return () => controller.abort();
  }, [sdk, visible, revision]);

  const run = async (target: DraftTarget) => {
    if (pending.current.has(target.threadId)) return;
    pending.current.add(target.threadId);
    setSending(new Set(pending.current));
    try {
      const result = await rpc.call("runDraft", target);
      if (result.kind === "sent") toast.success("Draft sent");
      else toast.info("Draft approved, still waiting", { description: result.reason });
    } catch (cause) {
      toast.error("Could not send draft", { description: cause instanceof Error ? cause.message : String(cause) });
    } finally {
      pending.current.delete(target.threadId);
      setSending(new Set(pending.current));
      refresh();
    }
  };

  return { drafts, sending, run };
}

export default definePluginApp((app) => {
  app.slots.experimental_threadAction({
    id: "run-draft",
    title: "Run draft",
    icon: "Play",
    group: experimental_THREAD_ACTION_GROUPS.open,
    order: 5,
    useData: useDraftActions,
    item: ({ thread, data }) => {
      const target = data.drafts.get(thread.id);
      if (thread.status !== "pending" || thread.archivedAt !== null || target === undefined) return null;
      const sending = data.sending.has(thread.id);
      return {
        label: sending ? "Sending draft…" : "Run draft",
        icon: "Play",
        disabled: sending,
        run: () => data.run(target),
      };
    },
  });
});

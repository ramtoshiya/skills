import { createElement as h, useCallback, useEffect, useState } from "react";
import { definePluginApp, experimental_THREAD_ACTION_GROUPS, useRpc, useSdk } from "@get-bb/plugin-sdk/app";
import { toast } from "sonner";
import { isClaudeCodeProvider } from "./providers.ts";
import type { rpcContract } from "./server.ts";
import { describeResult } from "./result.ts";

const TITLE = "Move running tool to background";

function useMove() {
  const rpc = useRpc<typeof rpcContract>();
  return useCallback(async (threadId: string) => {
    try {
      const result = await rpc.call("move", { threadId });
      const show = result.kind === "moved" ? toast.success : toast.info;
      show(describeResult(result));
    } catch (cause) {
      toast.error("Could not move the tool to the background", {
        description: cause instanceof Error ? cause.message : String(cause),
      });
    }
  }, [rpc]);
}

// A command runs outside React, so a mounted component lends it the RPC client.
let moveFromCommand: ((threadId: string) => Promise<void>) | null = null;

function CommandBridge() {
  const move = useMove();
  useEffect(() => {
    moveFromCommand = move;
    return () => { moveFromCommand = null; };
  }, [move]);
  return h("span", { hidden: true });
}

function useHeaderData({ threadIds }: { threadIds: readonly string[] }) {
  const sdk = useSdk();
  const move = useMove();
  const [supported, setSupported] = useState<ReadonlySet<string>>(new Set());
  const key = threadIds.join(",");

  useEffect(() => {
    let cancelled = false;
    Promise.all(key.split(",").filter(Boolean).map(async (threadId) => {
      const thread = await sdk.threads.get({ threadId });
      return isClaudeCodeProvider(thread.providerId) ? threadId : null;
    })).then(
      (ids) => { if (!cancelled) setSupported(new Set(ids.filter((id) => id !== null))); },
      (cause: unknown) => console.warn("background tools: could not read the thread's provider", cause),
    );
    return () => { cancelled = true; };
  }, [sdk, key]);

  return { supported, move };
}

export default definePluginApp((app) => {
  app.slots.experimental_appOverlay({ id: "command-bridge", component: CommandBridge });
  app.commands.register({
    id: "move",
    title: `Background tools: ${TITLE.toLowerCase()}`,
    defaultShortcut: { key: "b", mod: true, shift: true },
    isAvailable: ({ threadId }) => threadId !== null,
    run: ({ threadId }) => threadId === null ? undefined : moveFromCommand?.(threadId),
  });
  app.slots.experimental_threadAction<ReturnType<typeof useHeaderData>>({
    id: "move-header",
    title: TITLE,
    icon: "ArrowDownToLine",
    group: experimental_THREAD_ACTION_GROUPS.open,
    order: 7,
    placement: "header",
    useData: useHeaderData,
    item: ({ thread, data }) => data.supported.has(thread.id)
      ? {
          label: "Background",
          icon: "ArrowDownToLine",
          disabled: thread.status !== "active",
          run: () => data.move(thread.id),
        }
      : null,
  });
});

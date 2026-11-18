import { createElement as h, useCallback, useEffect, useId, useRef, useState, useSyncExternalStore, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import {
  definePluginApp,
  experimental_ProviderModelPicker,
  experimental_THREAD_ACTION_GROUPS,
  experimental_useProviders,
  useBbNavigate,
  useRpc,
  useSdk,
  type ExperimentalProviderModelPickerValue,
  type PluginThreadActionRegistration,
} from "@get-bb/plugin-sdk/app";
import { toast } from "sonner";
import { draftTarget, indexDrafts, type QueuedMessage } from "./drafts.ts";
import type { RunResult, rpcContract } from "./server.ts";

const describe = (cause: unknown) => cause instanceof Error ? cause.message : String(cause);

let chooser: QueuedMessage | null = null;
const chooserListeners = new Set<() => void>();
function setChooser(next: QueuedMessage | null) {
  chooser = next;
  for (const listener of chooserListeners) listener();
}
function subscribeChooser(listener: () => void) {
  chooserListeners.add(listener);
  return () => { chooserListeners.delete(listener); };
}

function useReportResult() {
  const navigate = useBbNavigate();
  return useCallback((result: RunResult, message: QueuedMessage) => {
    switch (result.kind) {
      case "choose":
        setChooser(message);
        return;
      case "sent":
        toast.success("Draft sent");
        return;
      case "queued":
        toast.info("Draft approved, still waiting", { description: result.reason });
        return;
      case "replaced":
        toast.success("Draft started on a new thread", { description: "The held draft was deleted." });
        navigate.toThread(result.threadId);
        return;
      case "replaced-draft-kept":
        toast.warning("Draft started on a new thread", {
          description: `The held draft could not be deleted: ${result.reason}. Delete it yourself.`,
        });
        navigate.toThread(result.threadId);
        return;
      default: {
        const exhaustive: never = result;
        return exhaustive;
      }
    }
  }, [navigate]);
}

function useDraftActions({ threadIds }: { threadIds: readonly string[] }) {
  const sdk = useSdk();
  const rpc = useRpc<typeof rpcContract>();
  const report = useReportResult();
  const [drafts, setDrafts] = useState<ReadonlyMap<string, QueuedMessage>>(new Map());
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
          toast.error("Could not load held drafts", { description: describe(cause) });
        }
      },
    );
    return () => controller.abort();
  }, [sdk, visible, revision]);

  const run = async (message: QueuedMessage) => {
    if (pending.current.has(message.threadId)) return;
    pending.current.add(message.threadId);
    setSending(new Set(pending.current));
    try {
      report(await rpc.call("runDraft", draftTarget(message)), message);
    } catch (cause) {
      toast.error("Could not send draft", { description: describe(cause) });
    } finally {
      pending.current.delete(message.threadId);
      setSending(new Set(pending.current));
      refresh();
    }
  };

  return { drafts, sending, run };
}

type DraftActions = ReturnType<typeof useDraftActions>;
type DraftAction = Omit<PluginThreadActionRegistration<DraftActions>, "id">;

const draftAction = (label: string, icon: string, order: number, choose: (data: DraftActions, message: QueuedMessage) => void) => ({
  title: label,
  icon,
  group: experimental_THREAD_ACTION_GROUPS.open,
  order,
  useData: useDraftActions,
  item: ({ thread, data }) => {
    const message = data.drafts.get(thread.id);
    if (thread.status !== "pending" || thread.archivedAt !== null || message === undefined) return null;
    const sending = data.sending.has(thread.id);
    return {
      label: sending ? "Sending draft…" : label,
      icon,
      disabled: sending,
      run: () => choose(data, message),
    };
  },
}) satisfies DraftAction;

const runDraft = draftAction("Run draft", "Play", 5, (data, message) => data.run(message));
const runDraftOn = draftAction("Run draft on…", "Bot", 6, (_, message) => setChooser(message));

const styles = {
  backdrop: {
    position: "fixed",
    inset: 0,
    zIndex: 50,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 16,
    background: "rgb(0 0 0 / 0.4)",
  },
  dialog: {
    width: "min(28rem, 100%)",
    maxHeight: "calc(100dvh - 32px)",
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 16,
    padding: 20,
    borderRadius: "var(--radius-lg, 12px)",
    border: "1px solid var(--border)",
    background: "var(--popover)",
    color: "var(--popover-foreground)",
    boxShadow: "0 16px 48px rgb(0 0 0 / 0.25)",
  },
  heading: { margin: 0, fontSize: 16, fontWeight: 600 },
  note: { margin: 0, fontSize: 14, lineHeight: 1.45, color: "var(--muted-foreground)" },
  buttons: { display: "flex", justifyContent: "flex-end", gap: 8 },
  button: {
    minHeight: 44,
    minWidth: 88,
    padding: "0 16px",
    borderRadius: "var(--radius-md, 8px)",
    border: "1px solid var(--border)",
    background: "transparent",
    color: "inherit",
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer",
    touchAction: "manipulation",
  },
  primary: {
    border: "1px solid var(--primary)",
    background: "var(--primary)",
    color: "var(--primary-foreground)",
  },
} satisfies Record<string, CSSProperties>;

function RunDraftOnDialog({ message }: { message: QueuedMessage }) {
  const rpc = useRpc<typeof rpcContract>();
  const report = useReportResult();
  const { providers } = experimental_useProviders();
  const titleId = useId();
  const [draftProviderId, setDraftProviderId] = useState<string | null>(null);
  const [value, setValue] = useState<ExperimentalProviderModelPickerValue | null>(null);
  const [running, setRunning] = useState(false);
  const close = useCallback(() => setChooser(null), []);

  useEffect(() => {
    let cancelled = false;
    rpc.call("chooserStart", draftTarget(message)).then(
      (start) => {
        if (cancelled) return;
        setDraftProviderId(start.providerId);
        setValue(start.execution);
      },
      (cause: unknown) => {
        if (cancelled) return;
        toast.error("Could not load the draft", { description: describe(cause) });
        close();
      },
    );
    return () => { cancelled = true; };
  }, [rpc, message, close]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented && !running) close();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [close, running]);

  const run = async () => {
    if (value === null || running) return;
    setRunning(true);
    try {
      report(await rpc.call("runDraft", { ...draftTarget(message), execution: value }), message);
      close();
    } catch (cause) {
      toast.error("Could not run draft", { description: describe(cause) });
      setRunning(false);
    }
  };

  const providerName = (id: string) => providers.find((provider) => provider.id === id)?.displayName ?? id;
  const moves = value !== null && draftProviderId !== null && value.providerId !== draftProviderId;

  return h("div", {
    style: styles.backdrop,
    onClick: (event: { target: unknown; currentTarget: unknown }) => {
      if (event.target === event.currentTarget && !running) close();
    },
  }, h("div", { role: "dialog", "aria-modal": true, "aria-labelledby": titleId, style: styles.dialog },
    h("h2", { id: titleId, style: styles.heading }, "Run draft on…"),
    value === null
      ? h("p", { style: styles.note }, "Loading the draft's model…")
      : h(experimental_ProviderModelPicker, { value, onChange: setValue, disabled: running }),
    value === null ? null : h("p", { style: styles.note }, moves
      ? `Starts a new ${providerName(value.providerId)} thread with this prompt, title, parent, project, and environment, then deletes this draft. The thread ID changes.`
      : "Sends this draft on its current thread with the chosen model."),
    h("div", { style: styles.buttons },
      h("button", { type: "button", style: styles.button, onClick: close, disabled: running }, "Cancel"),
      h("button", {
        type: "button",
        style: { ...styles.button, ...styles.primary },
        onClick: run,
        disabled: value === null || running,
      }, running ? "Running…" : "Run"),
    ),
  ));
}

function RunDraftOnOverlay() {
  const message = useSyncExternalStore(subscribeChooser, () => chooser);
  return message === null ? null : createPortal(h(RunDraftOnDialog, { key: message.id, message }), document.body);
}

export default definePluginApp((app) => {
  app.slots.experimental_threadAction({ id: "run-draft", ...runDraft });
  app.slots.experimental_threadAction({ id: "run-draft-header", placement: "header", ...runDraft });
  app.slots.experimental_threadAction({ id: "run-draft-on", ...runDraftOn });
  app.slots.experimental_threadAction({ id: "run-draft-on-header", placement: "header", ...runDraftOn });
  app.slots.experimental_appOverlay({ id: "run-draft-on", component: RunDraftOnOverlay });
});

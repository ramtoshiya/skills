import { useEffect, useMemo, useSyncExternalStore } from "react";
import {
  definePluginApp,
  experimental_useRpcKeyedQuery,
  experimental_useSidebarThreads,
} from "@get-bb/plugin-sdk/app";
import {
  rpcContract,
  withinProviderKeyLimit,
  withinThreadKeyLimit,
  type CatalogModel,
} from "./contract";
import { createLabelBridge, type LabelBridge } from "./label-bridge";
import { describeModel } from "./model-label";
import { mountModelLabels } from "./sidebar-dom";

const UNKNOWN_PROVIDER_CATALOG: CatalogModel[] = [];

export function buildLabels(
  rowIds: readonly string[],
  models: Readonly<Record<string, string | null>> | undefined,
  catalogs: Readonly<Record<string, CatalogModel[]>> | undefined,
  providerOf: ReadonlyMap<string, string>,
): Map<string, string> {
  const labels = new Map<string, string>();
  for (const threadId of rowIds) {
    const model = models?.[threadId];
    if (model === undefined) continue;
    const providerId = providerOf.get(threadId);
    const catalog =
      providerId === undefined ? UNKNOWN_PROVIDER_CATALOG : catalogs?.[providerId];
    const catalogStillLoading = catalog === undefined;
    if (catalogStillLoading) continue;
    const text = describeModel(model, catalog);
    if (text !== null) labels.set(threadId, text);
  }
  return labels;
}

function createLabelData(bridge: LabelBridge) {
  return function ModelLabelData() {
    const renderedRowIds = useSyncExternalStore(bridge.subscribeRowIds, bridge.getRowIds);
    const rowIds = useMemo(() => withinThreadKeyLimit(renderedRowIds), [renderedRowIds]);
    const { threads } = experimental_useSidebarThreads();
    const providerOf = useMemo(
      () => new Map(threads.map((thread) => [thread.id, thread.providerId])),
      [threads],
    );
    const providerIds = useMemo(
      () =>
        withinProviderKeyLimit(
          [...new Set(rowIds.flatMap((id) => providerOf.get(id) ?? []))].sort(),
        ),
      [rowIds, providerOf],
    );
    const models = experimental_useRpcKeyedQuery({
      contract: rpcContract,
      method: "threadModels",
      keys: rowIds,
      enabled: rowIds.length > 0,
    });
    const catalogs = experimental_useRpcKeyedQuery({
      contract: rpcContract,
      method: "providerModels",
      keys: providerIds,
      enabled: providerIds.length > 0,
    });

    useEffect(() => {
      bridge.setLabels(buildLabels(rowIds, models.data, catalogs.data, providerOf));
    }, [rowIds, models.data, catalogs.data, providerOf]);
    useEffect(() => () => bridge.setLabels(new Map()), []);
    return null;
  };
}

export default definePluginApp((app) => {
  const bridge = createLabelBridge();
  app.contentScripts.register({
    id: "model-labels",
    mount: ({ signal }) => mountModelLabels(document, bridge, signal),
  });
  app.slots.experimental_appOverlay({
    id: "model-label-data",
    component: createLabelData(bridge),
  });
});

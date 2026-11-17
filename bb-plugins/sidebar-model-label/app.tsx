import { useMemo } from "react";
import {
  definePluginApp,
  experimental_useRpcKeyedQuery,
  type ExperimentalThreadRowMetadataDataInput,
  type ExperimentalThreadRowMetadataProps,
} from "@get-bb/plugin-sdk/app";
import { rpcContract, type CatalogModel } from "./contract";
import { describeModel } from "./model-label";

interface ModelData {
  models: Record<string, string | null> | undefined;
  catalogs: Record<string, CatalogModel[]> | undefined;
}

function useModelData({
  threads,
}: ExperimentalThreadRowMetadataDataInput): ModelData {
  const threadIds = useMemo(() => threads.map((thread) => thread.id), [threads]);
  const providerIds = useMemo(
    () => [...new Set(threads.map((thread) => thread.providerId))],
    [threads],
  );
  const models = experimental_useRpcKeyedQuery({
    contract: rpcContract,
    method: "threadModels",
    keys: threadIds,
    enabled: threadIds.length > 0,
  });
  const catalogs = experimental_useRpcKeyedQuery({
    contract: rpcContract,
    method: "providerModels",
    keys: providerIds,
    enabled: providerIds.length > 0,
  });
  return useMemo(
    () => ({ models: models.data, catalogs: catalogs.data }),
    [models.data, catalogs.data],
  );
}

function ModelLabelItem({
  thread,
  data,
}: ExperimentalThreadRowMetadataProps<ModelData>) {
  const model = data.models?.[thread.id];
  const catalog = data.catalogs?.[thread.providerId];
  if (model === undefined || catalog === undefined) return null;
  const label = describeModel(model, catalog);
  if (label === null) return null;
  return (
    <span
      title={label.title}
      className="min-w-0 truncate text-xs leading-3.5 text-muted-foreground"
    >
      {label.text}
    </span>
  );
}

export default definePluginApp((app) => {
  app.slots.experimental_threadRowMetadata<ModelData>({
    id: "model",
    order: 0,
    useData: useModelData,
    component: ModelLabelItem,
  });
});

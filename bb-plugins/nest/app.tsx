import { useMemo } from "react";
import {
  definePluginApp,
  experimental_useRpcKeyedQuery,
  type ExperimentalThreadRowMetadataDataInput,
  type ExperimentalThreadRowMetadataProps,
} from "@get-bb/plugin-sdk/app";
import { MAX_THREAD_KEYS, rpcContract, type LogicalParent } from "./contract";

const PLUGIN_ID = "nest";

type Parents = Readonly<Record<string, LogicalParent>> | undefined;

function useLogicalParents({ threads }: ExperimentalThreadRowMetadataDataInput): Parents {
  const keys = useMemo(
    () => threads.filter((thread) => thread.originPluginId === PLUGIN_ID).map((thread) => thread.id).slice(0, MAX_THREAD_KEYS),
    [threads],
  );
  return experimental_useRpcKeyedQuery({ contract: rpcContract, method: "logicalParents", keys, enabled: keys.length > 0 }).data;
}

function LogicalParentBadge({ thread, data }: ExperimentalThreadRowMetadataProps<Parents>) {
  const parent = data?.[thread.id];
  if (!parent) return null;
  return (
    <span title={`Worker of ${parent.title} (${parent.id}), started past bb's thread depth limit`} style={{ whiteSpace: "nowrap" }}>
      ↳ {parent.title}
    </span>
  );
}

export default definePluginApp((app) => {
  app.slots.experimental_threadRowMetadata<Parents>({
    id: "logical-parent",
    order: 50,
    useData: useLogicalParents,
    component: LogicalParentBadge,
  });
});

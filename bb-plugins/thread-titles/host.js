import { experimental_defineHostEntry } from "@get-bb/plugin-sdk/host";
import { hostContract } from "./contract.js";
import { buildHelper, createHelperService } from "./helper.js";
import { SWIFT_SOURCE } from "./swift-source.js";

let service = null;

function helperService(context) {
  service ??= createHelperService({
    build: () => buildHelper({ source: SWIFT_SOURCE, directory: context.experimental_paths.dataDir }),
  });
  return service;
}

export default experimental_defineHostEntry({
  contract: hostContract,
  handlers: {
    "titles.status": async (_input, context) => helperService(context).status(),
    "titles.complete": async ({ prompt }, context) =>
      helperService(context).complete(prompt, context.signal),
  },
});

import { definePluginApp } from "@get-bb/plugin-sdk/app";
import { mountTildeStrikethrough } from "./strikethrough";

export default definePluginApp((app) => {
  app.contentScripts.register({
    id: "single-tilde",
    mount: ({ signal }) => mountTildeStrikethrough(document, signal),
  });
});

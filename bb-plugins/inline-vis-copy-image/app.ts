import { definePluginApp } from "@get-bb/plugin-sdk/app";
import { mountCopyImage } from "./copy-image";

export default definePluginApp((app) => {
  app.contentScripts.register({
    id: "copy-image",
    mount: ({ signal }) => mountCopyImage(document, signal),
  });
});

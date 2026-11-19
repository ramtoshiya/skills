// @vitest-environment jsdom
import { loadPluginApp, mountPluginContentScripts } from "@get-bb/plugin-sdk/testing/app";
import { cleanup, render } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const SINGLE = "data-tilde-strikethrough-single";

function HostMarkdown({ content, html }: { content: string; html: string }) {
  return createElement("div", {
    "data-markdown-preview": "",
    dangerouslySetInnerHTML: { __html: html },
  });
}

const RANGE_AND_STRUCK = {
  content: "v3~6 and then 8~10, but ~~removed~~",
  html: "<p>v3<del>6 and then 8</del>10, but <del>removed</del></p>",
};

const mounted: { dispose(): Promise<void> }[] = [];

afterEach(async () => {
  for (const scripts of mounted.splice(0)) await scripts.dispose();
  cleanup();
  document.body.innerHTML = "";
});

async function start() {
  const app = await loadPluginApp(() => import("./app"));
  const scripts = await mountPluginContentScripts(app, { pluginId: "tilde-strikethrough" });
  mounted.push(scripts.lifecycle);
  return scripts;
}

function singleTildeTexts(): string[] {
  return [...document.querySelectorAll(`del[${SINGLE}]`)].map((element) => element.textContent ?? "");
}

function allDeletedTexts(): string[] {
  return [...document.querySelectorAll("del")].map((element) => element.textContent ?? "");
}

describe("tilde strikethrough", () => {
  it("marks only the deletion that the message wrote with single tildes", async () => {
    render(createElement(HostMarkdown, RANGE_AND_STRUCK));

    await start();

    expect(singleTildeTexts()).toEqual(["6 and then 8"]);
    expect(allDeletedTexts()).toEqual(["6 and then 8", "removed"]);
  });

  it("marks a message that renders after the plugin started", async () => {
    await start();

    render(createElement(HostMarkdown, RANGE_AND_STRUCK));

    await vi.waitFor(() => expect(singleTildeTexts()).toEqual(["6 and then 8"]));
  });

  it("follows the message when its text changes", async () => {
    const view = render(createElement(HostMarkdown, RANGE_AND_STRUCK));
    await start();

    view.rerender(
      createElement(HostMarkdown, {
        content: "~~6 and then 8~~ and 1~2~3",
        html: "<p><del>6 and then 8</del> and 1<del>2</del>3</p>",
      }),
    );

    await vi.waitFor(() => expect(singleTildeTexts()).toEqual(["2"]));
  });

  it("keeps following the message through several changes", async () => {
    const view = render(createElement(HostMarkdown, { content: "", html: "" }));
    await start();

    for (const digit of ["1", "2", "3", "4", "5"]) {
      view.rerender(
        createElement(HostMarkdown, {
          content: `~~kept ${digit}~~ and a~${digit}~b`,
          html: `<p><del>kept ${digit}</del> and a<del>${digit}</del>b</p>`,
        }),
      );
      await vi.waitFor(() => expect(singleTildeTexts()).toEqual([digit]));
    }
  });

  it("pairs each Markdown root with its own source", async () => {
    render(
      createElement("div", null, [
        createElement(HostMarkdown, { key: "double", content: "~~same~~", html: "<del>same</del>" }),
        createElement(HostMarkdown, { key: "single", content: "~same~", html: "<del>same</del>" }),
      ]),
    );

    await start();

    const marks = [...document.querySelectorAll("del")].map((element) => element.hasAttribute(SINGLE));
    expect(marks).toEqual([false, true]);
  });

  it("leaves a deletion alone when its source cannot be read", async () => {
    document.body.innerHTML =
      "<div data-markdown-preview><del>unknown source</del></div><del>outside Markdown</del>";

    await start();

    expect(singleTildeTexts()).toEqual([]);
  });

  it("removes its marks and its style when bb disposes the content script", async () => {
    render(createElement(HostMarkdown, RANGE_AND_STRUCK));
    const styleCount = document.querySelectorAll("style").length;
    const scripts = await start();
    expect(singleTildeTexts()).toEqual(["6 and then 8"]);

    await scripts.lifecycle.dispose();

    expect(singleTildeTexts()).toEqual([]);
    expect(document.querySelectorAll("style")).toHaveLength(styleCount);
  });
});

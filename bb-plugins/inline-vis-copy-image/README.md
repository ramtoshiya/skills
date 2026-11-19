# inline-vis-copy-image

A [bb](https://getbb.app) plugin that makes bb Desktop's **Copy Image** menu
item work on an image inside an inline visualization. Without the plugin, the
menu item appears when you right-click such an image, but it copies nothing.

## Install

From this repository:

```sh
cd bb-plugins/inline-vis-copy-image
npm install
bb plugin install . --yes
```

The plugin needs no bb setting.

## What it covers

Right-click an image in an inline-vis HTML page in a chat message, then
choose **Copy Image**. bb copies the image at its original size.

| Case | Result |
| --- | --- |
| An `<img>` with an `http:`, `https:`, or `data:image/` source | Copied |
| A `<canvas>`, an inline `<svg>`, or a CSS background | Not covered. bb shows no **Copy Image** item for them |
| An `<img>` with a `blob:` source | Not covered. The app page cannot load a URL that the frame created |
| An inline-vis page opened in the side panel | Not covered |
| An image that the app page renders itself, such as one in a Markdown file shown inline | Not changed by the plugin |

The plugin adds a script to each inline-vis page before the page first
loads. A page that is already on screen when you enable or disable the plugin
loads again once, which resets what you typed or scrolled in it.

The app page loads the image again when you right-click it. If the image is
large or the connection is slow, wait a moment before you choose
**Copy Image**, because the item copies nothing until that load ends.

After you copy, the first click on the same point of the image closes the
plugin's invisible image and does not reach the page. Clicks anywhere else
work as before.

## How it works

bb Desktop's **Copy Image** asks the app page for the image at the pointer.
An inline-vis page lives in a sandboxed frame, so the app page finds the
frame there and no image.

The plugin's content script appends a small script to each inline-vis frame's
`srcdoc`. When you right-click an image, that script sends the image's URL
and the pointer position to the app page. The content script then places a
transparent 16 pixel `<img>` with the same URL in the app page, exactly under
the pointer. **Copy Image** now finds that image and copies it. The next
pointer press removes it.

The content script accepts a message only from a frame it added the script
to. It accepts only `http:`, `https:`, and `data:image/` URLs and a position
inside the frame, and it loads the image without a referrer. Disabling the
plugin removes the added script and the image.

## Risks

- `[data-inline-vis-frame] iframe[srcdoc]` is private markup of bb's bundled
  inline-vis plugin. If a bb release changes it, **Copy Image** copies
  nothing again and the page is otherwise unchanged. The selector is in
  [`copy-image.ts`](copy-image.ts).
- The plugin depends on how bb Desktop implements **Copy Image**, which is a
  hit test in the app page at the pointer. A bb release that copies the image
  another way can make the plugin unnecessary or ineffective.
- The app page requests the image again. An image that the server sends only
  once cannot be copied.

## Development

```sh
npm test            # Vitest with the plugin SDK's frontend harness
npm run typecheck
bb plugin build .   # writes dist/, which is ignored by Git
```

`npm run verify:live` checks the plugin in the real bb page with headless
Chromium. It needs `BB_SERVER_URL`, and `BB_VERIFY_CHROMIUM` set to an
existing Chromium, because it never downloads one. Pass the id of a thread
whose recent messages show an inline-vis HTML page that contains an `<img>`:

```sh
npm run verify:live -- thr_example
```

The check right-clicks the image and confirms that the app page's hit test at
that point finds a decoded copy of the image. It then confirms that the copy
leaves on the next press and that disabling the plugin restores every frame.
It enables the plugin again when it ends. It does not read or write the
clipboard, so confirm the copy itself in bb Desktop.

Tested with bb 0.49 and plugin SDK 0.6.132.

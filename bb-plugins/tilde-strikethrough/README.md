# tilde-strikethrough

A [bb](https://getbb.app) plugin that strikes through chat text only between
double tildes. bb also strikes through text between two single tildes, so a
message such as `v3~6 and then 8~10` loses its tildes and shows
"6 and then 8" struck through. With the plugin, that message reads as it was
written.

## Install

From this repository:

```sh
cd bb-plugins/tilde-strikethrough
npm install
bb plugin install . --yes
```

The plugin needs no bb setting.

## What changes

| You write | bb alone shows | With the plugin |
| --- | --- | --- |
| `v3~6 and then 8~10` | v3<del>6 and then 8</del>10 | v3~6 and then 8~10 |
| `~~removed~~` | <del>removed</del> | <del>removed</del> |

The plugin applies to every Markdown block that bb renders in the app page.
That includes a reply while it streams and a Markdown file shown inline in a
message. It does not change a message's stored text.

The plugin leaves a struck span as bb drew it in these cases:

- The message wrote the span as a raw `<del>` HTML tag. One exception exists.
  If a single-tilde span with the same text follows the tag in the same
  message, the plugin can pair the two, so the tag's text loses its line and
  the single-tilde span keeps it.
- The span's text differs from the message source, for example because the
  span contains an image or a mention that bb rewrote.

The restored tildes are drawn by CSS. A text selection that you copy from the
page does not include them, and the browser's find does not match them.

## How it works

bb parses chat Markdown with single-tilde strikethrough enabled and has no
setting for it. Both `~text~` and `~~text~~` become the same `<del>` element,
so the page alone cannot tell them apart.

The plugin's content script reads the Markdown source of each rendered block
from the properties of the bb component that rendered it. It parses that
source with the same GitHub Flavored Markdown rules and notes whether each
struck span opened with one tilde or two. It then pairs the spans with the
block's `<del>` elements by order and text. A `<del>` that pairs with a
single-tilde span gets the `data-tilde-strikethrough-single` attribute, and a
style rule removes its line and draws a tilde on each side. Disabling the
plugin removes the attributes and the style rule.

## Risks

- The plugin reads private state of bb's page. It finds a Markdown block by
  the `data-markdown-preview` attribute. It reads the source from React's
  internal fields on that element and from the `content` property of bb's
  Markdown component. If a bb or React release changes any of them, single
  tildes strike through again and nothing else changes. Every such
  assumption is in [`markdown-source.ts`](markdown-source.ts).
- The plugin parses with its own pinned Markdown packages. If bb changes its
  parser, a span that the two parsers read differently keeps bb's rendering.

## Development

```sh
npm test            # Vitest with the plugin SDK's frontend harness
npm run typecheck
bb plugin build .   # writes dist/, which is ignored by Git
```

`npm run verify:live` checks the plugin in the real bb page with headless
Chromium. It needs `BB_SERVER_URL`, and `BB_VERIFY_CHROMIUM` set to an
existing Chromium, because it never downloads one. Send this message in a
thread, then pass the thread's id:

```text
Range: v3~6 and then 8~10 stay plain.

Struck: ~~removed text~~ stays struck.
```

```sh
npm run verify:live -- thr_example
```

The check disables the plugin and confirms that bb strikes through both
spans. It then enables the plugin and confirms that the range shows its
tildes without a line while the double-tilde span stays struck. It ends with
the plugin enabled.

Tested with bb 0.49 and plugin SDK 0.6.132.

# sidebar-model-label

A [bb](https://getbb.app) plugin that shows the model each thread uses as
small muted text right after the thread's title in the sidebar. You can tell
an Opus thread from a GPT thread without opening it. Rows keep their height,
indentation, click target, hover actions, and sticky positions.

## Install

From this repository:

```sh
cd bb-plugins/sidebar-model-label
npm install
bb plugin install . --yes
```

The plugin needs no bb setting. It does not use the sidebar's Metadata row
option.

## What the label shows

The label shows the model of the thread's next turn, which is the model bb
would use if you sent a message now.

| Situation | Label |
| --- | --- |
| The provider names the model | `Opus 5.5` |
| The name starts with a vendor, such as `Anthropic · claude-opus-5-5` | `claude-opus-5-5` |
| The provider only calls it `Default (recommended)`, or does not list it | The model id |
| The model is empty or `default` | `Default` |
| bb cannot resolve a model | Nothing |

Model names come from each provider's model list on the bb server's own
machine. A thread on another machine whose model is not in that list shows
its model id. A row also shows the model id when its thread is not in the
active thread list, such as an archived thread.

The label and the gap before it take at most 40% of the title line's room
after the provider icon. A long model name ends in an ellipsis. In a very
narrow sidebar the title keeps most of the room and the label can show
nothing.

## When it updates

A row updates after a message is sent with a different model. Choosing another
model in the composer does not change the label until you send. The app asks
the server only about rows the sidebar has rendered, in one batch, and the
server asks the app to refresh a row only when its model actually changed.

## How it works

bb has no plugin slot for text on a row's title line, so the plugin adds the
label to the sidebar's markup itself. A content script finds each thread row
by the documented `data-sidebar-thread-id` attribute, then places one
`<span data-sidebar-model-label>` after the row's title. An app overlay reads
the models through the plugin's own RPC and hands the label text to the
content script. Disabling or reloading the plugin removes every label it
added.

## Risks

- The title element (`.bb-thread-title`) and its parent line are private bb
  markup. If a bb release changes them, rows that no longer match get no
  label, and the sidebar is otherwise unchanged. Every such assumption is in
  [`sidebar-dom.ts`](sidebar-dom.ts).
- The plugin relies on experimental bb plugin APIs
  (`experimental_appOverlay`, `experimental_useSidebarThreads`,
  `experimental_useRpcKeyedQuery`, `experimental_whileWatched`,
  `experimental_thread.events`). A bb update can change or remove them.

## Development

```sh
npm test            # Vitest with the plugin SDK's backend and frontend harnesses
npm run typecheck
bb plugin build .   # writes dist/, which is ignored by Git
```

`npm run verify:live` checks the plugin in the real sidebar with headless
Chromium. It needs `BB_SERVER_URL`, and `BB_VERIFY_CHROMIUM` set to an
existing Chromium, because it never downloads one. Take a baseline with the
plugin disabled, then check with it enabled:

```sh
npm run verify:live -- --baseline > /tmp/sidebar-baseline.json
npm run verify:live -- /tmp/sidebar-baseline.json
npm run verify:live -- --cleanup    # reloads, then disables the plugin
```

The check compares each row's height, indentation, click target, provider
icon, actions, and title position with the baseline at a normal and a narrow
sidebar width. It also scrolls the sidebar to confirm that stuck parent rows
never overlap.

Tested with bb 0.49 and plugin SDK 0.6.132.

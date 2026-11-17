# sidebar-model-label

A [bb](https://getbb.app) plugin that shows the model each thread uses, in
small muted text under the thread's title in the sidebar. You can tell an Opus
thread from a GPT thread without opening it. Hover the label to see the full
model name and id.

## Turn it on

bb draws plugin text under a row's title only when two settings are on. Both
are off by default:

```sh
bb settings experiment threadRowMetadata true
bb thread-list prefs set showRowMetadata true
```

The second setting is also in the sidebar under Organize → Rows → Metadata.

## Install

From this repository:

```sh
cd bb-plugins/sidebar-model-label
npm install
bb plugin install . --yes
```

## What the label shows

The label shows the model of the thread's next turn, which is the model bb
would use if you sent a message now.

| Situation | Label | Tooltip |
| --- | --- | --- |
| The provider names the model | `Opus 5.5` | `Model: Opus 5.5 (claude-opus-5-5)` |
| The name starts with a vendor, such as `Anthropic · claude-opus-5-5` | `claude-opus-5-5` | The full name and the id |
| The provider only calls it `Default (recommended)`, or does not list it | The model id | The name, if any, and the id |
| The model is empty or `default` | `Default` | `Model: provider default` |
| bb cannot resolve a model | Nothing | None |

Model names come from each provider's model list on the bb server's own
machine. A thread on another machine whose model is not in that list shows
its model id.

## When it updates

A row updates after a message is sent with a different model. Choosing another
model in the composer does not change the label until you send. The server
rechecks a thread only while an open bb window lists it, and asks the app to
refresh that row only when the model actually changed.

## Row height

The label sits on its own line under the title, so every labeled row is two
lines tall. A label on the title line would need changes to bb's sidebar
markup, which plugins cannot make through a supported API. The label shares
its line with other plugins' items and comes before the pull request number
from GitHub PR Status.

## Risks

The plugin relies on experimental bb plugin APIs
(`experimental_threadRowMetadata`, `experimental_useRpcKeyedQuery`,
`experimental_whileWatched`, `experimental_thread.events`). A bb update can
change or remove them.

## Development

```sh
npm test            # Vitest with the plugin SDK's backend and frontend harnesses
npm run typecheck
bb plugin build .   # writes dist/, which is ignored by Git
```

Tested with bb 0.49 and plugin SDK 0.6.132.

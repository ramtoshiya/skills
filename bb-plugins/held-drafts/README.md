# held-drafts

A [bb](https://getbb.app) plugin that lets any agent or script create a thread
whose first message waits for a person. The thread appears in the sidebar with
its message in the Queue. **Send now** dispatches it. Deleting the thread
discards it, and an unsent draft has no worktree to clean up.

bb's built-in Drafts plugin does the same for messages a person types in the
composer, but it has no command an agent can call. This plugin adds one:

```sh
bb draft create --prompt "$(cat brief.md)" --title "Fix the flaky test" \
  --new-environment worktree --provider claude-code --model claude-opus-5-5
```

`bb draft create --help` lists every option. The project defaults to the
calling thread's project. Without `--new-environment`, the thread uses the
project's default environment.

## Install

From this repository:

```sh
cd bb-plugins/held-drafts
npm install
bb plugin install . --yes
```

`npm install` only fetches type declarations for `npm run typecheck`. bb loads
`server.ts` directly.

## Hold or send

The `mode` setting decides what happens to new threads:

- `draft` (default) holds the first message until a person sends it.
- `direct` sends it immediately, so `bb draft create` behaves like
  `bb thread spawn`.

```sh
bb plugin config held-drafts set mode direct
```

Drafts created earlier stay held after a switch to `direct`.

## How it works

`bb draft create` spawns a thread attributed to this plugin. The plugin's
`message.dispatch` hook answers `wait` with the reason `Draft` while that
thread is still `pending`, and keeps answering `wait` on later re-checks of the
held row. **Send now** in the app and `bb thread queue send` skip every
dispatch hook, so the message goes out and bb creates the environment at that
moment. Later messages in the thread are not held.

## Risks

- The plugin relies on experimental bb plugin APIs (`experimental_hooks`,
  `experimental_optionLabels`). A bb update can change or remove them.
- When the plugin is disabled, removed, or fails to load, bb clears waits
  owned by plugins that are not running. Every held draft is then sent. Delete
  drafts you do not want before you disable the plugin.
- Removing only the queued message (its cancel control) leaves an empty
  pending thread. Delete the thread to discard a draft.

Tested with bb 0.49 and plugin SDK 0.6.132.

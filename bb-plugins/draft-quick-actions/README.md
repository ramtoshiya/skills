# Draft quick actions

Send a Held Drafts message from the sidebar without opening its thread.
The plugin adds **Run draft** to BB's thread menus and quick-action picker.
Held Drafts and BB's sidebar stay unchanged.

## Install and show the button

From this repository:

```sh
cd bb-plugins/draft-quick-actions
npm ci
bb plugin build .
bb plugin install . --yes
```

Open a thread row's menu, choose **Customize actions**, and put **Run draft**
in an empty slot. Keep any existing actions you want. The choice applies to
all rows, but the button appears only for eligible drafts.

Alternatively, inspect the current buttons with
`bb thread-list prefs get rowActions --json`, then add
`draft-quick-actions/run-draft` to the existing list. There are three slots.
For a list that currently contains only Archive:

```sh
bb thread-list prefs set rowActions '["draft-quick-actions/run-draft","bb--core/archive"]'
```

Hover a draft's row and click the play button to approve its queued message.
There is no confirmation dialog and no navigation. A toast distinguishes a
sent message from an approved message that still waits for its workspace or
another BB prerequisite.

## Eligible drafts

The thread must be unstarted, active in the sidebar, and created by Held
Drafts. It must have one editable inline message held by `held-drafts` in the
`waiting` state. Scheduled messages, retries, grouped messages, and other
plugins' waits are not quick-action targets. Use BB's Queue for those cases.

The server checks the thread and its complete queue again when you click.
If the message was removed, replaced, edited, or joined by another message,
the request fails without choosing a different message. The list refreshes
so you can review the new state. Requests through this plugin are serialized
per thread across app windows while a send is in flight.

## Boundaries and compatibility

The plugin uses BB's public Queue APIs and
`experimental_threadAction`. It does not import Held Drafts code, change its
mode, or create replacement messages. Disabling this plugin leaves manual
**Send now** available.

The visible list comes from one complete workspace Queue read and updates
on queue changes and reconnection. Reading the complete queue also hides
threads that have additional messages held by a different wait. Requests and realtime subscriptions are disposed
when the action is no longer mounted.

BB's send API has no atomic last-modified precondition. The version check
happens immediately before the send, but it cannot prevent an external edit
in the interval between those two API calls. The plugin also cannot serialize
BB's own **Send now** button or another plugin. BB owns dispatch and its
message-claim behavior.

The action API is experimental and the holder id `held-drafts` is part of
this integration. Verify the action after upgrading BB or replacing the
Held Drafts plugin.

## Verify changes

```sh
npm test
npm run typecheck
bb plugin build .
```

The tests run BB's backend and frontend harnesses. They cover changed targets,
concurrent requests, retry after a failed send, queued approval, row updates,
and subscription cleanup.

Run the live check against an installed plugin with **Run draft** already
selected. Set `BB_VERIFY_PROJECT` to a test project id and
`BB_VERIFY_CHROMIUM` to an existing Chromium executable compatible with
Playwright. `BB_SERVER_URL` is provided inside a BB agent thread.

```sh
BB_VERIFY_PROJECT=proj_example BB_VERIFY_CHROMIUM=/path/to/chromium npm run verify:live
```

The check creates and pins its own temporary draft, clicks the real sidebar
button, verifies that the original message leaves the Held Drafts wait
without navigation, and deletes its test thread. It sends a short verification
prompt to Claude Haiku 5.5. It does not approve existing drafts or download a
browser.

BB 0.49's `bb plugin types --check` expects a caret range for the shimmed
`sonner` package and rejects this repository's required exact pin. The SDK
version matches the host at `0.6.132`. TypeScript, bundle builds, and the live
check validate the exact-pinned configuration instead.

Tested with BB 0.49 and plugin SDK 0.6.132.

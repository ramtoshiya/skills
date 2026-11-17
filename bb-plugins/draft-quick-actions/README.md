# Draft quick actions

Send a Held Drafts message with one click or tap. The plugin adds
**Run draft** to the open draft's thread header, BB's thread menus, and the
sidebar quick-action picker. Held Drafts and BB's sidebar stay unchanged.

## Install

From this repository:

```sh
cd bb-plugins/draft-quick-actions
npm ci
bb plugin build .
bb plugin install . --yes
```

## Approve from the thread header

Open the draft's thread. On a window or pane 768 CSS pixels wide or wider,
**Run draft** is a button in the thread header, after the workspace's
**Open** button. It needs no hover, so it works with a mouse and on touch
screens such as an iPad.

On narrower screens, such as a phone, and in narrow split panes, BB moves
header buttons into the header's **Thread actions** menu (`···`). Tap `···`
and choose **Run draft** at the top of the menu. In BB 0.49 that menu also
lists the menu-entry version of **Run draft**, so the label appears twice.
Both entries approve the same message. The plugin cannot hide either copy,
because BB does not tell a thread action which menu shows it. The 768-pixel
width is BB 0.49's phone breakpoint. The plugin does not set it.

## Show the button on sidebar rows

Sidebar quick-action buttons appear only when you point at a row with a
mouse or trackpad. Touch screens hide them. On an iPad, touching and holding
a sidebar row can start a drag instead of opening the row's menu. Use the
header button on touch screens.

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

Point at a draft's row and click the play button to approve its queued
message.

Every **Run draft** control sends the message without a confirmation dialog
and without navigation. A toast distinguishes a
sent message from an approved message that still waits for its workspace or
another BB prerequisite.

## Eligible drafts

The thread must be unstarted, active in the sidebar, and created by Held
Drafts. It must have one editable inline message held by `held-drafts` in the
`waiting` state. Scheduled messages, retries, grouped messages, and other
plugins' waits are not quick-action targets. Use BB's Queue for those cases.

The server checks the thread and its complete queue again when you click or
tap.
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
concurrent requests, retry after a failed send, queued approval, the header
and menu registrations, row updates, and subscription cleanup.

Run the live check against an installed plugin with **Run draft** already
selected. Set `BB_VERIFY_PROJECT` to a test project id and
`BB_VERIFY_CHROMIUM` to an existing Chromium executable compatible with
Playwright. `BB_SERVER_URL` is provided inside a BB agent thread.

```sh
BB_VERIFY_PROJECT=proj_example BB_VERIFY_CHROMIUM=/path/to/chromium npm run verify:live
```

The check creates one temporary draft for each of four cases:

- A desktop sidebar row. An additional scheduled message must hide the button,
  and removing that message must restore it before the click.
- The desktop thread header.
- The thread header on an 834 by 1194 touch screen without hover.
- The **Thread actions** menu on a 390 by 844 touch screen. The check reports
  how many **Run draft** entries the menu lists and taps the first.

Each case holds the request until the control shows its pending state where
the control stays on screen. It then checks that exactly one request carries
the displayed target, and that the original message leaves the Held Drafts
wait without navigation or replacement messages. It waits for the expected
Claude Haiku 5.5 reply and for the control to disappear. The check deletes its
test threads even on failure. It does not approve existing drafts or download
a browser. Touch emulation in Chromium is not a physical iPad.

BB 0.49's `bb plugin types --check` expects a caret range for the shimmed
`sonner` package and rejects this repository's required exact pin. The SDK
version matches the host at `0.6.132`. TypeScript, bundle builds, and the live
check validate the exact-pinned configuration instead.

Tested with BB 0.49 and plugin SDK 0.6.132.

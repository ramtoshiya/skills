# Draft quick actions

Send a Held Drafts message with one click or tap, on its own model or on a
model you pick. The plugin adds **Run draft** to the open draft's thread
header, BB's thread menus, and the sidebar quick-action picker. It adds
**Run draft on…** to the thread header and BB's thread menus. Held Drafts
and BB's sidebar stay unchanged.

## Install

From this repository:

```sh
cd bb-plugins/draft-quick-actions
npm ci
bb plugin build .
bb plugin install . --yes
```

## Approve from the thread header

Open the draft's thread. In a window 768 CSS pixels wide or wider,
**Run draft** and **Run draft on…** are buttons in the thread header, after
the workspace's **Open** button. They need no hover, so they work with a
mouse and on touch screens such as an iPad.

On narrower screens, such as a phone, and in narrow split panes, BB moves
header buttons into the header's **Thread actions** menu (`···`). Tap `···`
and choose **Run draft** or **Run draft on…** at the top of the menu. In BB
0.49 that menu also lists the menu-entry versions of both actions, so each
label appears twice. Both copies of an action do the same thing. The plugin
cannot tell the two copies apart, because BB does not tell a thread action
which menu shows it. The 768-pixel width is BB 0.49's phone breakpoint. The
plugin does not set it.

## Run a draft on another model

Choose **Run draft on…** to open a dialog with BB's provider and model
picker. The picker starts at the draft's provider and the queued message's
model. Pick a provider, model, and reasoning level, then choose **Run**.
**Cancel**, the Escape key, or a click or tap outside the dialog closes it
without sending. The dialog's buttons are at least 44 CSS pixels tall and
need no hover.

A model from the draft's own provider changes the queued message's model,
reasoning level, and service tier in place, then sends it. The thread stays
the same.

BB cannot change a thread's provider. A model from another provider
therefore replaces the draft with a new thread on that provider. The dialog
says so before you choose **Run**. The new thread gets the same prompt,
attachments, title, parent thread, parent notification setting, project,
sidebar section, permission mode, and environment request. It starts at
once. The plugin then deletes the draft and the app opens the new thread.
The thread ID changes. If the new thread cannot start, the draft stays as it
was. If the draft cannot be deleted after the new thread starts, a warning
names the new thread and you delete the draft yourself.

The environment request comes from Held Drafts, which records it when
`bb draft create` makes the draft. A draft created by a Held Drafts version
that did not record it cannot move to another provider. The error asks you
to recreate it with `bb draft create`. Models from its own provider still
work.

## Run a draft whose model belongs to another provider

A queued message can carry a model that the draft's provider does not
offer. For such a draft, **Run draft** looks up which enabled providers
offer the model. When exactly one other provider offers it, **Run draft**
moves the draft to that provider as **Run draft on…** does. When no provider
or several other providers offer it, nothing is sent and the error asks you
to choose a model with **Run draft on…**.

BB's own **Send now** in the Queue always sends on the draft's original
provider. It cannot use another provider's model. Use **Run draft** or
**Run draft on…** for a draft like this.

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

Every **Run draft** control sends the message without a confirmation dialog.
It keeps you on the current page unless the draft moves to a new thread on
another provider. A toast distinguishes a sent message from an approved
message that still waits for its workspace or another BB prerequisite.

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

The plugin uses BB's public Queue, thread, and provider APIs,
`experimental_threadAction`, `experimental_appOverlay`, and
`experimental_ProviderModelPicker`. It reads the `environment` key of the
thread's `held-drafts` plugin metadata. It does not import Held Drafts code,
change its mode, or create replacement messages. It creates a thread only
when a draft moves to another provider. Disabling this plugin leaves manual
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
concurrent requests, retry after a failed send, and queued approval. They
cover a model change in place, a move to another provider with the copied
thread settings, plain **Run draft** with another provider's model, unknown
and ambiguous models, a draft without a recorded environment, a failed start,
and a failed delete. They also cover the header and menu registrations,
opening, running, and closing the **Run draft on…** dialog, row updates, and
subscription cleanup.

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

In the two header cases, the check holds the request until the button shows
**Sending draft…** and is disabled. In every case, it checks that exactly one
request carries the displayed target, and that the original message leaves
the Held Drafts wait without navigation or replacement messages, and waits for
the expected Claude Haiku 5.5 reply. In the header and menu cases, it also
waits for **Run draft** to disappear after the send. The check deletes its
test threads even on failure. It does not approve existing drafts or download
a browser. Touch emulation in Chromium is not a physical iPad.

BB 0.49's `bb plugin types --check` expects a caret range for the shimmed
`sonner` package and rejects this repository's required exact pin. The SDK
version matches the host at `0.6.132`. TypeScript, bundle builds, and the live
check validate the exact-pinned configuration instead.

Tested with BB 0.49 and plugin SDK 0.6.132.

---
name: draft-quick-actions
description: Explain or troubleshoot the Run draft header button, thread menu entry, and sidebar button for Held Drafts messages in BB, including approval on an iPad or phone.
---

# Draft quick actions {:#draft-quick-actions}

This plugin adds **Run draft** in two registrations that share one eligibility
check and one `runDraft` RPC:

- `draft-quick-actions/run-draft` is a thread menu entry. It appears in the
  thread header's **Thread actions** menu (`···`), sidebar row menus, and the
  quick-action picker. It is the key for a sidebar quick-action slot.
- `draft-quick-actions/run-draft-header` is a button in the open draft's
  thread header. It never appears in the quick-action picker.

## Approval {:#approval}

The person's click or tap approves the existing queued message. Do not invoke
`runDraft` RPC or send a real held draft on the person's behalf without
explicit authorization for that draft. Creating a draft does not approve it.

## Touch screens {:#touch-screens}

To approve on an iPad or another touch screen, tell the person to open the
draft's thread and tap **Run draft** in the thread header. The button needs
no hover. Do not suggest hovering a sidebar row or touching and holding it.
Touch screens hide sidebar quick-action buttons. On an iPad, touching and
holding a sidebar row can start a drag instead of opening its menu.

In BB 0.49, a window narrower than 768 CSS pixels, such as a phone, or a
narrow split pane moves header buttons into the header's `···` menu. Tell the person to tap
`···` and choose **Run draft** at the top. That menu also lists the menu entry,
so **Run draft** appears twice there. Both entries approve the same message.
The plugin cannot tell the two copies apart, because BB does not tell a
thread action which menu shows it.

## Missing button {:#missing-button}

Read `bb thread queue list <thread-id> --json` to inspect the draft. Every
**Run draft** control appears for an unstarted, unarchived Held Drafts thread
with one editable inline message in `waiting` state, held by `held-drafts`.
Other waits, retries, schedules, and grouped messages use BB's Queue instead.

The header button is missing on a phone-width screen because it is in the
`···` menu. For a missing sidebar button, read
`bb thread-list prefs get rowActions --json` to inspect the configured
buttons. Preserve existing choices when changing the list, which has at most
three slots. The plugin has no settings and no CLI subcommand.

The action rechecks the queue on click or tap. A changed target fails and
refreshes the controls. A successful approval that remains queued is not
evidence that the agent has started. Inspect the thread's actual runtime state
when needed.

---
name: draft-quick-actions
description: Explain or troubleshoot the Run draft and Run draft on… header buttons, thread menu entries, and sidebar button for Held Drafts messages in BB, including approval on an iPad or phone and running a draft on another provider's model.
---

# Draft quick actions {:#draft-quick-actions}

This plugin adds **Run draft** and **Run draft on…** in four registrations
that share one eligibility check, one `runDraft` RPC, and one `chooserStart`
RPC for the dialog's starting model:

- `draft-quick-actions/run-draft` is a thread menu entry. It appears in the
  thread header's **Thread actions** menu (`···`), sidebar row menus, and the
  quick-action picker. It is the key for a sidebar quick-action slot.
- `draft-quick-actions/run-draft-header` is a button in the open draft's
  thread header. It never appears in the quick-action picker.
- `draft-quick-actions/run-draft-on` and
  `draft-quick-actions/run-draft-on-header` are the menu entry and header
  button for **Run draft on…**. Both open one dialog with BB's provider and
  model picker. BB 0.49 shows the two header buttons as one split button:
  **Run draft** with an arrow that opens **Run draft on…**.

## Model choice {:#model-choice}

In the **Run draft on…** dialog, a model from the draft's own provider updates
the queued message's model, reasoning level, and service tier, then sends it
on the same thread. BB 0.49 cannot change a thread's provider, so a model from
another provider starts a new thread on that provider and deletes the draft.
The new thread has a new ID and keeps the prompt, title, parent thread, parent
notification setting, project, section, permission mode, and the environment
request that Held Drafts saved in its plugin metadata. The app opens it. A
draft without that saved environment cannot move to another provider. Tell the
person to recreate it with `bb draft create` or pick a model from the draft's
own provider.

Plain **Run draft** on a message whose model the draft's provider does not
offer moves the draft to the one other enabled provider that offers the model.
With no such provider or several, it sends nothing and opens the
**Run draft on…** dialog. The dialog starts on a provider that offers the
queued model, preferring the draft's own provider. BB's own **Send now** always uses the draft's original
provider, so it cannot run another provider's model.

## Approval {:#approval}

The person's click or tap approves the existing queued message on the model
the person picks. Do not invoke `runDraft` RPC or send a real held draft on
the person's behalf without explicit authorization for that draft. Creating
a draft does not approve it.

## Touch screens {:#touch-screens}

To approve on an iPad or another touch screen, tell the person to open the
draft's thread and tap **Run draft** in the thread header. The button needs
no hover. Do not suggest hovering a sidebar row or touching and holding it.
Touch screens hide sidebar quick-action buttons. On an iPad, touching and
holding a sidebar row can start a drag instead of opening its menu.

In BB 0.49, a window narrower than 768 CSS pixels, such as a phone, or a
narrow split pane moves header buttons into the header's `···` menu. Tell the person to tap
`···` and choose **Run draft** or **Run draft on…** at the top. That menu also
lists the menu entries, so each label appears twice there. Both copies of an
action do the same thing.
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

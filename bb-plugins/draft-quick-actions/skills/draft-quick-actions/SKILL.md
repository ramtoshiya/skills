---
name: draft-quick-actions
description: Explain or troubleshoot the Run draft sidebar button for Held Drafts messages in BB.
---

# Draft quick actions {:#draft-quick-actions}

This plugin adds **Run draft** to BB's thread action menus. The person can
place it in a sidebar quick-action slot through **Customize actions**.
The action key is `draft-quick-actions/run-draft`.

## Approval {:#approval}

The person's click approves the existing queued message. Do not invoke
`runDraft` RPC or send a real held draft on the person's behalf without
explicit authorization for that draft. Creating a draft does not approve it.

## Missing button {:#missing-button}

Read `bb thread-list prefs get rowActions --json` to inspect the configured
buttons. Preserve existing choices when changing the list, which has at most
three slots. The plugin has no settings and no CLI subcommand.

Read `bb thread queue list <thread-id> --json` to inspect the draft. The
button appears for an unstarted Held Drafts thread with one editable inline
message in `waiting` state, held by `held-drafts`. Other waits, retries,
schedules, and grouped messages use BB's Queue instead.

The action rechecks the queue on click. A changed target fails and refreshes
the list. A successful approval that remains queued is not evidence that the
agent has started. Inspect the thread's actual runtime state when needed.

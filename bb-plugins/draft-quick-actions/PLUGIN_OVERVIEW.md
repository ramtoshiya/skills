Approve a held draft from the sidebar without opening its thread or finding
its Queue card.

## What you get

Run draft appears in BB's thread menus and in Customize actions. Add it to a
quick-action slot to show a play button on eligible draft rows. Clicking it
sends the existing message and keeps you on the current page.

## Approval stays manual

Only you choose when a draft starts. The plugin does not switch Held Drafts
to automatic execution, rewrite its files, or create another thread. BB's
normal Send now action remains available when this plugin is disabled.

## Changed drafts and waiting workspaces

Before sending, the plugin checks that the draft still has the same single
held message and modification time. A changed draft produces an error rather
than sending a different message. This check is not an atomic edit lock.

A successful approval can still wait for a workspace, connected machine, or
another BB prerequisite. The result message distinguishes that wait from a
message that was sent.

## Requirements

An installed Held Drafts plugin must create the drafts. Scheduled messages,
grouped messages, retries, and other plugins' waits are outside this action.
The plugin uses BB's experimental thread action API and requires verification
after host API changes.

Approve a held draft with one click or tap, from its thread header or the
sidebar, without finding its Queue card. Run it on its own model or on a
model you pick, including another provider's.

## What you get

An open draft shows a Run draft button in its thread header, with an arrow
that opens Run draft on…. They need no hover, so they work on an iPad. On a phone, they
move into the header's ··· menu. Both actions also appear in BB's thread
menus. Run draft also appears in Customize actions. Add it to a quick-action
slot to show a play button on eligible draft rows when you point at them
with a mouse. Run draft sends the existing message and keeps you on the
current page.

## Pick a model

Run draft on… opens a dialog with BB's provider and model picker. A model
from the draft's own provider changes the queued message in place and sends
it on the same thread.

BB cannot change a thread's provider. A model from another provider
replaces the draft with a new thread on that provider. The new thread keeps
the prompt, title, parent thread, project, and environment request. The
draft is deleted and the app opens the new thread, which has a new thread
ID. The dialog tells you before this happens.

When a queued message carries a model that only one other provider offers,
Run draft moves the draft to that provider in the same way. When no provider
or several providers offer the model, Run draft sends nothing and opens the
Run draft on… dialog.

BB's own Send now in the Queue always sends on the draft's original
provider and cannot use another provider's model.

## Approval stays manual

Only you choose when a draft starts. The plugin does not switch Held Drafts
to automatic execution or rewrite its files. It creates a thread only when
you run a draft on another provider. BB's normal Send now action remains
available when this plugin is disabled.

## Changed drafts and waiting workspaces

Before sending, the plugin checks that the draft still has the same single
held message and modification time. A changed draft produces an error rather
than sending a different message. This check is not an atomic edit lock.

A successful approval can still wait for a workspace, connected machine, or
another BB prerequisite. The result message distinguishes that wait from a
message that was sent.

## Requirements

An installed Held Drafts plugin must create the drafts. Moving a draft to
another provider needs the draft's environment request, which Held Drafts
records when it creates the draft. Scheduled messages, grouped messages,
retries, and other plugins' waits are outside this action. The plugin uses
BB's experimental thread action, app overlay, and model picker APIs and
requires verification after host API changes.

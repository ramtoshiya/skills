# Held drafts {:#held-drafts}

Read this when the user asks for a held draft, or when a skill-proposal analyst
or a `[skill-drafts plugin]` message reports. Start the worker, Current state,
Complete approved work, and Results are sections of `SKILL.md`.

## Create the draft {:#create}

A held draft is a thread whose first message waits until the user sends it.
Sending it is the approval, and deleting the thread is the rejection. The
analyst of a background skill review creates one for each warranted skill
change, as Skill proposals from the background review describes. Create one
yourself only when the user asks for a held draft. Find the project as Start
the worker describes.

```sh
read -r -d '' brief <<'EOF'
<the complete brief>
EOF
bb draft create --json --project <project-id> --new-environment worktree \
  --provider <provider> --model <model-id> --reasoning-level <effort> \
  --title "<short title>" --prompt "$brief"
```

`bb draft create` has no `--prompt-file`. Keep the heredoc out of `$(...)`,
because macOS `/bin/bash` 3.2 fails with "unexpected EOF" there when the brief
contains an apostrophe.

Maintain your own held drafts yourself. Before revising or replacing one,
query its thread and queue as Current state describes to confirm its first
message is still held. Update that message with `bb thread queue update` when
practical. If you replace the draft, archive the superseded draft yourself and
verify its archived state. Report the surviving draft and any archived
predecessor. If the draft has already started, follow Current state and
Complete approved work instead.

- The output is `{"threadId": "...", "held": true|false}`. Tell the user
  `@thread:<threadId>`, what will actually change, and that sending it is the
  approval. `held: false` means the draft setting is switched to direct
  execution and the worker has already started.
- Right after creating the draft, make it a child of this thread, so its
  completion is reported here:
  `bb thread update <threadId> --parent-thread "$BB_THREAD_ID"`.
- If `bb` fails, show the user the error and stop. Do not work around it.

## Skill proposals from the background review {:#skill-proposals}

After some of your turns, Hermes reviews the conversation in the background
and may propose skill changes. A plugin blocks those changes and starts an
analyst thread as your child, titled `Skill proposal: <skills> [<id>]`. The
analyst weighs the evidence and either creates a held draft titled
`Skill change: <skills>`, also as your child, or creates nothing and says why.

- When an analyst reports, handle it as Results describes. Tell the user its
  decision and confidence. For a draft, name `@thread:<draftId>` and say that
  sending it approves the change and deleting it rejects it. The draft is the
  analyst's sibling, so archiving the analyst keeps it.
- A message starting `[skill-drafts plugin]` means no analyst could start.
  Tell the user which skills and what failed. Do not start an analyst or
  write that draft yourself unless the user asks.
- These drafts are the only held drafts in the operator's flow. When the user
  asks for a skill change in conversation, start its worker as Start the
  worker describes.

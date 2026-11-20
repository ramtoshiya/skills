# BB workers {:#bb-workers}

Read this before your first worker thread. [Worker routing](../SKILL.md) decides the row,
provider, and urgency. This file covers the commands.

## Start a worker {:#start}

Start each worker with `bb nest spawn` from the bb `nest` plugin. Run this as one shell command:

```sh
read -r -d '' brief <<'BRIEF'
<brief>
BRIEF
bb nest spawn --project "$BB_PROJECT_ID" --title "<role>" \
  --provider <provider> --model "$(<skill-dir>/scripts/newest-model <family> <provider>)" \
  --reasoning-level <effort> \
  --environment "$BB_ENVIRONMENT_ID" --prompt "$brief"
```

`bb nest spawn` makes the worker a child of your thread, as `bb thread spawn --parent-self` does.
bb rejects that command below four thread levels, and `bb nest spawn` then runs the worker under
the nearest ancestor that can take it and relays its results to you. Do not use
`bb thread spawn --parent-self`. If `bb nest` is missing, say that the bb `nest` plugin is not
installed and stop.

- `read` exits 1 at the end of the heredoc, so do not join it to the next command with `&&`. Keep
  the heredoc out of `$(...)`. `--prompt-file -` fails, because plugin commands cannot read
  multi-line standard input. `--prompt-file <path>` works.

- `--provider` is `claude-code` for a worker on Claude, and `codex` or `claudex` for a GPT worker
  on that route.
- `--model` is the output of `newest-model`, as the skill's first section requires. If the script
  exits nonzero, do not start the worker with an empty `--model`.
- `--reasoning-level` is the row's effort. Confirm that `bb provider models <provider> --json` lists
  it in the model's `supportedReasoningEfforts`. BB drops a level the model does not list, and the
  worker then runs at its own default.
- `--environment "$BB_ENVIRONMENT_ID"` shares your checkout, including uncommitted changes. Use it
  for read-only roles and for workers whose files no other writer touches at the same time. When
  workers edit overlapping files in parallel, or the calling workflow asks for isolation, commit
  what they need and pass `--new-environment worktree --base-branch "$(git branch --show-current)"`
  instead. Merge such a worker's commits into your branch before you archive it. Always pass one of
  these flags. Without one, the worker gets a fresh worktree of the project's default branch, which
  has neither your branch nor your uncommitted changes.

If the newest-model guard plugin rejects the spawn, it fails with HTTP 409 and names the newest ID,
and no thread is created. Spawn again with the script's output.

BB has no read-only permission mode, and a worker inherits your permission mode. Keep a read-only
role read-only through its brief. Say that it must not edit files, commit, or change anything
outside its reply. After it finishes, run `git status` to confirm that the checkout did not change.

## Wait for workers {:#wait}

Wait for workers through parent notifications. When a worker's turn completes, fails, or stops on a
question or an approval, BB sends a `[bb system]` message to your thread. For a worker that
`bb nest spawn` placed past the depth limit, the message starts with
`[nest] Automatic report from your worker` instead and needs no reply. The message steers into
your running turn, or starts a new turn when you are idle. Do other work meanwhile. When the next
step needs a result and no other work is left, end your turn with one line that names the workers
you are waiting for. Do not loop on `bb thread show` or `bb thread wait`.

When your own thread is a BB child, ending a turn reports that turn to your parent as your result.
`bb status` then shows a `Parent` and `Parent notifications: auto`. Keep the turn open instead. Run
`bb thread wait <worker-id> --timeout <limit> && bb thread output <worker-id>` in the foreground,
with a limit below your shell tool's timeout. Run it again only when it exits with code 2, which
means it timed out. For a worker that is your bb child, the `mail` bb plugin drops the completion
message for a reply this command already printed. A nest relay message still arrives.

Do the same for a long command, test run, or review: run it in the foreground and keep the turn.
Do not start it in the background and end the turn, because the parent receives that turn as a
completed result. If a turn must end before a scheduled resume and has nothing to report, reply with
only `[no-op]`.

If a worker's notice leaves you nothing to report or do, reply with exactly `[no-op]`. The `mail` and
`nest` bb plugins drop that turn's notice, so your own parent is not woken. Do not `bb thread tell` a
worker to acknowledge it. Send progress to your parent with `bb mail send`, which does not wake it.

Both messages quote a final reply of up to 4,000 characters. A longer reply arrives as one line
with its first line and length. Read it with `bb thread output <id>`.

## Change a running worker's model {:#move}

A thread keeps its provider. Within one provider, such as a Claude worker moving from `opus` to
`fable`, stop the running turn, set the model, and tell it to continue:

```sh
bb thread stop <id>
bb thread update <id> --model "$(<skill-dir>/scripts/newest-model fable)"
bb thread tell <id> 'Continue the task on the new model.'
```

When urgency ends, the new model can wait for the next turn, so skip the stop and the
continue message and run only `bb thread update <id> --model <model>`.

To move a worker to another provider, such as a GPT worker whose work became urgent, hand it off:

1. `bb thread stop <old-id>`. Leave the old thread idle and do not archive it yet.
2. Read where it stands: `bb thread log <old-id>`, and `git status` and `git diff` in its
   environment.
3. Start the new worker with `bb nest spawn` as above, on the target provider, with
   `--environment <old worker's environment id>` so it sees the same files. Its brief carries the
   original brief, the state reached, the uncommitted changes it now owns, and what is left.
4. Move the old worker's children under the new one. List them with
   `bb nest list --parent <old-id> --json`. Run `bb thread update <child-id> --parent-thread <new-id>`
   for each row whose `route` is `child`. A `relay` row cannot move. It keeps reporting to the old
   worker, so read its result with `bb thread output <child-id>` and pass it to the new worker.
5. Archive the old worker after the new one finishes. Archiving a thread also archives the children
   still under it and its relay workers, so step 4 comes first.

## Gate fixer {:#gate-fixer}

When a failed shared gate is urgent, one session starts one fixer:

- If a worker already fixes the gate, the session that started it switches it.
- If none exists and your session has a parent, tell the parent with `bb thread tell` and do not
  spawn one.
- If none exists and your session is top-level, the first session that notices spawns the fixer on
  Claude and tells the other affected top-level sessions with `bb thread tell` that it has taken
  the fix. Sessions told so do not spawn their own.

## Archive workers {:#archive}

Archive each worker with `bb thread archive <id>` once you have read its reply, merged its commits,
and need nothing more from it. Archiving keeps the worker's history, removes it from the thread
list, and archives the workers it started. A worker in your environment leaves that environment in
place. A worktree worker's checkout is removed five minutes after archiving, and its branch stays.

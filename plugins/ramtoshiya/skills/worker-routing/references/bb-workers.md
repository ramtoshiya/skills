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

- `--provider` is `claude-code` for a worker on Claude and `claudex` for a GPT worker. The `codex`
  provider is disabled in BB, so `bb nest spawn --provider codex` fails with HTTP 409.
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

BB has no read-only permission mode, and a worker inherits your permission mode. For a read-only
role, name the protected targets in its brief. Tell it not to change the checkout or commit.
After it finishes, run `git status` to confirm that the checkout did not change.

## Wait for workers {:#wait}

Every parent waits for a worker in the foreground and keeps its turn open, whether it is a top-level
session or a bb child. Do other work first when there is some. When the next step needs the result,
run this with a limit below your shell tool's timeout:

```sh
bb thread wait <worker-id> --timeout <limit> && bb thread output <worker-id>
```

Run it again only when it exits with code 2, which means it timed out. Do not end the turn to wait.
For a bb child, ending a turn reports it to your own parent as your result. The `mail` bb plugin
drops the completion message for a worker reply that this command already printed. A nest relay
message still arrives. For a worker that the nest command placed past the depth limit, it starts
with `[nest] Automatic report from your worker` and needs no reply.

The messages that bb and nest send quote a final reply of up to 4,000 characters. A longer reply
arrives as one line with its first line and length, and `bb thread output <worker-id>` prints it
whole. When that output is only `[no-op]` or empty, read `bb thread log <worker-id>` back to the
worker's last other reply before you call it stalled or finished.

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

To move a worker to another provider, such as a GPT worker whose work became urgent or a worker
stopped by a usage limit, hand it off:

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

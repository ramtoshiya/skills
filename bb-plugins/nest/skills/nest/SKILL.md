---
name: nest
description: Start a worker thread from any depth with `bb nest spawn`, and list a thread's workers with `bb nest list`. Use instead of `bb thread spawn --parent-self` whenever an agent starts a worker, because bb rejects children below four levels.
---

# Start workers with nest {:#nest}

`bb nest spawn` starts a worker of the calling thread (`BB_THREAD_ID`) at any
depth. Use it wherever you would run `bb thread spawn --parent-self`. bb
rejects that command from a fourth-level thread with `too_deep`.

## Start a worker {:#spawn}

Run this as one shell command:

```sh
read -r -d '' brief <<'BRIEF'
<the complete brief>
BRIEF
bb nest spawn --new-environment worktree --provider <provider-id> \
  --model <model-id> --reasoning-level <level> --title "<short title>" \
  --prompt "$brief"
```

- `read` exits 1 at the end of the heredoc. Do not join it to the next
  command with `&&`.
- Keep the heredoc out of `$(...)`, because macOS `/bin/bash` 3.2 fails there
  when the brief contains an apostrophe.
- `--prompt-file -` fails, because plugin commands cannot read multi-line
  standard input. `--prompt-file <path>` works and reads the file on your
  machine, relative to your directory.
- Every other option matches `bb thread spawn`: `--project`, `--environment`,
  `--new-environment`, `--base-branch`, `--provider`, `--model`,
  `--reasoning-level`, `--title`, and `--json`. The calling thread is always
  the parent, so `--parent-self` is optional.
- `--tag <tag>`, repeatable, gives the worker a mail tag such as
  `role=reviewer`, so `bb mail send --where role=reviewer` can reach it.
  Tags are not inherited.

## Results {:#results}

The output says which route bb allowed:

- `You will be notified when this thread is done.` The worker is a normal
  child, and bb notifies you as it does for `bb thread spawn`.
- `bb's depth limit placed it under <host>.` The worker runs under an
  ancestor that bb lets take children. Nest sends you each of its turn results,
  failures, and pending approvals or questions as a message that starts with
  `[nest] Automatic report from your worker`. Those messages need no reply.
  A reply over 4,000 characters arrives as one line that names
  `bb thread output <worker>`. A turn the worker ended only to self-compact
  is not reported. Never message the host about the worker.

`bb thread wait <worker>`, `bb thread output <worker>`, and
`bb thread interactions` work on both routes.

## List workers {:#list}

`bb nest list --parent <thread>` lists the unarchived workers of a thread
from both routes. `bb thread list --parent-thread` misses workers on the relay
route. Add `--json` for `id`, `status`, `route`, `physicalParentThreadId`,
and `title`.

## When you are a relay worker {:#relay-worker}

If your first message starts with `[nest] Your logical parent is`, follow it.
Your turn results reach that thread automatically. Do not send them with
`bb thread tell`, and never message the thread that `bb status` shows as your
parent.

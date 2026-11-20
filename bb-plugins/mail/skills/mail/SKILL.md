---
name: mail
description: Message other bb threads with `bb mail send`, choosing per message whether to wake the recipient now or leave it in the inbox for its next turn, and reach many threads at once with `--where` selectors and tags. Use whenever an agent messages another thread and the message should not wake it, or should reach several threads.
---

# Message threads with mail {:#mail}

Every message that starts a turn costs the recipient a turn. `bb mail send`
lets you decide, per message, whether it is worth one. `bb thread tell` always
wakes the recipient, as `bb mail send --wake` does.

## Wake or inbox {:#wake-or-inbox}

Without `--wake` the message waits in the recipient's inbox. It starts no
turn and arrives when the recipient's next turn starts. If the recipient is
working, it waits for the turn after the current one. With `--wake` it
starts a turn now, or joins the running one.

```sh
bb mail send <thread> --message "FYI: main moved to 3d34cff."
bb mail send <thread> --wake --message "Your brief changed: drop the API task."
```

These examples show the line, not a complete rule:

- Wake: a final result, a failure, a question you need answered, or a request
  that needs action now.
- Inbox: progress, facts the recipient may use later, or "main moved".

A reply to a thread that is waiting on you usually wakes it.

## Many recipients {:#selectors}

`--where` sends to every thread that matches all its terms. Check first with
`bb mail who`:

```sh
bb mail who --where parent=$BB_THREAD_ID
bb mail send --where parent=$BB_THREAD_ID --where role=reviewer --message "Re-review after 3d34cff."
```

Terms: `project=`, `parent=` (every descendant, including nest relay
workers), `env=`, `branch=`, `provider=`, `status=`, and tags. Mail never
reaches archived threads, held drafts, or you. It lists skipped drafts and
you in its report, and leaves archived threads out of it. Inbox is
the default here too, so add `--wake` only when every recipient must act now.

For a multi-line message, read it into a variable first:

```sh
read -r -d '' msg <<'EOF'
<message lines>
EOF
bb mail send <thread> --message "$msg"
```

`--message-file <path>` also works. `--message-file -` does not.

## Tags {:#tags}

Tags are labels any thread can set on any thread: `key=value` or a bare
word. Nothing sets them by default, and workers do not inherit them.

```sh
bb nest spawn ... --tag role=reviewer
bb mail tag add <thread> role=reviewer
bb mail tag rm <thread> role=reviewer
bb mail tag ls <thread>
```

`role=reviewer` and `team=web` are examples, not a fixed set.

## Notices you no longer get {:#notices}

With mail installed, bb does not wake you for:

- a thread being moved under you or away from you,
- a child's turn that ended only to start self-compaction,
- a child's result that your `bb thread wait <child> && bb thread output <child>`
  already printed during the child's latest turn. A bare `bb thread wait`
  prints no result, so that notice still comes.

A child reply over 4,000 characters arrives as one line with its first line,
its length, and `bb thread output <child>`. Run that command to read it.

# mail

A [bb](https://getbb.app) plugin that cuts turns agents spend on messages
from other agents. It does three things:

- It removes bb notices that only start a turn to say nothing new.
- `bb mail send` lets the sender choose whether a message starts the
  recipient's turn now or waits in its inbox until its next turn.
- `bb mail send --where` sends one message to every thread a selector
  matches.

```sh
bb mail send thr_abc --message "main moved to 3d34cff. Rebase before you push."
bb mail send thr_abc --wake --message "Stop: the schema changed. Read docs/schema.md."
bb mail send --where parent=thr_lead --where role=reviewer --message "Review the new diff."
bb mail who --where project=proj_web provider=codex
bb mail tag add thr_abc role=reviewer
```

## Install

From this repository:

```sh
cd bb-plugins/mail
npm ci --ignore-scripts
bb plugin install . --yes
```

## Commands

| Command | Does |
| --- | --- |
| `bb mail send <thread> --message <text>` | Puts the message in the thread's inbox |
| `bb mail send <thread> --wake --message <text>` | Sends the message and starts the thread's turn now |
| `bb mail send --where <selector> --message <text>` | Puts the message in the inbox of every thread the selector matches |
| `bb mail who --where <selector>` | Lists the threads a selector matches, without sending |
| `bb mail tag add <thread> <tag>...` | Adds tags to any thread |
| `bb mail tag rm <thread> <tag>...` | Removes tags |
| `bb mail tag ls [thread]` | Lists a thread's tags, by default the caller's |

`--message-file <path>` reads the message from a file on the caller's
machine instead. `--json` prints a machine-readable report. A message sent
from an agent thread shows `[bb message from thread:<id>]`, as
`bb thread tell` does.

## Inbox and wake

A message sent without `--wake` never starts a turn. bb keeps it queued and
adds it to the recipient's next turn, whatever starts that turn. If the
recipient is already working, the message joins the running turn, as any
queued message does. A later message that does start a turn carries the
held inbox messages with it.

Mail marks an inbox message with a plugin submission when it sends it, and
remembers which queued messages it is holding. That memory lives in the
running plugin. If mail restarts while a message is held, that message can
start a turn when bb next tries to deliver it.

## Selectors

`--where` takes terms, and a thread must match all of them. Repeat `--where`
or put several terms in one value separated by spaces.

| Term | Matches |
| --- | --- |
| `project=<id>` | Threads in the project |
| `parent=<thread>` | Every descendant of the thread. It follows nest's logical parent where nest placed a worker under another thread |
| `env=<id>` | Threads in the environment |
| `branch=<name>` | Threads whose environment is on the branch |
| `provider=<id>` | Threads on the provider, such as `codex` |
| `status=<status>` | Threads in that status, such as `idle` or `active` |
| `<key>=<value>` or `<word>` | Threads with that tag |

A selector send never reaches an archived thread, a thread that has not sent
its first message (such as a held draft), or the sender. The report lists
the skipped ones. The message starts with `[mail to <selector>]` so each
recipient knows it went to a group.

Tags are free text: `key=value` or a bare word of letters, digits, and
`. _ : / -`. The built-in keys above cannot be tags. Any thread can edit any
thread's tags. A new thread starts with no tags, and `bb nest spawn --tag`
sets them when the thread is created.

## Notices

| bb notice | What mail does |
| --- | --- |
| A thread became or stopped being this thread's child | Deletes it, whoever moved the thread |
| A child finished a turn that ended only to start the self-compact helper | Deletes it, because the child resumes on its own |
| A child finished, and this thread's `bb thread wait <child>` command already printed the child's reply | Deletes it |
| A child finished while this thread's `bb thread wait <child>` command is still running | Holds it up to 30 seconds, then decides again |
| A child finished with a reply over 4,000 characters | Replaces bb's truncated quote with one line: the reply's first line, its length, and `bb thread output <child>` |
| Any other child notice, a notice bb merged for several children, and environment directory notices | Leaves it alone |

`bb thread wait` alone prints only a status line, so its notice is still
delivered. Run `bb thread wait <child> --timeout <seconds> && bb thread output <child>`
to get the reply in the same command and let mail drop the notice. A wait that
timed out or failed does not count.

## Limits

- If mail is stopped or crashes, held inbox messages are delivered as ordinary
  messages, and bb's notices arrive unchanged. Every check that throws lets
  the message through.
- A completion notice changes in place when bb merges another child's outcome
  into it, and bb emits no event for the merge. Mail reads the notice again
  and deletes it only if it has not changed. A merge in the few milliseconds
  between that read and the delete would lose the merged outcome.
- The wait check reads at most the parent's last 100 events, and the
  compaction check reads the child's last 100 events. bb refuses a larger
  read.
- `parent=` follows nest's metadata. A thread moved with
  `bb thread update --parent-thread` keeps any logical parent nest recorded.

## bb internals and experimental APIs

A bb update can change any of these:

- Experimental plugin APIs: `experimental_hooks.on("message.dispatch")`,
  its `experimental_submission` field, and `experimental_hooks.recheck` for
  the inbox,
  `threads.experimental_listPluginMetadata` for tags and nest's logical
  parents, and the `waitHolder` filter of `threads.queue.list`.
- bb's notice rows: the `systemNotice` kinds `ownership-assigned`,
  `ownership-removed`, `ownership-batch`, and `child-completed`, the subject
  shape `{ kind: "thread", threadId, outcomes }`, and that plugins may delete
  and reschedule these rows.
- That bb sets `originPluginId` on every message a plugin sends, so mail
  cannot use it to tell an inbox message from a wake message, and that bb
  passes the plugin submission only on a message's first delivery attempt.
- bb's 2-second window for merging child notices, during which mail decides.
- That a held notice is released with a `null` send time, because bb rejects
  a send time that is not in the future.
- bb's 4,000-character quote limit for child replies.
- The `commandExecution` items in thread events, with `command`, `exitCode`,
  and `aggregatedOutput`, which Claude Code and Codex threads both produce.
- The command text `bb thread wait <child>`, and the self-compact helper's
  `bb-compact.mjs run` without `--no-resume`.
- That bb compacts in a turn of its own with a `thread/compacted` event and
  no items.
- That nest stores a worker's logical parent as `logicalParentThreadId` in
  its thread metadata, and that one plugin may write another plugin's thread
  metadata, which `bb nest spawn --tag` uses.

## Development

```sh
npm run typecheck
npm test
```

Tested with bb 0.50.1 and plugin SDK 0.6.132.

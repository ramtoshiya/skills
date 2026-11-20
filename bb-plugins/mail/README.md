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
adds it to the recipient's next turn when that turn starts, whatever starts
it. A message sent while the recipient is working waits for the turn after
the current one, so it does not interrupt work in progress.

### ACP threads

bb steers a running ACP thread, such as Hermes (`acp-*` providers), by
cancelling its turn and sending the message again. Hermes discards a cancelled
turn that has not started yet, so a message steered in right after the user's
turn starts takes the user's message with it. For these recipients mail never
lets a message join a running turn. While the recipient is working, mail holds
every message that did not come from a user, whether sent with `bb mail send`,
`bb mail send --wake`, `bb thread tell`, or a bb notice. When the recipient goes
idle, mail releases them and they start a turn of their own. Mail never holds
or reorders a user's message. Claude Code and Codex threads keep the behavior
above.

An inbox message for an idle ACP thread also waits until a turn has started
and ended, so it does not start a turn on its own.

### Self-compaction

Held inbox messages count in `queuedMessageCount`, but the self-compact helper
does not treat them as queued work, so they do not stop a compaction.

Mail marks an inbox message with a plugin submission when it sends it, and
remembers which queued messages it is holding. That memory lives in the
running plugin. If mail restarts while a message is held, that message can
start a turn when bb next tries to deliver it. Each time a thread starts a
turn, mail asks bb which messages it holds for that thread and lets them
join the turn.

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
skipped drafts and the sender. Archived threads are not listed at all. The message starts with `[mail to <selector>]` so each
recipient knows it went to a group.

Tags are free text: `key=value` or a bare word of letters, digits, and
`. _ : / -`. The built-in keys above cannot be tags. Any thread can edit any
thread's tags. A new thread starts with no tags, and `bb nest spawn --tag`
sets them when the thread is created.

## Notices

| bb notice | What mail does |
| --- | --- |
| A thread became or stopped being this thread's child | Deletes it, whoever moved the thread |
| A child finished a turn that ended only to start self-compaction, or bb's compaction turn after it | Deletes it, because the child resumes on its own |
| A child finished, and this thread's `bb thread wait <child>` command already printed the child's reply | Deletes it |
| A child finished a turn whose whole reply is `[no-op]` (after trimming) | Deletes it. A reply that merely contains the marker is delivered |
| A child finished while this thread's `bb thread wait <child>` command is still running | Holds it up to 30 seconds, then decides again |
| A child finished with a reply over 4,000 characters | Replaces bb's truncated quote with one line: the reply's first line, its length, and `bb thread output <child>` |
| Any other child notice, a notice bb merged for several children, and environment directory notices | Leaves it alone |

`bb thread wait` alone prints only a status line, so its notice is still
delivered. Run `bb thread wait <child> --timeout <seconds> && bb thread output <child>`
to get the reply in the same command and let mail drop the notice. A wait that
timed out or failed does not count, and neither does a wait that returned
before the child's latest turn started.

## Limits

- If mail is stopped or crashes, held inbox messages are delivered as ordinary
  messages, and bb's notices arrive unchanged. Every check that throws lets
  the message through.
- A completion notice changes in place when bb merges another child's outcome
  into it, and bb emits no event for the merge. Before mail deletes or
  replaces a notice, it reschedules the notice 30 seconds out, conditional on
  the notice being unchanged. bb merges nothing into a rescheduled notice. If
  the notice changed, mail leaves it alone. If mail fails after that, the
  notice arrives when the 30 seconds end.
- Mail decides from the child's latest reply and turn. If the child starts
  another turn in the second before mail reads them, mail decides from that
  turn.
- The wait check reads at most the parent's last 100 events, and the
  compaction check reads the child's last 100 events. bb refuses a larger
  read. If the child's latest turn started more than 100 events ago, its
  notice is delivered.
- `parent=` follows nest's metadata. A thread moved with
  `bb thread update --parent-thread` keeps any logical parent nest recorded.

- A user's message that arrives as mail releases a held message to an ACP
  thread can still lose to it. If bb sends the release first, the user's
  message cancels that turn before it starts, and Hermes discards the user's
  message. Mail cannot see this race.
- A user's message sent into a running ACP turn cancels the turn, as it does
  without mail. Mail releases held messages when the cancelled turn goes idle,
  and they can reach the thread before the user's resent message does.

## bb internals and experimental APIs

A bb update can change any of these:

- Experimental plugin APIs: `experimental_hooks.on("message.dispatch")`,
  its `experimental_submission`, `attempt`, and `initiator` fields, and `experimental_hooks.recheck` for
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
  `bb-compact.mjs run` without `--no-resume`. A launch counts only with exit
  code 0, which Claude Code records when it starts the helper in the
  background. A launch that fails in the foreground records another code.
- Hermes's `self_compact` tool call, which bb records as a `toolCall` item
  titled `self_compact` with `arguments.action` `compact` and a result that
  contains `**status:** scheduled`. `resume: false` is not dropped, because
  that child then waits for the user.
- The `createdAt` time on thread events, which mail compares between the
  parent's wait and the child's turn.
- That bb compacts in a turn of its own with a `thread/compacted` event and
  no items other than Hermes's one agent message.
- That nest stores a worker's logical parent as `logicalParentThreadId` in
  its thread metadata, and that one plugin may write another plugin's thread
  metadata, which `bb nest spawn --tag` uses.

## Development

```sh
npm run typecheck
npm test
```

Tested with bb 0.50.1 and plugin SDK 0.6.132.

# Background tools

This [bb](https://getbb.app) plugin moves a thread's running command or agent to
the background, as Ctrl+B does in the Claude Code terminal. The tool call
returns at once, the agent continues its turn, and Claude Code tells the agent
when the background work ends. It works on Claude Code threads and on threads of
the [`claudex-native`](../claudex-native/README.md) provider.

## Use

Open the thread and do one of these while a command is running:

- Press **Cmd+Shift+B** on macOS, or **Ctrl+Shift+B** elsewhere. To use another
  key, change it under **Settings → Keyboard**. If another command uses the new
  key, bb offers to replace that binding. bb leaves the default unbound when
  another command already uses it.
- Run **Background tools: move running tool to background** from the command
  palette.
- Click **Background** in the thread header. The button is disabled while the
  thread is idle. On a narrow screen, such as a phone, bb puts it in the
  header's **Thread actions** menu.
- Run `bb background move <thread-id>`. Without an id it acts on the calling
  thread.

Everything that is running in the foreground moves, as with Ctrl+B. Claude Code
registers a command a few seconds after it starts, so an earlier request reports
that there is nothing to move. bb then lists the work as a background task.

## Install

You need macOS, bb running on this Mac, and
[Node.js](https://nodejs.org/en/download) on the `PATH` that bb gives its
providers. Use a checkout you intend to keep, because bb runs a file from it.

```sh
cd bb-plugins/background-tools
npm ci --ignore-scripts
bb plugin build .
bb plugin install . --yes
```

Install, disable, or remove the plugin while no thread depends on a background
command. Each of these changes the launch environment of Claude Code and Claudex
threads. On a thread's next turn, bb rebuilds its running Claude Code session,
and the rebuild stops the session's background commands. Installing again from
the same directory keeps running sessions.

A rebuilt session can still start Claude Code without the plugin. If a move
reports that it cannot reach the thread's Claude Code process, run
`bb thread stop <thread-id>`, then send the next message.

## How it works

bb's Claude Code bridge starts whatever `BB_CLAUDE_CODE_EXECUTABLE` names. The
plugin sets that variable for both providers to [`shim.cjs`](shim.cjs), which
starts `claude` or `~/.local/bin/claudex` with the same arguments and passes
their streams through. For each session the shim also listens on a Unix socket
in `/tmp/bb-background-tools-<uid>`, which only your user can open. When the
plugin connects, the shim sends Claude Code the `background_tasks` control
request of the [Agent SDK](https://code.claude.com/docs/en/agent-sdk/typescript)
and keeps the answer out of the stream bb reads.

Claude Code and Claudex sessions that bb starts on this Mac run through the
shim. If sessions stop starting, run `bb plugin disable background-tools`.

## Limits

- Only threads on the machine that runs the bb server get the shim. Threads on
  other hosts start Claude Code as before.
- The plugin replaces a `BB_CLAUDE_CODE_EXECUTABLE` that you set yourself. The
  shim then starts the first `claude` on `PATH` or in Claude Code's usual
  install locations.
- Claude Code decides what can move. It refuses when
  `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` turns background tasks off.

Tested with bb 0.50.1 and Claude Code 2.1.332.

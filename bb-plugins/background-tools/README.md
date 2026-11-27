# Background tools

This [bb](https://getbb.app) plugin moves a thread's running Bash command to the
background, as Ctrl+B does in the Claude Code terminal. The command keeps
running, and the agent continues its work. Claude Code tells the agent when the
command ends. It works on Claude Code threads and on threads of the
[`claudex-native`](../claudex-native/README.md) provider.

The plugin has two parts:

- The bb plugin in this folder adds the button, the shortcut, and the
  `bb background move` command.
- The Claude Code plugin in [`claude-plugin`](claude-plugin) runs inside each
  Claude Code session that bb starts and moves the command.

## Use

Open the thread and do one of these while a Bash command is running:

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

bb then lists the command as a background task. The plugin moves only Bash and
PowerShell commands. When another tool is running, such as a web search, the
plugin leaves it running and says so.

## Install

You need macOS and bb running on this Mac. Use a checkout you intend to keep,
because bb runs the plugin from it.

1. Install the bb plugin:

	```sh
	cd bb-plugins/background-tools
	npm ci --ignore-scripts
	bb plugin build .
	bb plugin install . --yes
	```

2. Install the Claude Code plugin from this repository's marketplace. The
	[agent plugin tasks](../../docs/agent-pack.md) install it with the other
	entries. To install it alone, run this from the repository root:

	```sh
	claude plugin marketplace add "$PWD"
	claude plugin install background-tools@ramtoshiya --scope user
	```

A Claude Code session loads the plugin when it starts. A session that was
already running reports that no session answered. To load the plugin there,
run `bb thread stop <thread-id>`, then send the next message.

## How it works

When a session starts with `BB_THREAD_STORAGE` set, the Claude Code plugin
empties `background-requests` in the thread's storage folder. Then it runs
`tail -n +1 -f` on that file so it reads requests written before `tail` starts.
`tail` waits on the file through kqueue, so nothing checks the file on a timer.

The bb plugin appends a request id to the file and waits up to five seconds for
`background-answer-<id>`. The Claude Code plugin reads the newest assistant
message. If every open tool call in it is Bash or PowerShell, the plugin aborts
the main turn. Claude Code then keeps the command running as a background task.
The plugin submits a prompt that tells the agent to continue, and it writes the
answer.

## Limits

- Only threads on the machine that runs the bb server can be reached.
- The plugin uses Claude Code's turn abort from a plugin hook. When background
  tasks are off, for example through `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`, the
  abort stops the command instead.
- A subagent that runs in the foreground stops with the turn. bb turns
  subagents off by default.
- bb shows the thread as idle for about two seconds between the stopped turn
  and the turn that continues.

Tested with bb 0.50.1 and Claude Code 2.1.332.

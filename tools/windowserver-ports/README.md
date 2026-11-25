# windowserver-ports

`windowserver-ports` warns you before WindowServer runs out of Mach ports and
logs you out. On macOS 27.2.1, WindowServer keeps one dead port name for every
client process that exits. When its port space reaches 305,834 names, the
kernel kills it and every GUI session ends. Only logging out or restarting
clears the names. The
[`windowserver-ports` skill](../../plugins/ramtoshiya/skills/windowserver-ports/SKILL.md)
describes which programs cause this and how to stop yours from adding names.

The command needs no root.

## Install

Requires macOS with Apple's Command Line Tools and
[Node.js](https://nodejs.org/en/download) 22.19 or newer. There are no other
dependencies. From a clone of this repository:

```sh
sh tools/windowserver-ports/install.sh
windowserver-ports install
```

The first command copies the program to `~/.local/share/windowserver-ports/`,
compiles the probe client there, and links `~/.local/bin/windowserver-ports`.
It refuses to replace a different command at that path. Put that directory on
`PATH`. Run it again after changing the source.

The second command writes and loads the LaunchAgent
`~/Library/LaunchAgents/com.ramtoshiya.windowserver-ports.plist`, which runs
`check` at login and every 10 minutes. The agent keeps the full path of the
Node.js that ran `install`, so run `windowserver-ports install` again after you
remove that Node.js version. `windowserver-ports status` says when the agent is
installed but has stopped adding readings.

`windowserver-ports uninstall` removes the LaunchAgent and keeps the history.
To remove the command too, delete `~/.local/bin/windowserver-ports`,
`~/.local/share/windowserver-ports/`, and
`~/.local/state/windowserver-ports/`.

## Commands

```sh
windowserver-ports status [--json]       # ports now, growth, projected time to the limit
windowserver-ports record                # add one reading to the history
windowserver-ports check [--threshold N] # record, then notify when the limit is near
windowserver-ports probe [--count N] [--settle SECONDS] [--json]
windowserver-ports clients [--last 1h] [--json]
windowserver-ports install | uninstall
```

`status` reads the current count without adding it to the history. `--json`
prints the same facts for scripts and agents. `level` is `warning` when
`reasons` is not empty, and `ok` otherwise. `growth` and `projection` are
`null` until the history holds an hour of readings for the running
WindowServer. `projection` is also `null` while the count is not growing. The
growth rate compares the current count with the oldest reading from the last 6
hours.

## Alerts

`check` sends an alert for either reason:

| Reason | Meaning |
| --- | --- |
| `threshold` | The count is at least 200,000. `--threshold` changes this |
| `projection` | At the current growth rate, the count reaches the limit within 24 hours |

It sends the alert with the [bb](https://getbb.app) app's
`bb push-notifications send`. When `bb` is missing or the send fails, it uses a
macOS notification from `osascript`. A successful `bb` send does not prove that
you saw it. bb shows desktop notifications only while a bb window or tab is
open, and reaches a phone only after you register one.

Each reason is sent again after 6 hours if it still applies, and right away for
a new WindowServer, such as after you log in again. An alert that neither
channel accepted is retried at the next check.

## Probe

`probe` answers whether the running macOS still keeps the names. It watches the
count while nothing is launched, then launches 20 small programs that connect
to WindowServer and exit, and watches again. The programs show no window and no
Dock icon. The count settles after each phase for 10 seconds, so a round takes
about 20 seconds.

| Result | Meaning |
| --- | --- |
| `present` | The count grew by about one port for each program, after subtracting the idle change |
| `gone` | The count did not grow |
| `inconclusive` | No round gave either answer, usually because other apps were opening or closing windows |

A round that gives no answer is repeated, up to 3 rounds and 60 programs in one
run. While the leak is present, each program leaves one more dead name until you
log out. The count from `top` includes the dead names but also every live port,
so run the probe while the Mac is quiet. A probe client that sees no screen
fails the run, so that a process without WindowServer access cannot report a
fix.

When `check` sees a new macOS version or build, it runs the probe once, at
least 30 minutes after WindowServer started, and notifies you of the result. An
inconclusive result is not retried, so run `probe` yourself.

## Which processes connect

`clients` counts new WindowServer connections in the unified log, by client.
The log names only processes that registered as apps. Other clients are named
while they are still running, and are counted together as
`(exited, no name in the log)` after they exit. Reading a long period can take
minutes.

## State

Files are in `~/.local/state/windowserver-ports/`, or under `$XDG_STATE_HOME`
when it is set.

| File | Contents |
| --- | --- |
| `history.jsonl` | One reading per line: time, macOS version, WindowServer process ID and start time, port count. It keeps about the last two weeks of 10-minute readings |
| `check.json` | The alerts already sent and the macOS version that `check` last saw |
| `check.log` | What the LaunchAgent sent, and its errors |

## Limits

- The limit of 305,834 was measured on macOS 27.2.1. The command uses it on
  every version.
- The count is every port WindowServer holds, not only dead names. An exact
  count of dead names needs `sudo lsmp`.
- A growth rate from the last few hours does not predict a loop that starts
  later.

Tested on macOS 27.2.1.

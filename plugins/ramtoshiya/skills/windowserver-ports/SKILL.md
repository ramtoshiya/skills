---
name: windowserver-ports
description: >-
  Keep macOS tools from filling WindowServer's Mach port space, which kills
  WindowServer and logs the user out. Use when code on a Mac starts processes
  repeatedly that may touch the display: Swift or AppKit helpers, Vision OCR,
  Metal, tests, headless or visible Chrome, Electron, `screencapture`,
  `osascript`, or other CLIs called in a loop. Also use when a Mac logged out
  unexpectedly, WindowServer crashed with OS_REASON_PORT_SPACE, or someone
  asks how many WindowServer ports are in use.
---

# WindowServer port space {:#windowserver-ports}

## The defect {:#defect}

On macOS 27.2.1, WindowServer keeps one dead Mach port name for every client
process that connected to it and then exited. It never frees them. A clean
exit, a kill, and an explicit disconnect before exit all leave the name. When
WindowServer's port space reaches its limit (305,834 names on 27.2.1), the
kernel kills WindowServer and every GUI session logs out. Nothing outside
WindowServer can free the names. Only logout or reboot does. macOS 26.5.1 and
26.6.2 did not keep the names. No later release has been checked yet, so check
again after every macOS update, as [Check after an update](#after-update) says.

Any process that touches the display connects, including ones that never show
a window:

- `NSApplication.shared` connects when it is created.
- Vision text recognition picks a Metal device, Metal asks for the main
  display, and that looks up `com.apple.windowserver.active`. Forcing Vision
  to the CPU does not avoid it.
- Each Chrome or Electron launch connects once, headless included, with the
  GPU disabled too.
- Apple's own `screencapture`, `qlmanage`, and `system_profiler` connect.
  A `screencapture` run left 2 names.

A loop that starts such a process once a second adds at least 3,600 names an
hour. A test suite that starts a few hundred helpers adds a few hundred names
per run.

## Host monitor {:#host-monitor}

To see how close this Mac is, run `windowserver-ports status --json`. Look the
command up on `PATH`. If it is missing, name it and its install step,
`sh tools/windowserver-ports/install.sh` from a clone of the repository that
ships this skill, and stop. Never install, update, or build it yourself.

- `level` is `warning` when the count is at least `threshold` or is projected to
  reach `limit` within 24 hours. `reasons` says which. Tell the user, because
  only logout or reboot clears the names, and do not start a loop that adds
  more.
- `growth` and `projection` are `null` until the history holds an hour of
  readings for the running WindowServer. `projection` is also `null` while the
  count is not growing. A `null` is not proof of safety.
- `monitor.installed` says whether a LaunchAgent records readings and notifies
  the user. `monitor.stale` says that it stopped.
- `windowserver-ports clients --last 1h` counts new connections by client.

## Rules for code that starts processes {:#rules}

1. A process that only reads or writes files starts unable to connect. Either
   run it under
   `sandbox-exec -p '(version 1)(allow default)(deny mach-lookup (global-name "com.apple.windowserver.active"))' <command>`,
   or call `CGSSetDenyWindowServerConnections(true)` first thing in the
   process. Denied, it leaves no name, and Vision OCR gives byte-identical
   output. `sandbox-exec` costs about 5 ms per process and is marked
   deprecated. The deny call is private API, which Chromium's renderer also
   uses.
2. Make the deny structural. A helper registry records whether each helper
   needs the screen, and the launcher denies every helper that does not. A
   repository's test command runs its whole test runner under the deny
   profile. A new helper or test then cannot add names.
3. A process that really needs the screen lives for the whole session. Capture
   inside a process that stays up instead of calling `screencapture` per frame.
   Ask for the frontmost app or the cursor through NSWorkspace or NSEvent in
   that process instead of polling `osascript`.
4. Reuse one browser per run. Open a browser context per page instead of a new
   Chrome. Keep Chrome's sandbox on. `--no-sandbox` would leave no name but
   turns off Chrome's isolation.

## Measure {:#measure}

Count names before and after the work you changed, with nothing else running
that starts GUI processes. The exact count needs root:

```sh
pid=$(pgrep -x WindowServer)
sudo lsmp -p "$pid" | grep DEAD_NAME
```

Without root, `top -l 1 -pid "$pid" -stats pid,command,ports` gives the total
port count. It includes the dead names, and it also moves with live ports that
come and go. On a quiet 27.2.1 desktop it moved by 2 or less within seconds, and
20 connecting processes added about 20. Compare it with an idle interval of the
same length, and wait a few seconds after the processes exit, because the count
first overshoots.

Per-process attribution comes from WindowServer's unified log. Each connection
logs a line with `New conn 0x` and the client's PID. A process that registers as
an app also logs `Process creation:` with its name. Call `/usr/bin/log`,
because zsh has a `log` builtin that takes its place:

```sh
/usr/bin/log show --start "<start>" --end "<end>" \
  --predicate 'process == "WindowServer" AND (eventMessage CONTAINS "New conn 0x" OR eventMessage CONTAINS "Process creation:")'
```

## Check after an update {:#after-update}

After a macOS update, `windowserver-ports probe` checks without root, and the
installed monitor runs it once by itself. By hand, start a tiny program that
connects (for example one that creates `NSApplication.shared` and exits) 10
times, and count dead names before and after. 10 more names means the defect remains. 0 means Apple fixed it.
Then the deny rules cost little to keep, but long-lived processes are no
longer required.

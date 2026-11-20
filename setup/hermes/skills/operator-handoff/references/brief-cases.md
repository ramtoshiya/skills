# Brief cases {:#brief-cases}

Add these to the brief described in Write the brief in `SKILL.md` when the case
applies.

## Web UI or server {:#web-ui}

When the work delivers a web UI or server that the user will open, the
expected result says that it keeps running after the worker finishes, how to
restart it, and that it opens from another of the user's devices.

## Independent pieces {:#independent-pieces}

When the work splits into pieces that each stand on their own, the expected
result says to integrate each piece once it passes the checks, as the
authority paragraph describes, instead of holding all of it for one final
integration. Say the same when a later message adds scope to a running
worker. A brief that integrates only at the end keeps finished work off
`main` and can leave the user wondering why integration is delayed.

## Shared verification device {:#shared-device}

When you start workers that run at the same time and verify on the same
device, such as an app on another Mac, each brief names that device and the
other workers by title, and sets a turn rule. Before using the device or
reinstalling there, the worker tells the others with `bb thread tell`, and
tells them again on release. A reinstall counts as a turn. The brief gives
your thread id, so the worker finds the others' ids with
`bb thread list --parent-thread <your thread id> --json`.

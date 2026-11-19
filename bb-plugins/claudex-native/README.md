# claudex-native

This [bb](https://getbb.app) plugin adds a **Claudex** provider alongside Claude
Code. Claudex threads use the installed [`claudex`](../../tools/claudex/README.md)
wrapper and support checkpoint forks, plan mode, and the accept-edits, auto, and
full permission modes.

## Install

Use macOS with [bb](https://getbb.app) and its CLI, [Node.js](https://nodejs.org/en/download)
22 or newer, and `claudex` installed at `~/.local/bin/claudex`. Use a checkout you
intend to keep.

Link the bridge from the bb installation that runs your server. For the standard
desktop installation:

```sh
cd bb-plugins/claudex-native
app=/Applications/bb.app
bb_package="$app/Contents/Resources/app.asar.unpacked/node_modules/bb-app"
ln -s "$bb_package/server/dist/builtin-plugins/provider-claude-code/dist/host.js" claude-host.local.js
bb plugin build .
bb plugin install .
```

For a desktop app installed elsewhere, set `app` to the actual bundle path. If
your server runs from an npm installation instead, set `bb_package` to the
absolute path of that installed `bb-app` package. Recreate the symlink if the
installation path changes. An update at the same path needs no change to the
link. bb rebuilds path plugins when its version changes.

If you already use Claudex, install from a different provider's thread after
active Claudex turns finish. Install over the existing plugin so bb keeps its
settings. Do not remove it first.

## How it works

bb bundles the linked Claude Code bridge into this plugin's host artifact. The
Claudex worker sets `BB_CLAUDE_CODE_EXECUTABLE` to `~/.local/bin/claudex`. The
built-in Claude Code provider runs in a separate worker and keeps using `claude`.

The bridge comes from an internal path in bb and is not part of the public
plugin SDK. The link and bundles stay local because the bridge includes
third-party code. If the build cannot resolve the link after an update, check
whether the new bb package still ships the bridge at that path.

Tested with bb 0.49.0 and 0.50.1.

## Settings

| Setting | Default | Effect |
| --- | --- | --- |
| Claude Code memory | Off | Enables Claude Code memory in Claudex threads |
| Disable provider subagents | On | Hides Claude Code's own subagent tool |
| Disable Workflow tool | On | Hides the Workflow tool |
| Claude Code sandbox | On | Runs commands in Claude Code's sandbox |

# claudex-native

A [bb](https://getbb.app) plugin that adds a provider named **Claudex**. A
Claudex thread runs the [`claudex`](../../tools/claudex/README.md) command
through bb's own Claude Code provider bridge. It supports checkpoint forks,
plan mode, and the accept-edits, auto, and full permission modes.

The plugin consists of `server.js`, which registers the `claudex` provider and
its settings, and `host.js`. `host.js` loads the bridge from
`vendor/claude-host.js`, then sets `BB_CLAUDE_CODE_EXECUTABLE` to
`~/.local/bin/claudex` for the current user. This order works because the
bridge reads the variable each time it starts a session, not when it loads.

## The bridge is generated on your machine

`vendor/claude-host.js` is not in Git. It is bb's built-in Claude Code
provider bridge from your installed bb app, with two edits. That bundle
includes third-party code, such as the Anthropic Claude Agent SDK. This
repository has not confirmed that the license terms of that code allow
redistribution. So `npm run prepare-vendor` builds the file locally, and
`.gitignore` keeps `vendor/`, `dist/`, and `node_modules/` out of Git.

The script reads the bb app without changing it. It does not use the
network, run an installer, or execute the bridge. It writes nothing until every check below passes:

1. It finds the bb app. With `--app <path>`, it uses only that path. Without
   it, the script tries `/Applications/bb.app`, then `~/Applications/bb.app`,
   and uses the first one that passes every check.
2. It reads `CFBundleShortVersionString` from `Contents/Info.plist` and
   requires the pinned bb version.
3. It requires the pinned sha256 of the built-in bridge at
   `Contents/Resources/app.asar.unpacked/node_modules/bb-app/server/dist/builtin-plugins/provider-claude-code/dist/host.js`.
4. It applies each edit and requires its exact number of matches.
5. It requires the pinned sha256 of the edited result.
6. It writes `vendor/claude-host.js`, then `vendor/claude-host.evidence.json`.
   Each file goes to a unique temporary name first and is then renamed into
   place, so an interrupted run never leaves an unchecked file at either path.

The two edits are:

| Edit id | Change | Reason |
| --- | --- | --- |
| `rate-limit-provider-id` | `{providerId:"claude-code",` becomes `{providerId:"claudex",` | bb shows Claudex rate-limit events under the Claudex provider, not under Claude Code |
| `source-map-comment` | Removes `//# sourceMappingURL=host.js.map` | The source map is not copied, so the reference would point at a missing file |

`PIN` in [`scripts/prepare-vendor.mjs`](scripts/prepare-vendor.mjs) holds
the version, paths, hashes, and edits. Nothing else defines them. The command
line has no option that changes them.

## Compatibility

The plugin works only with this exact input:

| Item | Value |
| --- | --- |
| bb app | 0.49.0 |
| bb plugin SDK | 0.6.132 |
| Claude Agent SDK inside the bridge | 0.3.318 |
| Built-in bridge sha256 | `87b8489ecd259684d16171c74c0fbebba428b0bf9f22e358215a15ad0ce5a406` |
| Generated `vendor/claude-host.js` sha256 | `09194e28c09286433a3ed2b45932d932986c2076a8004ef760a1afa8ea8c2983` |

`package.json` limits the plugin to bb `>=0.49.0 <0.50.0`. After a bb update,
`prepare-vendor` stops with `VERSION_MISMATCH` or `SOURCE_HASH_MISMATCH`. To
support the new version, check the new built-in bridge for both edit targets,
then update `PIN` and this table together.

## Set up

You need macOS, bb 0.49.0 with its `bb` command,
[Node.js](https://nodejs.org/en/download) 22 or newer, and `claudex`
installed at `~/.local/bin/claudex` as its
[README](../../tools/claudex/README.md) describes.

```sh
cd bb-plugins/claudex-native
npm run prepare-vendor
```

If bb is installed somewhere else, pass the app path:

```sh
npm run prepare-vendor -- --app /path/to/bb.app
```

To check an existing `vendor/claude-host.js` and its evidence file without
reading the app again, run:

```sh
npm run prepare-vendor -- --check
```

A failed check prints one line with one of the codes below and exits with
status 1. A wrong option exits with status 2. Other errors, such as a
permission error, print Node's error message.

| Code | Meaning |
| --- | --- |
| `SELECTED_PATH_INVALID` | The `--app` path has no `Contents/Info.plist`. The script does not try other locations |
| `NOT_INSTALLED` | Neither default location has a bb app |
| `VERSION_UNREADABLE` | `Info.plist` has no readable `CFBundleShortVersionString` |
| `VERSION_MISMATCH` | The app is a different bb version |
| `SOURCE_MISSING` | The app has no built-in Claude Code bridge at the pinned path |
| `SOURCE_HASH_MISMATCH` | The built-in bridge differs from the pinned file |
| `EDIT_COUNT_MISMATCH` | An edit target appears a different number of times than pinned |
| `OUTPUT_HASH_MISMATCH` | The edited bridge differs from the pinned result |
| `VENDOR_MISSING`, `VENDOR_INVALID` | `--check` found no generated file, a changed file, or a missing or different evidence file |

When defaults are searched and no app passes, the code comes from the first
app that was found.

## Verify

```sh
npm test
npm run verify-build -- --baseline <installed claudex-native plugin directory>
```

`npm test` uses temporary fixture apps and removes them afterward. It covers
each failure code, path selection, reruns, the command line, and `host.js`
with a stub bridge. It also builds the bridge from the installed bb app into
a temporary directory and checks the pinned hash. That test is skipped when no
bb app is installed. It fails when the installed bb is a different version,
which means the pins need an update. The repository's root `npm test` does not
run these tests.

`verify-build` compares this source with an installed copy of the plugin.
Point `--baseline` at the directory the plugin was installed from, which holds
its `dist/`. The command builds a temporary copy with `bb plugin build` and
requires these results:

- `server.js` and `dist/server.js` are byte-identical to the baseline.
- `dist/host.js` is byte-identical to the baseline. If the baseline's
  `dist/host.js` sets the executable path as a literal string, that string
  must equal `~/.local/bin/claudex` for the current user. The comparison then
  puts that literal assignment in place of this build's assignment.

`bb plugin build` needs no bb server and changes nothing outside the
temporary copy. The command does not run the bridge.

## Install

Install only after `npm run prepare-vendor` succeeds. bb builds a path
install, and the build fails without `vendor/claude-host.js`. Install from a
checkout you keep. When bb removes a worktree it manages, it moves any plugin
installed from that worktree to a preserved copy.

```sh
bb plugin install . --yes
```

If `claudex-native` is already installed from another directory, installing
from this directory restarts the plugin on the new source. bb keeps the
plugin's settings. Whether a running Claudex turn survives the restart has
not been tested. Install when no Claudex thread is working, from a thread that
does not use the Claudex provider. Do not run `bb plugin remove` first,
because it deletes the plugin's settings.

## Settings

| Setting | Default | Effect |
| --- | --- | --- |
| Claude Code memory | Off | Enables Claude Code memory in Claudex threads |
| Disable provider subagents | On | Hides Claude Code's own subagent tool |
| Disable Workflow tool | On | Hides the Workflow tool |
| Claude Code sandbox | On | Runs commands in Claude Code's sandbox |

Tested with bb 0.49.0 and plugin SDK 0.6.132.

# Plugin update review

This macOS tool prepares Git merge candidates for a local marketplace. It opens
one local review page when a scan finds new candidates or preparation problems.
The page shows each worktree, conflicts, revisions, and diffs. A person can
open registered tests in Terminal and apply a reviewed revision. Preparation
runs no tests, models, builds, or agents. The tool does not resolve conflicts.

## Install and configure

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and a
uv-managed Python 3.11 or newer. Git, `open`, `osascript`, and Terminal must be
available. From this repository:

```sh
sh tools/plugin-update-review/install.sh
plugin-update-review configure --repo /path/to/marketplace-checkout
plugin-update-review serve
```

Put `~/.local/bin` on `PATH`. The installer copies the runtime to
`~/.local/share/plugin-update-review/` and links the command in `~/.local/bin`.
It refuses to replace an unrelated command. It does not install plugins or
start a service. Run it again to update the copy. The command uses uv offline
with isolated Python and executes its installed source, regardless of the
current directory.

`configure` creates `~/.config/plugin-update-review/config.json` from the
checkout's marketplace and upstream-fork lists. It groups entries that share a
fork, leaves tests and installation targets empty, and disables marketplace
push. It will not overwrite an existing config. It does not fetch, test,
publish, install, or start anything. Edit the config before serving. The
`--config` option selects another file for `configure` and `serve`.

Configuration is version 1 JSON:

```json
{
  "version": 1,
  "marketplace": {
    "checkout": "/absolute/path/to/marketplace",
    "branch": "main",
    "remote": "origin",
    "push": false
  },
  "sources": [{
    "id": "example",
    "label": "Example skills",
    "fork_url": "https://github.com/example/fork.git",
    "branch": "main",
    "upstream_url": "https://github.com/example/upstream.git",
    "upstream_branch": "main",
    "plugin_names": ["example-plugin"],
    "tests": [{
      "id": "package-check",
      "label": "Check the package",
      "kind": "static",
      "argv": ["uv", "run", "--offline", "--no-project", "--managed-python", "--python", ">=3.11", "--no-config", "--exclude-newer", "3 days", "python", "scripts/build_hermes_plugin.py", "--check"]
    }]
  }],
  "install_targets": [{
    "id": "sync",
    "label": "Sync approved installations",
    "cwd": "/absolute/path/to/marketplace",
    "argv": ["mise", "run", "agents:sync"],
    "env": {}
  }],
  "interval_seconds": 86400
}
```

The example test is the known package check for a fork containing that script.
Register it only for a source that contains the script. A copy is in
[registered-tests.json](templates/registered-tests.json). Register only
commands you have inspected. The tool never discovers test suites. In
particular, do not register a whole test directory that contains live model
tests. A test with `kind` set to `eval` is still a manual button. Use that kind
for a command that can contact a model. Tests run from the candidate worktree.
They receive `AGENTMEMORY_SDK_CHILD=1`, including when a command rebuilds its
own child environment only if that command preserves or explicitly sets it.
A registered `env -i` command must explicitly include `AGENTMEMORY_SDK_CHILD=1`.
Choose a command whose scripts also set it in any environment they rebuild. The
tool cannot inspect arbitrary scripts for environment replacement.

Each installation target has a unique `id`, label, absolute `cwd`, argument
array, and explicit environment additions. Targets run in configuration order
for every applied source. Use only native sync commands you intend to run on
this machine. Keep credentials out of URLs, command arguments, and config.
Use a credential helper or existing environment for Git authentication. Local
repository paths also work as URLs. `marketplace.push` must be true and
`remote` set to push the pin commit. Fork publication always uses the source's
configured URL and branch when Apply is clicked.

## Run and review

`serve` binds only to `127.0.0.1:8765` by default. Use `--port` to choose a
port. It scans on startup and then after each configured interval while the
process is running. After sleep or shutdown, it scans when the process runs
again. It does not guarantee a missed scan at a particular time. To open the
current page explicitly, run:

```sh
plugin-update-review open
```

Use the same `--state-dir` with `open` and `serve` when overriding the default.
Only one server may use a state directory at a time. An unchanged pending
candidate is retained and does not open another tab. If its upstream, fork, or
pins change, the page reports the change and retains the existing worktree.
The person must decide how to proceed. The tool never resets, stashes, repairs,
or deletes worktrees.

Diffs compare each entry's prior pin with the candidate for that entry's
marketplace path, plus tracked staged and unstaged worktree changes. Untracked
file names appear in worktree status. A missing pin object makes its diff
unavailable. Diffs over 500,000 characters are visibly truncated. Inspect the
worktree with Git for the full changes, untracked contents, and conflict detail.
Refresh rereads the worktree. To repair a conflict, work outside the page and
commit the resolution before testing or applying.

The test button opens a Terminal window for the selected registered command.
The result and log identify the candidate commit. Dirty, conflicted, or stale
candidates are refused. Tests are optional and do not approve an update. A
queued or running test whose Terminal process was interrupted may need manual
inspection of its log. No model evaluation runs without its own button click.

Apply publishes the candidate to the fork with a normal non-force push, changes
only the selected marketplace SHA values, and preserves all other manifest
bytes, including line endings. It commits the pin edits locally and pushes the
marketplace only if configured. It then runs installation targets.
The checkout must be clean and on its configured branch. The tool checks the
reviewed head, fork head, and previous pins before mutation. It refuses changed
refs, a dirty checkout, or a stale revision. It does not switch branches or
restart sessions, grant trust, or repair caches.

Application has separate phases, not a transaction across repositories. The
page reports partial progress and failed installation targets. Retry checks
refs and skips a fork push, marketplace commit or push, and installation
targets already recorded as complete. A failed command may have made external
changes before reporting failure. Inspect its log and target state before
retrying. If an interrupted commit leaves the checkout dirty, inspect and
resolve it manually. A crash between an external side effect and its recorded
phase can require manual reconciliation. Never reset or force-push to make a
retry succeed.

## Background service

For a service in a logged-in macOS user session, copy
[launch-agent.plist](templates/launch-agent.plist) to
`~/Library/LaunchAgents/local.plugin-update-review.plist`. Replace
`COMMAND_PATH` with the absolute installed command path and `UV_AND_GIT_PATH`
with a `PATH` that finds uv and Git without an interactive shell. XML-escape
those values. Then run:

```sh
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/local.plugin-update-review.plist
```

The template starts the local server at login and keeps it alive. Its timer is
in the server, so it does not run while the server is stopped or the Mac is
asleep. To stop it, run:

```sh
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/local.plugin-update-review.plist
```

Notifications and browser opening depend on macOS permissions and the logged-in
session. A browser-open failure is recorded in the event log. The page uses a
random per-server token and checks request origins. It is intended for ordinary
local use, not a shared or remotely exposed service.

## State and logs

The default state directory is `~/.local/state/plugin-update-review/`, or
`$XDG_STATE_HOME/plugin-update-review/` when set. It contains caches,
worktrees, `state.json`, the private active `session.json`, `events.jsonl`,
`jobs/`, and `logs/`. Configuration follows `$XDG_CONFIG_HOME` when set.
Event records include scans, candidate revisions, errors, test launches, and
application phases. Test and install output is in private files under `logs/`.
Test output also remains visible in Terminal. Known secret environment values
and configured installation environment values are redacted from captured logs.
Avoid commands that print other secrets, since arbitrary output cannot be
classified reliably. The page does not expose command arguments, environments,
or log contents. Protect the local state and configuration as private files.

Run the tool's non-model tests from the repository:

```sh
uv run --no-project --managed-python --python '>=3.11' python -m unittest discover -s tools/plugin-update-review/tests -p 'test_*.py'
```

# nest

A [bb](https://getbb.app) plugin that lets an agent at any depth start worker
threads. bb accepts a child thread only four levels deep, so `bb thread spawn
--parent-self` fails from a fourth-level thread with `too_deep`. `bb nest
spawn` works from every level.

```sh
read -r -d '' brief <<'BRIEF'
<the complete brief>
BRIEF
bb nest spawn --new-environment worktree --provider claude-code \
  --model claude-sonnet-5-5 --title "Fix the flaky test" --prompt "$brief"
```

The calling thread (`BB_THREAD_ID`) is always the parent. `bb nest spawn
--help` lists every option. They match `bb thread spawn`: `--project`,
`--environment`, `--new-environment`, `--base-branch`, `--provider`,
`--model`, `--reasoning-level`, `--title`, `--prompt`, `--prompt-file`, and
`--json`. `--parent-self` is accepted and changes nothing.

## Install

From this repository:

```sh
cd bb-plugins/nest
npm install
bb plugin install . --yes
```

## How it works

When bb lets the caller take a child, `bb nest spawn` starts a normal child,
exactly as `bb thread spawn --parent-self` would. bb then notifies the caller
when the child finishes.

Otherwise the plugin starts the worker under the nearest ancestor that can
take a child. That ancestor is only a host:

- The worker's parent notifications are off, so the host hears nothing.
- The caller owns the worker's lifecycle, so archiving the caller archives
  the worker and everything the worker started.
- The worker's first message starts with a short note. It names the caller as
  its logical parent and tells the worker not to message the host.
- When the worker ends a turn, fails, or waits on an approval or question, the
  plugin sends the caller a message from the worker. The message says it needs
  no reply and holds up to 4,000 characters of the final reply. That matches
  bb's own child notifications.

`bb nest list --parent <thread>` lists a thread's unarchived workers from
both routes. The `route` column shows `child` or `relay`.

## Sidebar badge

A relay worker appears in the sidebar under its host. The plugin adds a
`↳ <caller title>` badge to its row so you can see who started it:

![Relay workers under their host, each with a badge naming the thread that started it](docs/sidebar-badge.png)

The badge shows only when **Organize → Rows → Metadata** is on in the
sidebar. It is off by default.

## Limits

- `--prompt-file -` is rejected. bb plugin commands receive arguments, not
  multi-line standard input. Read the brief into a variable with `read -r -d
  ''` as shown above, or pass a file path. `--prompt-file` reads the file on
  the caller's machine, relative to the caller's directory.
- A relay worker's result arrives as a message in the caller's conversation,
  not as a bb child notification. The caller cannot `bb thread wait` for the
  relay message itself, but it can wait on the worker thread.
- Relays are sent when bb emits the worker's event. If the plugin is not
  running at that moment, for example during a bb restart, that result is not
  relayed. Read it with `bb thread output <worker>`.
- `bb thread update --parent-thread` cannot move a thread below four levels
  either. Relay workers stay under their host.
- The plugin uses experimental plugin APIs, which a bb update can change or
  remove: `threads.experimental_listPluginMetadata` for `bb nest list` and the
  badge, and `experimental_threadRowMetadata` and
  `experimental_useRpcKeyedQuery` for the badge.

## Development

```sh
npm run typecheck
npm test
bb plugin build .
```

Tested with bb 0.50.1 and plugin SDK 0.6.132.

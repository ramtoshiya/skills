# Claudex Lean coordination

Claudex Lean coordinates coding work through independent Agent Deck CLI workers.
The lead delegates implementation and product tests, then requests independent
verification of the actual candidate. Raw worker logs stay outside the lead's
context. Multica owns tasks and user-facing reporting. Agent Deck owns execution,
messaging, worktrees and session lifecycle. No conductor service or hcom runtime
is required, and native Claude delegation is not a fallback.

Existing agents and the original [Claudex pipeline](claudex-pipeline.md) are
unchanged. Do not migrate ongoing work merely to test the separate configuration.

## Operator setup

Install [Agent Deck](https://github.com/asheshgoplani/agent-deck) and its required
tmux dependency using the upstream instructions. The skill never installs or
updates missing tools. Provision a private Agent Deck profile and short tmux
socket directory. Set `worktree.branch_prefix = ""` in that profile's effective
configuration, so Agent Deck does not rewrite a precreated candidate branch.

The worker CLI must already authenticate normally and start without interactive
shell-manager setup. Reuse normal authentication without copying credentials or
requiring a new empty provider home. A separate provider home needs its own login.
Configure explicit worker permissions without YOLO or bypass defaults. Native
Agent Deck hooks can be passed through session-local Claude `--settings`, leaving
shared hooks untouched. Enable the native session, prompt, tool, stop and end
callbacks needed for identity and message handling. The native hook handler is
`agent-deck hook-handler`. Follow the installed version's hook contract.

For a Claude worker, disable native Agent, Task, Workflow and peer messaging
fallbacks. Grant the private completion directory through `--add-dir {run_dir}`.
If tool execution is sandboxed, its approved Git commit and Agent Deck control
operations need explicit permissions to reach Git metadata and the tmux socket.
These control-plane allowances are not a security sandbox for hostile workers.
Do not grant broader access merely to turn a denied operation into a pass.

Agent Deck's XDG roots can also relocate other tools' data lookup. Preserve an
already installed managed Python directory through `UV_PYTHON_INSTALL_DIR` when
existing offline hooks need it. Do not silently install another interpreter or
change shared hooks to hide a startup failure.

Store the private runtime JSON at
`$HOME/.config/claudex-lean/agent-deck.json`, mode `0600`. It contains:

- `agent_deck`: absolute installed executable path.
- `worker_command`: argv array for the normally authenticated coding CLI.
- `profile`: the dedicated Agent Deck profile.
- `tmux_path`: absolute directory containing the installed tmux executable.
- `tmux_socket`: the profile's isolated socket name.
- `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`, and
  `TMUX_TMPDIR`: existing absolute directories, owned by the operator, mode `0700`.
- `trust_folder`: optional boolean, false by default. Explicit opt-in allows native
  startup settling for the owned project. Unknown prompts stop dispatch.

The adapter removes inherited Multica task credentials and parent CLI session
identity from its launch environment. An existing tmux server can retain older
environment state. Provision the dedicated socket from a clean launch, not a
shared server. This does not isolate disk-based authentication or provide hostile
multi-tenant containment. Do not commit runtime configuration, transcripts or
completion records.

## Separate Multica configuration

Package the complete `setup/agents/claudex-lean/skill/` directory as a local zip
and import it through Multica's supported skill import command. Bind it only to
the separate agent and use `lead-instructions.md` for that agent's instructions.
An authorized refresh preserves the skill ID and bindings. Do not inherit the
original pipeline skill or role-root arguments. Secret and machine-local agent
fields must not be fetched with task credentials.

The package has no globally registered roles or shared-profile synchronization.
Its relevant files are `scripts/agent_deck.py`, `scripts/report.py` and
`evals/evals.json`. Missing local runtime setup is a deployment requirement, not
permission to invent a substitute backend.

## Execution and verification

Write a scoped prompt and create a private run directory outside product content.
Run the adapter in the foreground:

```sh
uv run --no-project python -I /path/to/claudex-lean/scripts/agent_deck.py \
  --config "$HOME/.config/claudex-lean/agent-deck.json" \
  --repo /path/to/input-checkout --prompt /private/prompt.md \
  --run-dir /private/builder --role builder --max-seconds 240
```

The adapter pins a fresh branch to the input HEAD before requesting its worktree.
A different initial HEAD is rejected before work starts. A completed builder must
return a committed, clean candidate. Dirty source files are preserved and do not
block a separate worker checkout.

For independent verification, point `--repo` at the builder's candidate worktree
and use `--role reviewer --candidate FULL_COMMIT_SHA`. The reviewer receives a
fresh CLI context and worktree, inspects the requested behavior and leaves the
candidate unchanged. Its conclusion still needs actual evidence. A worker-written
`completion.json`, idle status, delivered message or zero exit is not independent
verification.

Workers can message peers and create authorized children using native Agent Deck
commands under the same profile, socket and worker settings. Preserve parent links
and an agreed finite child budget. Use deferred sends for busy peers. Plain restart
does not establish inbox replay, and transport deduplication does not make product
operations idempotent.

The adapter stops discoverable owned sessions child-first and keeps worktrees.
It re-enumerates descendants after stopping them and verifies the settled graph.
Four expanding passes return unresolved cleanup rather than a false success.
It does not stop unrelated sessions or delete dirty work. On unresolved cleanup:

```sh
uv run --no-project python -I /path/to/claudex-lean/scripts/agent_deck.py \
  --config "$HOME/.config/claudex-lean/agent-deck.json" \
  --run-dir /private/builder --cleanup-only
```

Recovery does not relaunch the product job. Inspect `run.json` and the recorded
native session identity first. Detached, unlinked workers and an ambiguous add
that appears after lookup still require operator reconciliation. Private
`control-error.json` contains bounded native control-command diagnostics, not a
public result. Collect owned processes before ending the lead turn.

## Progress reporting

Give short natural-language Multica updates around every ten minutes of active
silence. State completed work, current activity, next action and any blocker.
Exact-second timing is not a completion gate. Keep foreground work units shorter
than the reporting interval and post due updates between commands. Give the outer
tool enough time for startup and owned-session cleanup.

`scripts/report.py` remains available for compatible foreground process-group
commands. It captures private command output and reconciles ambiguous comment
delivery through a unique marker and the required reply parent. It is not an
exactly-once guarantee or a substitute for final delivery. Do not wrap the detached
Agent Deck adapter in it: its five-second termination grace can kill the adapter
before tmux cleanup completes. Agent Deck execution uses the adapter's finite
lifetime and cleanup-only recovery instead.

## Validation

Run the repository checks in `AGENTS.md`. Focused adapter and reporting tests use:

```sh
uv run --no-project python -m unittest discover -s test -p 'test_claudex_lean*.py' -v
```

Controlled CLI fixtures cover candidate binding, startup refusal, completion,
cancellation, owned cleanup and recovery. They do not prove real Agent Deck
behavior. Verify the installed runtime with an actual CLI worker, the correct
linked-checkout base, completion-file access and process cleanup before assigning
product work. A real bug still needs its original failure reproduced and an
independent candidate-bound check. Policy evaluations are not that evidence.

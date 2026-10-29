# Claudex Lean coordination

Claudex Lean keeps implementation and product tests in independent Agent Deck CLI
workers. The lead agrees scope, coordinates work, obtains fresh verification and
reports through Multica. Implementation workstreams retain their session and
worktree across retries. Review starts in a fresh context at the actual candidate.
The original [Claudex pipeline](claudex-pipeline.md) and existing agents are unchanged.

## Operator setup

Install [Agent Deck](https://github.com/asheshgoplani/agent-deck) and tmux through
the upstream instructions. The skill never installs or updates tools. Keep the
working operator runtime rather than rebuilding profiles for each task.

Use a dedicated Agent Deck profile and short tmux socket directory. Set
`worktree.branch_prefix = ""`, so the backend does not rewrite the branch pinned
to the requested input commit. Reuse normal provider authentication without copying
credentials or requiring a new empty provider home. The verified integration uses
Claude Code with session-local native Agent Deck hooks. Other harnesses need their
native wait/output contract checked before claiming support.

Store `$HOME/.config/claudex-lean/agent-deck.json` as a private `0600` file with:

- `agent_deck`: absolute installed executable.
- `worker_command`: normally authenticated CLI argv, with literal `{run_dir}`
  substitution available for an additional working-directory allowance.
- `profile`, `tmux_path` and `tmux_socket`: the dedicated profile, absolute directory
  containing tmux, and isolated socket name.
- `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`, and
  `TMUX_TMPDIR`: existing operator-owned absolute directories, mode `0700`.
- `trust_folder`: optional, false by default. Explicit opt-in permits native
  settling for the owned project. Unknown prompts stop dispatch.

Resolve Node, its matching npm, and uv from working installations rather than
inactive shims. Preserve the managed Python lookup and required release-age policy
when XDG roots change. Use fork-owned uv/npm caches with scoped sandbox write
allowances. Required local-server tests need local binding, with listeners kept
short-lived and on loopback. Do not disable guards or skip repository checks.

Preapprove required operations and use Claude's `dontAsk` mode for unattended
workers. Native Agent/Task/Workflow fallback is disabled. Git metadata and Agent
Deck control operations need their approved permissions. These allowances are not
hostile-worker containment. An existing tmux server may retain old environment
state, so provision the dedicated socket from a clean launch. Shared provider
hooks, credentials and global Git settings do not belong in this package.

## Use and recovery

Import the complete `setup/agents/claudex-lean/skill/` archive through Multica and
bind it only to the separate agent. Use `lead-instructions.md` for that agent.
A supported refresh preserves the skill ID and bindings. Runtime configuration,
logs and workstream records stay private and outside product content.

Use the installed `scripts/agent_deck.py --help`. Start with `--config`, `--repo`,
`--prompt`, a fresh private `--run-dir` and `--max-seconds`. Continue with the same
config/run directory, `--resume` and an explicit new prompt. For a fresh review,
add `--candidate FULL_SHA` to pin unchanged candidate state across its units.
`--cleanup-only` needs only config and run directory and does not start work.
An ambiguous send requires native reconciliation before `--ack-ambiguous` can
permit a different continuation. Give a worker the requested behavior, permitted
files/effects and required checks. The adapter pins the input HEAD and uses native correlated
replies. There is no worker-written completion file or separate reporting service.
A received reply is not task success. Inspect its Git candidate and evidence, then
obtain independent verification of the original failure and agreed safety scope.

Continue an existing implementation session/worktree after inspecting its record
and native state. Do not blindly repeat an ambiguously delivered operation.
Independent review needs a fresh context, not every implementation retry. Parallel
workstreams may have separate owners. Authorised children retain native parent links and scoped
settings. A restart is not proof of inbox replay or application idempotency.

The adapter collects discoverable owned processes before returning and retains
worktrees. Cleanup recovery does not relaunch the product job. Unlinked workers
and a late ambiguous launch still require explicit reconciliation. Do not delete
dirty work or stop unrelated sessions to make cleanup appear successful.

The lead gives short natural-language Multica updates around ten minutes of active
silence, between bounded foreground calls. Internal events do not reset that clock.
This is approximate lead-owned reporting, not an independent timer guarantee.
Repository policy owns required checks. Additional roles and repeated full-suite
runs are not automatic phase gates, and unchanged-candidate evidence may be reused
where that policy permits.

## Validation

Run the checks in `AGENTS.md`. Focused adapter tests use:

```sh
uv run --no-project python -m unittest discover -s test -p test_claudex_lean_agent_deck.py -v
```

Controlled CLI tests check native result handling, candidate binding, resumption
and cleanup. They do not prove live backend behavior. Verify real correlated
replies and stopped-session context/worktree continuity before replacing a native
contract. Product acceptance still requires the actual failure case and fresh
candidate-bound verification, not merely flags, an idle session or a zero exit.

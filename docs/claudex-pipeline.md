# Claudex build pipeline

A Multica lead can coordinate builds with seven centrally installed Claude Code
roles without installing workers into every repository or exposing them to every
Claude session. The package contains the lead's workspace skill, native role
prompts, an ownership-safe installer, and bounded control-data validation. It
does not create or configure a Multica lead, squad, property, or assignment.

## Install and remove

From this checkout, with [uv](https://docs.astral.sh/uv/) and a managed Python
3.11 or newer already installed:

```sh
mise run agents:sync -- --host claude --plugin claudex-pipeline
mise run agents:status -- --host claude --plugin claudex-pipeline
```

Normal `agents:sync` also installs the package when Claude Code is on `PATH`.
The destination follows `CLAUDE_CONFIG_DIR`, defaulting to
`~/.claude/claudex-pipeline`. It is an inert directory until a session adds it.
Nothing is installed into `~/.claude/agents` or repository agent directories.

For a custom destination, or without mise, run:

```sh
uv run --offline --no-project --managed-python --python '>=3.11' python -I setup/agents/claudex-pipeline/pipeline.py install --destination "$HOME/.claude/claudex-pipeline"
```

Repeat installation after updating the checkout. `status` compares the installed
files with this revision. `uninstall` removes only recorded owned files and the
ownership manifest, leaving unrelated files and directories intact. Use the
repository copy of `pipeline.py` for uninstall, then omit this component from
subsequent sync selections if it should stay absent.

Identical existing files can be adopted. Differing unowned files, edited or
missing owned files, and symlinked package paths are conflicts. Resolve or
preserve them manually. Use a physical absolute destination path, including
physical parent components rather than OS aliases such as `/tmp` on macOS.
The installer checks all managed files before changing
any and replaces each file atomically. It is not a filesystem transaction or a
sandbox against another process racing writes. Serialize installation and do
not edit managed files during it. No `--force` mode is provided.

## Configure the lead

Import `setup/agents/claudex-pipeline/skill/` as a workspace skill using the
workspace's authorized skill-import workflow, and bind it only to the lead.
The skill is not a shared Claude/Codex/Pi/Hermes plugin. Keep the repository
revision and workspace skill source revision aligned when updating it.

Add the installed root to the lead's Claude Code arguments:

```sh
--add-dir /absolute/path/to/.claude/claudex-pipeline
```

Keep project settings enabled. `--bare` disables the Agent tool, and
`--setting-sources ''` prevents these added-directory role definitions from
loading on the tested runtime. `--setting-sources project` works for an isolated
probe. Restart sessions after changing the package, because added-directory
agent files are not watched. See the official
[custom subagent documentation](https://code.claude.com/docs/en/sub-agents).

Confirm the workspace already has the agreed lifecycle states,
`claudex-pipeline` opt-in label, and `Claudex Candidate`, `Claudex Review`, and
`Claudex Risk` properties. Their definitions and lead creation remain workspace
administration tasks. Risk is consequence, not test completeness.

Before product work, verify project-local `AGENTS.local.md` and its
`CLAUDE.local.md` import are present in the outer and native worktrees. Use the
tracked `.worktreeinclude` and the outer-worktree copier. This package does not
copy private project policy, grant credentials, or authorize integration.

## Worker capabilities

| Role | Available tools | Responsibility |
| --- | --- | --- |
| explorer | Read, Glob, Grep | Find scope and prerequisites |
| builder | Read, Glob, Grep, Edit, Write | Implement in native worktree isolation |
| reviewer | Read, Glob, Grep | Blind first-pass review of an exact SHA |
| security-reviewer | Read, Glob, Grep | Separate conditional security review |
| runner | Read, Glob, Grep | Request and assess behavior verification |
| reconciliation-builder | Read, Glob, Grep, Edit, Write | Repair conflicts/findings in native worktree isolation |
| worklog-reporter | None | Draft four fields from supplied bounded state |

All roles exclude shell, delegation, network and tool-discovery tools. The
reporter cannot read files. Worker instructions prohibit all Multica mutations.
The explicit allowlists also exclude MCP/platform tools. These are Claude Code
tool boundaries, not an OS sandbox. Product code and project instructions still
need normal trust and review.

The lead brokers approved repository test and Git commands. The runner does not
execute tests itself. This avoids granting a general shell that could also run
Multica. Inspect requested commands against local policy rather than executing
worker text blindly. A missing behavioral result cannot become a passing verdict.
The lead may commit and integrate authorized work but never patch product code.
Use a builder for every correction and re-review the new SHA.

## Model and effort selection

Roles contain no model or effort pin. For each work unit, start a fresh Claudex
coordinator with the selected full model ID and explicit `--effort`, and set
`CLAUDE_CODE_SUBAGENT_MODEL` to that ID. Invoke the named role through the native
Agent tool with no model alias override. Use one selected work unit per session
when choices differ. A reviewer and security reviewer never reuse builder context.
Record the observed child model and reject an unexpected alias or fallback.
This mechanism uses one copy of each role protocol, rather than model-specific
agent files.

`pipeline.py select-model --model MODEL [--file RECEIPT] --work-kind KIND` applies
this admission matrix. A receipt is trusted only after the lead matches its
native invocation evidence. Schema validation cannot authenticate a caller's JSON.

| Model tier | Work kind | Required confirmed actual effort |
| --- | --- | --- |
| Sol | Any | May be unknown, record null |
| Luna | Bounded, low-uncertainty transformation | off, minimal, low, or max. Choose the lowest sufficient setting |
| Luna | Substantive reasoning | max |
| Terra | Any | max |

A low risk label does not make a task trivial. The worklog reporter is a typical
bounded transformation. Use `--work-kind bounded` only after checking scope and
uncertainty. Unconfirmed required effort falls back to Sol or direct lead drafting.

The tested CLI accepts low/medium/high/xhigh/max through `--effort`, not off or
minimal. Do not silently translate off/minimal to another setting. The receipt
format permits them for a runtime that can supply trusted confirmation.
The current native stream exposes the actual child model but not effective
child effort. Luna low and max probes both complete, but neither qualifies as
confirmed effort. Therefore production Luna/Terra admission remains closed on
this evidence path. A requested flag, frontmatter, native Agent argument or
worker self-report is not proof of actual effective effort. The manager can use
Sol now or add trusted runtime effort instrumentation before enabling those tiers.

## Control records and recovery

`pipeline.py validate-control --file ENVELOPE` checks a closed v1 schema:

- Canonical UUIDs: `issue_id`, `attempt_id`.
- Role suffix: `role`, such as `builder` or `security-reviewer`.
- Full Git commit IDs: `base_sha`, `candidate_sha`.
- SHA-256 change detector: `contract_digest`.
- Integer `cycle` from zero through three and nullable `strategy_change`.
  Cycle three requires model, worker, approach, or environment as the changed axis.
  The lead must verify that a real change occurred, not merely set this field.
- `payload_ref` and at most sixteen `evidence_refs`, as safe opaque references.
- Integer `version`, exactly one.

A receipt adds `session_id` (the native coordinator UUID), `worker_id` (the native
worker's opaque ID), nullable `actual_model`, nullable `actual_effort` and
`effort_source`, `status` (pass/needs_work/blocked/probe), `summary_ref`, and
`evidence_refs`. It retains issue, attempt, role and candidate SHA, but does not
repeat base, digest, cycle, strategy or payload. The lead enriches runtime
provenance after the worker returns. Workers must not invent it.

Validate with `validate-receipt --file RECEIPT --control ENVELOPE` to reject a
stale candidate or mismatched issue, attempt or role. Keep findings and role
payloads in Markdown. Persist JSON only after inspecting it for sensitive data.

`save-active --file STATE --repo REPO` takes `version`, a validated `control`,
`receipt_refs`, and nullable `blocker`. A blocker has `actor_ref`, `condition_ref`
and `evidence_ref`, pointing to the bounded Markdown explanation. The command
verifies commit objects and atomically writes:

```text
<git-common-dir>/claudex-pipeline/v1/issues/<issue-uuid>/active.json
```

Place each attempt's handoff and receipts in `attempts/<attempt-uuid>/` beside
that pointer. Worktrees share this issue-local state. No repository-wide index
is maintained. Recovery checks current comments, actual worker/session state,
Git objects, worktree ownership and evidence before resuming.

Records are limited to 32 KiB. References cannot be absolute paths, URLs,
traversals or arbitrary prose. Structural validation is not secret detection.
Keep raw transcripts, logs, secrets and environment dumps in neither records
nor public test output. Native transcript/artifact storage owns raw evidence.

## Checks

```sh
npm test
uv run --offline --no-project --managed-python --python '>=3.11' python -I test/claudex-pipeline-live.py setup/agents/claudex-pipeline --output /path/to/private/discovery.json
uv run --offline --no-project --managed-python --python '>=3.11' python -I test/claudex-pipeline-live.py setup/agents/claudex-pipeline --writer --output /path/to/private/writer.json
uv run --offline --no-project --managed-python --python '>=3.11' python -I test/claudex-pipeline-live.py setup/agents/claudex-pipeline --role worklog-reporter --model gpt-6-luna --effort low --fallback-model gpt-6.1-sol --output /path/to/private/luna-low.json
uv run --offline --no-project --managed-python --python '>=3.11' python -I test/claudex-pipeline-live.py setup/agents/claudex-pipeline --role worklog-reporter --model gpt-6-luna --effort max --fallback-model gpt-6.1-sol --output /path/to/private/luna-max.json
```

Live probes require an already-configured `claudex` and paid upstream access.
They create disposable Git repositories, use foreground native Agent spawns,
validate JSON handoffs against the probe SHA, and check actual worktree files.
They disable hooks and MCP only in their disposable sessions. They never use
`--agent` as a substitute for native spawn. Subprocess groups are bounded by a
timeout and terminated before cleanup. Output files contain allowlisted summary
fields only, not response or transcript bodies. `passed` covers the native
capability being probed, not production model-effort admission.

Tested with Claude Code 2.1.309 through Claudex, GPT-6.1 Sol, and GPT-6 Luna.

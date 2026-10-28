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
files with this revision. The installed package includes the skill's evaluation
fixtures as well as its prompt, helper and seven role definitions. `uninstall`
removes only recorded owned files and the ownership manifest, leaving unrelated
files and directories intact. Use the
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

## Package fingerprint

Both source and installed helpers print the same full 64-character digest:

```sh
uv run --offline --no-project --managed-python --python '>=3.11' python -I setup/agents/claudex-pipeline/pipeline.py package-fingerprint
uv run --offline --no-project --managed-python --python '>=3.11' python -I "$HOME/.claude/claudex-pipeline/pipeline.py" package-fingerprint
```

Use `--source ROOT` to inspect another package root. `agents:status` checks source
and installed equality and reports this full value. The digest is SHA-256 of the
logical relative-path to per-file SHA-256 mapping, serialized with Python's
`json.dumps(mapping, sort_keys=True)` and encoded as UTF-8. Serialization has no
indentation or trailing newline and uses the default JSON separators, including
spaces. This matches `setup/agents/sync.py`, not a hash of concatenated file bytes.

The ownership manifest is checked but excluded from the logical mapping. As in
the synchronizer, `.git`, `__pycache__`, `.DS_Store`, `.in_use` and files ending
in `.pyc` are excluded. Other extra files prevent a canonical fingerprint even
though uninstall preserves unrelated files. Symlinks in included package paths,
missing or modified owned files and invalid ownership manifests are conflicts.
A digest detects change, it does not authenticate who installed the package.

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

The local-policy bridge is optional unless source repository or project
instructions explicitly require it. Its members are `AGENTS.local.md`,
`CLAUDE.local.md` importing it, and a tracked `.worktreeinclude` selecting both.
If any member exists, including a dangling symlink, validate the complete bridge
as regular non-symlink files, its import and manifest selection, the outer-worktree
copier, and identical propagation into outer and native worktrees. A partial or
required bridge fails preflight with the specific missing or invalid check.

If no member exists and policy does not require one, record
`absent-not-required` and continue using the issue contract, ordinary tracked
repository instructions when present, Multica runtime instructions, and the
bound workspace skill. `AGENTS.md` and `CLAUDE.md` are optional ordinary
instructions, not bridge members. A repository with none of these five files
can proceed. Do not invent missing policy or turn a failed check into absence.
This package does not copy private project policy, grant credentials, or
authorize integration.

## Repository baseline

Preflight requires clean product content and an unchanged index, not an empty
`git status`. A task runtime can supply untracked `.claude/`, `.multica/` and
`CLAUDE.md` before native work starts. Inspect their ownership and confirm that
Multica supplied them before the agent began. Their names are not an ownership
guarantee. Resolve unexpected product-owned untracked content before a probe.

A tracked `CLAUDE.md`, including a one-line `@AGENTS.md` import, can carry a
proven startup overlay. The helper permits it only as the sole dirty tracked
path, with no staged changes, conflict stages, or persistent index flags. It
requires the exact index bytes followed by the Multica writer's two-LF managed
separator and one complete appended runtime block. The block must have the
exact begin/end markers, original-boundary metadata matching the tracked CR/LF
suffix and blank-file state, the runtime heading, and the matching agent identity.
Prepended blocks, legacy blocks without boundary metadata, formatter-normalized
boundaries, duplicate or malformed markers, markers already in the tracked
content, mode changes, and edits outside the managed insertion fail closed.

Provenance must be a bounded untracked regular `.multica/daemon_task_context.json` in this
checkout, with `managed_by` equal to `multica-daemon-task`, canonical `agent_id`
and `issue_id` UUIDs, and at most an optional canonical `chat_session_id` UUID.
Unknown or duplicate fields and symlinked provenance are rejected. Parent-directory
markers are not borrowed. This is a structural check, not cryptographic task
authentication: the daemon marker has no checkout path, signature, or timestamp.
The operator must confirm runtime ownership and startup timing before capture.
A forged local marker and matching body cannot establish that ownership.

Capture a bounded baseline in private storage outside the worktree:

```sh
uv run --offline --no-project --managed-python --python '>=3.11' python -I setup/agents/claudex-pipeline/pipeline.py capture-baseline --repo "$PWD" --file /path/to/private/baseline.json
uv run --offline --no-project --managed-python --python '>=3.11' python -I setup/agents/claudex-pipeline/pipeline.py verify-baseline --repo "$PWD" --file /path/to/private/baseline.json
```

Capture before the probe and verify afterward. The record includes initial
status, HEAD, branch, semantic index entries, registered worktrees and file modes
and SHA-256 fingerprints. Baseline schema version 3 also records tracked dirty
status and the complete overlay fingerprint, block offsets and digest, tracked
object and digest, and the local provenance fields and fingerprint. Verification
requires this entire record to remain identical. The semantic index records each path,
mode, object ID, conflict stage and persistent assume-unchanged, skip-worktree
and intent-to-add flags. Stat-cache, cache-tree, fsmonitor-valid cache state and
index encoding changes are ignored. Ordinary Git reads can refresh these without
changing staged content. Older baseline schemas are rejected, never interpreted
as semantic records. Ignored runtime startup files are included. Inventory is
limited to 2,048 entries and 32 MiB of file content. Semantic index entries are
separately limited to 2,048. Baseline JSON and each Git inventory output have a
2 MiB size limit, separate from the unchanged 32 KiB control-envelope limit.
Capture writes deterministic compact JSON. Verification accepts compact or
formatted records within the baseline limit without dropping evidence.
Exceeding a limit rejects capture or verification, it does not omit entries. Git-ignored content
outside the runtime startup paths is not covered. Serialize work in the checkout
because this is a comparison helper, not a filesystem sandbox or atomic snapshot.
The record contains paths and status, so do not publish it without inspection.

An unchanged runtime baseline passes. Additions, removals, content or mode changes,
index changes, tracked diffs, HEAD or branch changes and worktree changes fail.
For authorized implementation work, preserve the original record and separately
review the explicitly allowed delta. Never silently delete, ignore, stage or
commit runtime files to make cleanliness pass, or recapture a baseline to hide a
mutation. The helper never changes repository files or Git state.

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

Derive the coordinator's tool union from the selected role frontmatter:

```sh
ROOT="$HOME/.claude/claudex-pipeline"
TOOLS=$(uv run --offline --no-project --managed-python --python '>=3.11' python -I "$ROOT/pipeline.py" dispatcher-tools --role explorer)
# Supply both flags to the fresh coordinator, alongside its model and effort:
# --tools "$TOOLS" --allowedTools "$TOOLS"
```

The helper prints `Agent` plus that role's declared tools. An Agent-only parent
restriction also restricts the child, so it prevents an explorer's file checks.
The reporter union is only `Agent`. Writer unions include only their declared
file tools in addition to `Agent`, not shell or platform tools. Worker frontmatter
still applies its own narrower boundary.

The coordinator system prompt must permit exactly one `Agent` invocation naming
the selected `claudex-ROLE`, wait for that worker, and prohibit using the extra
role tools itself or invoking other agents. This coordinator restriction is a
prompt contract, not a native per-caller tool sandbox. Inspect native events and
reject direct coordinator file-tool calls, wrong roles, extra spawns or unexpected
worker tools. Use a fresh coordinator for each selected role.

All roles exclude shell, delegation, network and tool-discovery tools. The
reporter cannot read files. Worker instructions prohibit all Multica mutations.
The explicit allowlists also exclude MCP/platform tools. These are Claude Code
tool boundaries, not an OS sandbox. Product code and project instructions still
need normal trust and review.

The reporter returns exactly four short Markdown bullet fields, in order:
`Completed work`, `Current activity`, `Next step`, and `Blocker`. Each field is one
nonempty line. `pipeline.py validate-worklog --file DRAFT` checks the entire
unmodified response and rejects extra headings, text, JSON, fences, sentinels,
hidden machine blocks and runtime metadata. Every worker returns role payloads
only, never runtime receipts or provenance. The lead assembles and validates the
receipt from trusted native runtime evidence
after the worker returns. Do not trim extra output to pass validation.

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
uv run --offline --no-project --managed-python --python '>=3.11' python -I test/claudex-pipeline-live.py "$HOME/.claude/claudex-pipeline" --role worklog-reporter --output /path/to/private/reporter.json
uv run --offline --no-project --managed-python --python '>=3.11' python -I test/claudex-pipeline-live.py "$HOME/.claude/claudex-pipeline" --output /path/to/private/discovery.json
uv run --offline --no-project --managed-python --python '>=3.11' python -I test/claudex-pipeline-live.py setup/agents/claudex-pipeline --writer --output /path/to/private/writer.json
uv run --offline --no-project --managed-python --python '>=3.11' python -I test/claudex-pipeline-live.py setup/agents/claudex-pipeline --role worklog-reporter --model gpt-6-luna --effort low --fallback-model gpt-6.1-sol --output /path/to/private/luna-low.json
uv run --offline --no-project --managed-python --python '>=3.11' python -I test/claudex-pipeline-live.py setup/agents/claudex-pipeline --role worklog-reporter --model gpt-6-luna --effort max --fallback-model gpt-6.1-sol --output /path/to/private/luna-max.json
```

Live probes require an already-configured `claudex` and paid upstream access.
They run one fresh coordinator per role in disposable Git repositories, enforce
one named foreground Agent spawn and no direct coordinator tools, validate exact
role payloads against the probe SHA, and reject worker provenance. Explorer must
use Glob, Read and Grep to return a token from a physical file. Both writer roles
use Markdown implementation summaries and physically write only the authorized
fixture in isolated worktrees. Their outer-worktree delta must contain only
native worktree entries, preserving every pre-existing file. The default run
checks all seven roles. Use `--writer --role builder --role reconciliation-builder`
to select only the two writer probes.
The reporter probe parses the complete native worker text instead of a JSON
handoff. It supplies bounded issue, attempt and candidate references, an explicit
reporting deadline and concrete facts, then checks exact transformation and zero
tool calls. Startup-sentinel instructions exercise output isolation. Read-only
probes also verify preservation of pre-existing runtime-owned untracked files.
Install the candidate into a disposable private root to probe it without updating
the shared installation.
They disable hooks and MCP only in their disposable sessions. They never use
`--agent` as a substitute for native spawn. Subprocess groups are bounded by a
timeout and terminated before cleanup. Output files contain allowlisted summary
fields only, not response or transcript bodies. `passed` covers the native
capability being probed, not production model-effort admission.

Tested with Claude Code 2.1.309 through Claudex, GPT-6.1 Sol, and GPT-6 Luna.

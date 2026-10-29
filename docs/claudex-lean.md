# Claudex Lean coordination

Claudex Lean is a separate coordination policy and timed-reporting package.
The lead delegates product implementation and tests, uses independent verification,
and keeps raw worker logs out of its own context. It does not require a complete
repository inventory or role-specific receipts for every source change.

The package does not include a worker backend. It cannot yet dispatch product work,
exchange worker messages, or prove external worker cleanup. It never falls back to
native Claude delegation. Select and verify an external backend separately before
assigning product implementation. Existing agents and the original
[Claudex pipeline](claudex-pipeline.md) are unchanged.

## Files

- `setup/agents/claudex-lean/lead-instructions.md`: portable lead instructions.
- `setup/agents/claudex-lean/skill/`: an independently importable Multica skill,
  its reporting script and policy evaluation cases.
- `test/test_claudex_lean.py`: reporting cadence, transport recovery, command
  lifetime and cancellation tests.

The skill uses repository instructions and current user authority. Security review
is selected for concrete changes to actual boundaries, not every mention of data.
Accepted risks and optional hardening do not silently grow the completion gate.
Existing user changes and runtime instructions remain protected without imposing a
universal pristine-tree or cumulative byte-limit requirement.

## Separate Multica configuration

Package the `skill/` directory as a local zip and import it with Multica's supported
skill import command. Bind the resulting new skill ID only to the new configuration.
Use `agent copy` to preserve the source agent's portable model and runtime settings,
then replace instructions with this package's lead instructions. Do not inherit the
original pipeline skill or its role-root `--add-dir`. Preserve unrelated arguments
and settings when adapting an existing configuration. Secret and machine-local
fields are not copied by that command and must not be fetched using agent credentials.

A copied agent plus this skill is a coordination foundation, not a verified coding
runtime. Keep backend selection and deployment readiness explicit. Do not migrate
existing issues or modify the source agent merely to test the copy.

The package has no globally registered native roles, no required tool installation,
and no automatic shared-profile synchronization. Import the complete skill archive,
including `scripts/report.py`, so a refreshed task receives the reporting code.

## Foreground progress reporting

The reporting script wraps an approved command, captures its stdout/stderr in a
private records directory, and posts a worklog when 600 seconds pass without one
of its own confirmed posts. Internal status updates do not reset the timer. Supply
`--last-visible-at` with the run start or last successful visible response timestamp,
so setup time before launching the loop is not lost. Use one reporting owner. It does
not query or reset its timer for comments posted by another process.

The wrapped command is supplied by the separately configured backend. It must
collect its workers and exit on completion, failure, cancellation or a real external
blocker. The reporting script does not infer lifecycle from status text. Do not use
it to make the lead execute product tests. It creates no daemon or cron job.

Write a private status file containing:

```json
{
  "observed_at": "2030-01-02T03:04:00+00:00",
  "completed": "Fixture prepared.",
  "current": "Worker is verifying the candidate.",
  "next": "Collect the independent result.",
  "blocker": "None confirmed."
}
```

Only include facts safe to post. Status older than ten minutes is labeled stale.
Missing or malformed status produces an honest unavailable report, not a success
claim. The script does not summarize raw stdout or expose it in the worklog.

From an authorized working directory, run:

```sh
uv run --no-project --managed-python --python '>=3.11' python -I \
  /path/to/claudex-lean/scripts/report.py \
  --issue ISSUE_UUID --parent COMMENT_UUID --status /private/status.json \
  --records /private/run-records --last-visible-at LAST_VISIBLE_ISO_TIME \
  --max-seconds 3600 -- APPROVED_BACKEND_COMMAND
```

The records directory must be private (mode `0700`). Comment bodies are temporary
UTF-8 files in the working directory, passed with `--content-file` and removed after
the call. The run records contain a process ID, private command output, one delivery
journal and the terminal result. Do not commit or publish these runtime files.
A nonblocking local lock prevents two supervisors from owning the same records.

A send counts only after a returned comment ID is checked. A lost response remains
pending and is reconciled by its marker and reply parent before retrying. If the
lookup fails, the loop does not blindly resend. This reduces duplicates but is not
a transactional exactly-once delivery guarantee. On terminal command completion,
an unresolved delivery returns exit 3 and remains in the journal. Recover it with
`--issue ISSUE_UUID --parent COMMENT_UUID --records /private/run-records --reconcile-only`.
That mode reconciles and, only after a successful absent lookup, retries the pending
worklog without starting a command. A normal launch refuses pending delivery rather
than duplicating product work. API outages and latency can delay delivery beyond its
due time. Final-result delivery is separate.

The script owns only the process group it starts. It checks the Multica daemon PID
and group before launching any command and refreshes that check before termination.
If initial admission fails, nothing starts. If the refresh fails, cleanup uses the
verified launch-time identity and exclusively owned new process group, records a
warning, and still collects its child. It attempts graceful termination, then kills
remaining members of that group. It cannot identify detached sessions created by a future
backend. That backend must supply verified ownership and cleanup for them before use.
No global process-name kill or unrelated-session cleanup is appropriate.

## Validation

Run the repository checks described in `AGENTS.md`. Focused reporting tests use:

```sh
uv run --no-project --managed-python --python '>=3.11' python -m unittest discover \
  -s test -p test_claudex_lean.py -v
```

The tests cover a controlled clock, failed and ambiguous delivery, recovery,
short command outcomes, timeout/cancellation, and exclusive ownership. Simulated
transport does not prove live Multica delivery. Policy evaluations do not prove
worker capability. A production backend still needs independent-worker, real failure
case, lifecycle and long-running reporting integration checks.

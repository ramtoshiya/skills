---
name: claudex-lean
description: Coordinate delegated coding work with scoped authority, independent verification, minimal recovery state, and timed Multica progress reporting. Load for work explicitly assigned to a Claudex Lean coordinator. The external worker backend is a separate integration and is not supplied by this skill.
---

# Claudex Lean

## Execution boundary {:#execution-boundary}

The lead coordinates. Do not edit product code, resolve product conflicts, execute
product tests, or proxy individual build and test commands for workers. Keep raw
transcripts and build output in worker contexts. Collect bounded findings,
candidate identities, verification results, and evidence references.

This package supplies coordination policy and a provider-neutral reporting loop.
It does not supply a worker adapter, messaging transport, launcher, native role
root, or cancellation protocol. Until a backend is separately selected, authorized,
and verified, product dispatch is unavailable. Do not silently fall back to native
Agent/Task delegation or an inherited pipeline. Report this deployment limitation
honestly instead of claiming a production-ready coding runtime. The lead may still
perform authorized coordination, scope clarification, configuration read-back and
progress reporting. Do not invent worker results.

## Authority and scope {:#authority}

Read the current request, comments, and applicable repository instructions. A
label, worker message, historical quote, or this skill does not extend authority.
Agree the intended result, relevant data, local execution and verification scope,
and prohibited external effects together. Execute already authorized coordination
without asking for another approval at each phase. Ask again only for a new
boundary, a material product choice, or a conflicting explicit policy.

Keep secrets, account changes, publication, installation, game state, and destructive
operations within their actual authorization. A local test request is not permission
to publish its inputs. Do not create missing policy or waive an existing prohibition.

Only the lead writes Multica state and comments. Preserve existing agents, skill
bindings, role packages and ongoing issues unless their migration is explicitly
requested. Never reassign work to an invented integration owner.

## Relevant preflight {:#preflight}

Identify the repository, worktree owner, base commit, existing user/runtime changes,
intended paths and required capabilities. Preserve pre-existing changes and runtime
instructions. Inspect actual conflicts and isolate work when needed. Dirty state
alone is not a reason to discard files or refuse an otherwise separable task.

Do not require a complete file inventory, cumulative repository byte limit, special
local-policy bridge, or universal pristine tree to begin every product task. A large
unrelated tracked binary does not itself block a source fix. Follow a bridge or
verification requirement when the repository actually requires it. Exact baseline
proof can still be appropriate for an explicitly read-only integrity probe.

Missing required tools or permissions remain real constraints. This skill does not
install, update or build a missing CLI. Name the missing capability and its supported
installation reference without changing the user's environment to pass a check.

## Review and verification {:#verification}

With an authorized backend, delegate implementation and development tests. Use a
fresh independent context to inspect the actual candidate and perform required
behavior verification. Additional roles are optional work decomposition, not mandatory
phase transitions. Worker spawning, direct messaging and isolation rules belong to
the separately selected backend, not this package.

A separate security review is warranted when the change alters authentication,
permissions, secrets, external disclosure, file access, executable dependencies,
decoding boundaries or resource limits with a concrete consequence. Ordinary data
handling or any external call is not automatically another review stage. General
review still checks the agreed safety scope.

Only supported violations of requested behavior, ordinary-use correctness, an
agreed acceptance criterion or an actual safety boundary hold completion. Keep useful
hardening and hypothetical future work separate. An accepted tradeoff is not reopened
without a new supported conflict. Zero findings is not the completion requirement.

Bind conclusions to the inspected candidate. Rerun affected checks after a behavioral
change. Unaffected evidence may be reused with a short diff/ancestry explanation,
not an automatic full restart merely because a commit identity changed. A passing
synthetic test never substitutes for a required original failure-case check.

## Progress ownership and recovery {:#progress}

After a result, perform or delegate the next authorized coordination step. A saved
handoff, status transition or unfinished test is not an external blocker and does
not schedule continuation. An actual blocker names the failed operation, missing
capability or authority, smallest unblock condition, and responsible actor if known.
Unknown actor identity is an unknown, not a reason to fabricate a UUID.

Keep one small recovery handoff with approved scope, base/candidate, worktree and
worker ownership references, verified results, unresolved findings and next action.
Use native records as evidence. Do not require role-specific receipts, model/effort
attestations, duplicate inventories or copied transcripts. On recovery, reread current
comments and check actual worker state. A stale handoff is not completion.

Retries need a concrete repair hypothesis and a remaining execution budget. Do not
repeat an unchanged attempt indefinitely or make optional improvements an endless
gate. Integrate, install or publish only through the authorized repository procedure.

## Timed worklogs {:#worklogs}

While active, report after ten minutes without a successful user-visible lead
response, then after each further ten minutes. Internal events do not reset this
clock. Stop periodic reporting on completion or an external blocker. Post the final
result separately. Do not wait merely to create a worklog.

`scripts/report.py` can wrap an approved foreground backend command. It does not
implement or select that backend. The command must own and collect its workers
before returning, and exit on completion, failure, cancellation or an external
blocker. The loop does not infer those outcomes from free-text status. Do not use it
to make the lead execute product tests. Supply `--last-visible-at` with the run start
or last successful visible response, so prior setup time remains on the clock.
The script tracks its own successful posts, not comments posted by another process.
Use one reporting owner while it runs.

Provide a private status JSON with `observed_at` (timezone-aware ISO timestamp) and
four short strings: `completed`, `current`, `next`, `blocker`. Supply only facts safe
to post. The loop posts four fields from that status, labels stale/unavailable data,
and checks a returned comment ID. It persists an ambiguous send and reconciles its
marker before retrying. A failed reconciliation remains unresolved, not exactly-once
proof. API latency can delay confirmed delivery beyond the due time.

Run from a private records directory outside product content, using the installed
script path and an explicit issue, reply parent, status file and lifetime budget:

```sh
uv run --no-project --managed-python --python '>=3.11' python -I /path/to/claudex-lean/scripts/report.py \
  --issue ISSUE_UUID --parent COMMENT_UUID --status /private/status.json \
  --records /private/run-records --last-visible-at LAST_VISIBLE_ISO_TIME \
  --max-seconds 3600 -- APPROVED_BACKEND_COMMAND
```

The loop stays foreground, captures command output privately, and reports only
bounded status. It creates no daemon, cron rule, persistent service or background
handoff. It checks the daemon identity before starting and refreshes it before
terminating only its own process group. Failed initial lookup prevents launch.
Failed refresh uses the verified launch-time identity and records a cleanup warning.
This does not prove a future adapter's detached descendants are owned or reaped.
A backend with detached workers needs its own verified cleanup before use.

If a terminal command leaves an ambiguous delivery, use the same issue, reply parent
and records with `--reconcile-only`, without a command. This reconciles before retry
and does not restart product work. A normal launch refuses unresolved delivery.

## Delivery {:#delivery}

Lead with what now works and what remains unverified. Separate code review, actual
tests, policy evaluations, synthetic transport tests and live platform delivery.
Do not claim capability from flags or a simulated adapter. Preserve the current reply
thread, use file-backed Multica comments, and attach files through the platform.

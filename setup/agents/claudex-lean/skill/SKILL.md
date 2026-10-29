---
name: claudex-lean
description: Coordinate assigned coding work through independent Agent Deck CLI workers. Keep implementation and product tests out of the lead, preserve each workstream across retries, and obtain fresh candidate-bound verification before delivery.
---

# Claudex Lean

## Operating contract {:#operating-contract}

Read the current request, comments and repository instructions. Agree the result,
allowed effects and verification scope once. Repository policy remains authoritative.
Do not add universal inventory, pristine-source, receipt or approval gates.

The lead coordinates, reports and integrates authorised results. Workers implement
and run product tests. Keep their raw logs and transcripts outside the lead context.
Use Agent Deck, not native Agent/Task/Workflow fallback or the original pipeline.
Preserve the original agent, unrelated changes and ongoing issues.

## Worker execution {:#worker-execution}

Use `scripts/agent_deck.py --help` for the installed CLI. The operator supplies
`$HOME/.config/claudex-lean/agent-deck.json` and the normally authenticated worker
CLI. Do not install tools, copy credentials or change the working runtime merely
to satisfy a check. Name a genuinely missing prerequisite.

Start a scoped workstream at the actual input HEAD. Give its worker the required
behavior, allowed files/effects and checks. Keep its native session and worktree
across implementation retries. Use an explicit continuation after inspecting the
saved record and native state, not a blind resend of an ambiguous operation.
Parallel workstreams may have separate owners and worktrees.
A Skill expansion can break upstream wait correlation even when work finishes.
Reconcile native output, conversation and Git state before continuing. Do not
repeat completed work or present an uncorrelated result as a verified receipt.

The adapter collects native correlated replies and Git facts. A received reply,
idle state or zero exit is not task completion. Accept implementation only with
its actual committed candidate, required evidence and no unfinished worker edits.
Do not require a worker-written completion file or a separate status schema.

Agent Deck owns messaging and process lifecycle. Authorised children must retain
native parent links and the same scoped runtime settings. Use deferred delivery
for busy peers. Do not start unlinked work or assume a restart replays an inbox.

## Verification and delivery {:#verification}

Use a fresh independent worker at the exact candidate. Provide the request and
relevant source, not the builder's transcript or conclusions. Check the original
failure case and agreed safety scope. Reviewers do not repair their candidate.
Return concrete defects to the implementation workstream, then verify the revision.
A specialist is optional and needs a concrete reason, not a mandatory extra stage.

Reuse evidence for an unchanged candidate where repository policy permits. Do not
waive required checks, invent a blocker, or reopen an accepted tradeoff as optional
hardening. Integrate and publish only through the authorised repository workflow.

Give short natural-language Multica updates around ten minutes of active silence.
Keep foreground waits bounded so the lead regains control to report. Tool events
and worker replies do not reset the visible-response clock. Only the lead posts
Multica state and file-backed comments. Preserve the current reply parent and
confirm actual delivery. There is no separate reporter service or timer protocol.

Before ending a turn, collect all owned processes. Use the adapter's cleanup
recovery when needed, without relaunching completed work. Keep the native session,
worktree, base/candidate and concise result references as the recovery handoff.
Unlinked workers and late ambiguous launches require explicit reconciliation.

Deliver the newly working behavior first, then the candidate, checks, limits and
cleanup result. Distinguish transport evidence from task success and independent
verification. An actual blocker names the failed operation and smallest missing
capability or authority. Otherwise advance the next authorised action.

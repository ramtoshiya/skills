# Retries and step-ups {:#retries}

Read this when a worker stopped, failed, or seems to have outgrown its row. The rows are in
[Choose the row](../SKILL.md).

A worker that stopped or failed reruns on the same row by default. Read its thread first, with
`bb thread log <id>` for a BB worker, not only the reply it returned. Fix what stopped it, or say in
the new brief how to get past it. A worker stopped by a usage limit moves to another provider
instead, as [Route and quota](../SKILL.md#worker-route) describes.

Step up one row only when the worker's own work shows that the task outgrew its row: it produced a
design that misses the requirement, or its checks kept failing while it kept changing the code. Say
which one you saw. A worker that stopped before either happened has shown nothing about its row,
whatever its reason. `sonnet` `high` moves to `opus` `high`.
If `opus` `high` outgrows its row, split the work or change the approach. A step-up never goes to
`fable`. Only urgency does.

A Terra worker that outgrew its row reruns on the same provider on `sol` `high`, so the step-up
stays on the Codex quota.

After two materially identical failures without progress, change the approach or name the missing
capability.

## Seats outside the Claude family {:#cross-family}

When the calling workflow needs a seat outside the Claude family, such as a cross-model judge,
start it with the thread tool on the provider of the `codex` side. Give it the family the table's
GPT column names for its row, or `sol` at the row's effort for an
`opus` row. Without a thread tool, or while `quota-pace.py` reports the `codex` side limited, the
seat cannot run, so follow the calling workflow's fallback.

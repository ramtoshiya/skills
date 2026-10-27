# Impeccable storage contract {:#impeccable-storage-contract}

This POC targets an already-installed Impeccable CLI with native surface-brief schema 1. The local compatibility check uses CLI 4.7.0, whose shipped engine pin is 0.1.16. Passing those checks does not certify every release or storage format.

## Ownership {:#ownership}

| Artifact | Interview behavior |
| --- | --- |
| Resolved PRODUCT.md | Read product context. Propose approved durable additions separately. No POC automatic writes. |
| Resolved DESIGN.md | Read incumbent visual constraints. Propose a direction conflict if necessary. Never edit it here. |
| Resolved surface brief | Read all existing content. Save only the marked interview block, preserving the rest. |
| .impeccable/design.json | Optional read for visual context. No writes or regeneration. |
| .impeccable/config*.json | Do not change settings, hook consent, build path, or ignores. |
| .impeccable/build/** | Do not close phases, replace state, or manufacture a seed reference. |
| .impeccable/critique/** | Relevant findings may inform questions. Do not alter scores or close a backlog. |

Use Impeccable's resolved context paths rather than assuming root files exist. Read installed init/new-work/document guidance only where it affects compatibility. An interview record is not a substitute for PRODUCT.md or a completed Direction contract.

## Native helper contract {:#native-helper}

The official surface helper determines file naming, target normalization, and metadata:

```text
impeccable surface-brief path <target>
impeccable surface-brief read <target>
impeccable surface-brief write <primary-target> <body-file> [related-target ...]
```

`write` replaces the body and regenerates native metadata. It is not a section-merge API. Do not guess the slug, pass only the new paragraph, or omit existing related targets.

The bridge first reads through the official resolver and then verifies canonical storage. It accepts native schema 1 metadata with version, slug, primary_target, and related_targets. Unknown metadata or noncanonical serialization causes refusal rather than silent normalization. A related-target alias is resolved back to the existing primary target. Legacy paths, URL targets, and custom schemas are outside the POC writer's supported contract.

## Managed region {:#managed-region}

The bridge owns exactly this region:

```markdown
<!-- impeccable-interview:start -->
## Interview brief {:#interview-brief}

Task, situation, scope, evidence, hypotheses, recovery, acceptance,
readiness, and unresolved decisions for this surface.
<!-- impeccable-interview:end -->
```

Draft input contains only the content, without the markers or managed heading. Other headings and text remain outside the region. An unmarked existing Interview brief requires explicit manual adoption, not duplicate insertion. Malformed markers, duplicates, or a marked region overlapping a Direction contract are refused.

Do not put the native Direction contract inside this region. Preserve its exact text, including seed reference, FORM, and FINISH. If the task changes its meaning, record the pending conflict and resolve that decision before claiming implementation readiness. Do not create a dummy Direction contract for a new interview brief.

## Prepare a reviewed plan {:#prepare-plan}

Use an external scratch directory for the draft and plan. The native executable and project root must already be known and trusted. This example uses the host's uv runner, but the helper needs only Python 3.11+ standard library and can run with an approved installed Python interpreter.

```sh
uv run --no-project python -I "$SKILL_DIR/scripts/brief_bridge.py" prepare \
  --project "$PROJECT" --engine "$ENGINE" --target "$TARGET" \
  --draft "$DRAFT" --out "$PLAN"
```

`prepare` reads current storage, writes a new plan outside the project, and prints a unified diff. It does not change project files. Existing plan files are not overwritten. Pass `--context-file <resolved-path>` for each inherited or additional document whose changes should invalidate the plan. Root PRODUCT.md and DESIGN.md are tracked by default, including their absence.

Show the diff and preserve the user's scope of authorization. For example, approval to update one surface does not approve a product-wide policy or a visual-system change. A prepared plan contains local context paths and interview text, so do not publish it as an external report.

## Apply and resume {:#apply-plan}

After authorization for the reviewed change:

```sh
uv run --no-project python -I "$SKILL_DIR/scripts/brief_bridge.py" apply \
  --plan "$PLAN" --approved
```

The flag is a caller attestation, not proof that a human approved. The helper checks the CLI version, context fingerprints, surface identity, baseline hash, and proposed content digest. It uses the official writer, preserves related targets, and verifies both bytes and CLI readback. Reapplying an unchanged successful plan is a no-op.

A stale plan requires a fresh read and diff. Do not force the write. A post-write verification failure means the result needs inspection, not that nothing changed. Do not blindly restore a previous version, since another writer may have intervened.

The check and native write are not a cross-process transaction. Avoid concurrent writers. The POC catches changes present before its final inspection, but does not guarantee against a writer racing the CLI call or a process crash. It also does not authenticate plan files or user consent. Treat the plan and executable as trusted local workflow inputs, not a security sandbox.

For a later interview session, reload context and use the same concrete target. The native resolver loads the saved body as text. It does not assign special built-in validation semantics to this custom section. A later standard Impeccable command can still replace it, so verify preservation at that handoff rather than promising permanent enforcement.

## Refusal and fallback {:#refusal}

Missing tools, unsupported formats, stale content, or permission denial do not authorize installation, schema repair, or another route around a guard. Return a conversation-only brief or proposed change and state that it was not saved. Keep incomplete decisions and missing evidence visible.

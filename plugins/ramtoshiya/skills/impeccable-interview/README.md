# Impeccable interview

An interview skill for projects already using Impeccable. It reads product,
design, and per-surface context, clarifies the user task, and saves approved
interview context through Impeccable's native surface helper. No other
interview skill or wiki is required.

## Use

Install the `ramtoshiya` plugin as described in [Agent plugins](../../../../docs/agent-pack.md).
Install [Impeccable](https://impeccable.style/) separately. The bridge needs an
existing native CLI supporting surface-brief v1 and Python 3.11+ standard
library. It never installs an engine.

In Claude Code:

```text
/ramtoshiya:impeccable-interview route:/imports Help clarify recovery after invalid CSV rows.
```

```text
/ramtoshiya:impeccable-interview src/pages/import-errors.tsx Resume the saved brief and show the proposed update before saving.
```

Other hosts discover the same skill through their plugin skill registry. A
concrete target selects the surface. The skill stops after the brief and
storage handoff, without invoking UI implementation or another workflow.

## Write scope

The bridge creates or replaces one marked interview block in a surface brief.
It preserves native primary/related target metadata, the Direction contract,
and other content. Preparation produces an external plan and diff before an
authorized save. Stale context, unsupported storage, unsafe paths, and malformed
blocks cause refusal.

PRODUCT.md changes remain proposals. DESIGN.md, design.json, settings, build
state, and critique records are not written. The writer supports normalized
project-relative source targets and `route:/...`, not URLs, custom frontmatter,
or legacy-path migration.

Use it without concurrent writers. The checks and native write are not a
cross-process transaction. A plan and its `--approved` flag are trusted local
workflow inputs, not authenticated proof of human consent. Later Impeccable
operations may replace the custom section.

## Files

- [SKILL.md](SKILL.md): discovery and handoff flow.
- [Evidence and questioning](references/evidence-and-questioning.md): user-evidence distinctions.
- [Storage contract](references/impeccable-storage-contract.md): ownership, saving, and recovery.
- [Bridge](scripts/brief_bridge.py): preparation and native-helper write guard.
- [Integration tests](tests/test_brief_bridge.py): subprocess checks against a real installed CLI.
- [Behavior scenarios](evals/evals.json): saved-brief and missing-dependency scenarios with fixtures.

## Validate

From the repository root, set `ENGINE` to an existing trusted native executable,
not an installer or downloading wrapper:

```sh
IMPECCABLE_TEST_ENGINE="$ENGINE" uv run --offline --no-project --managed-python \
  --python '>=3.11' --no-config --exclude-newer '3 days' python -I \
  plugins/ramtoshiya/skills/impeccable-interview/tests/test_brief_bridge.py
```

The suite runs explicitly, outside `npm test`, because it needs an installed
Impeccable engine. It tests preview without writes, save/read/context reload,
managed-block replacement, aliases, idempotency, stale data refusal, malformed
metadata and markers, Direction contract protection, symlink escape, apply
authorization, and missing-engine handling. Protected files are compared
byte-for-byte.

The behavior scenarios are optional fresh-agent checks. Compare disk changes
as well as response claims. They do not establish automatic triggering,
interview quality, or representative-user outcomes.

Tested with Impeccable CLI 4.7.0 (shipped engine pin 0.1.16).

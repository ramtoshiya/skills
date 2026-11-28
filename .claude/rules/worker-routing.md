---
paths:
  - "plugins/ramtoshiya/skills/worker-routing/**"
  - "dev/tests/plugins/test_quota_pace.py"
---

# Worker routing

- A quota projection only picks the side a worker starts on. Only an actual usage-limit error or a `null` route stops work, and agents mention quota to the owner only in those cases. `quota-pace.py` keeps forecast figures out of its default output for this reason. ([Quota projections never make agents stop or hold work](../../docs/decisions/2026-11-29-quota-projections-never-stop-work.md))

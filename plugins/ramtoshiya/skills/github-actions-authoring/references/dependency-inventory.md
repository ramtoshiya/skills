# Inventory dependencies


Enumerate every remote `uses:` dependency before editing, including unchanged
steps in affected files, planned additions, job-level reusable workflows, and
remote dependencies nested in composite actions or reusable workflows you inspect.
Record each source repository, subpath, existing ref, and caller location. Inspect
local `./` actions and local reusable workflows for further remote dependencies.
Use a YAML-aware read or manual inspection, not a grep that misses aliases or
multiline values. Deduplicate lookups by source repository without losing callers.

Distinguish these sources:

- `owner/repo[/subpath]@ref` and `owner/repo/.github/workflows/file.yml@ref` need
  official release evidence and a commit pin from that original repository.
- Local `./` paths have no independent release tag. Review the local code and
  inventory its remote dependencies.
- `docker://` images need verified publisher provenance, stable release age, and
  an immutable image digest. A GitHub commit SHA is not an image digest. If the
  publisher's official release evidence cannot establish these facts, stop.

Do not edit a third-party repository to fix its nested pins. Report an unsafe
transitive dependency and stop if no compatible safe upstream release exists.


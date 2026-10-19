---
name: reorganize-commits
description: Reorganize the current branch's commits into meaningful chunks for reviewers and later maintainers.
disable-model-invocation: true
---

Reorganize the commits on the current branch to help the reviewer and future workers.

- A commit does not need to pass tests on its own. A meaningful chunk matters more.
- The result does not need to match the original tree byte for byte. Drop, move, edit, or stash content
  when that makes sense.

Report the original tip commit so the rewrite can be undone.

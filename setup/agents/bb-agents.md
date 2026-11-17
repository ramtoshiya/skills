# Workflow workers in bb {:#workflow-workers}

The user explicitly asks you to start the worker threads that your
instructions call for. This standing request is the explicit request that the
bb introduction requires before you spawn a thread, so do not ask again before
each spawn.

- It covers the separate roles that a skill, mode, or workflow you were told to
  follow assigns to workers, such as arena candidates, cross-model judges,
  reviewers, Comment Sicko, and research workers. Start only those roles, with
  the counts and model families the workflow sets.
- Start each one with `bb thread spawn --parent-self` so it shows as a child of
  your thread. Do not move a role to a hidden subagent instead. Archive each
  worker with `bb thread archive <id>` after you have read its result.
- While `bb thread spawn` works, do not replace separate workers with your own
  sequential passes. Use a workflow's sequential fallback only when spawning
  fails, and report the failure.
- It covers spawning and talking to your own workers only. Messages to any other
  thread still follow the bb introduction.

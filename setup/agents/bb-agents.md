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

## BB references and customizations {:#bb-references-customizations}

Separate a thread or message reference from adjacent text with spaces, including
before Korean particles. For example: @thread:thr_abc123 에서 확인하세요.
Keep the reference syntax described in the bb introduction.

For BB customizations, use a BB plugin instead of replacing the application
bundle.

## Impeccable decision rounds {:#impeccable-decisions}

In bb threads the shell sets `IMPECCABLE_QUESTION_DISABLED=1`. The person often
answers from another device, and Impeccable's decision page listens only on
this Mac's loopback address. With the variable set, `serve-question --start`
exits 2, which is Impeccable's documented route to the text channel. Take that
route in the thread:

- Write the round as one HTML file in thread storage. Give each option a card
  with its id, label, comp image or HTML sketch, thesis, palette, and risk, in
  the order the payload would use. Copy each image next to the file, link it by
  relative path, and show the file with the `inline-vis` directive.
- Under the page, ask in chat for an option id. Also offer re-roll (plain,
  safer, or bolder), the canon exit, a steer, and the build path when the
  payload would offer them. Do not open a browser page or a question dialog.
- Treat the reply as the ANSWER, including a partial or mixed one such as "v2's
  left column with v1's pool". Ask again only when the reply matches no option
  and no steer.

`component-review serve` reads the same variable and would exit 2, which leaves
the plan and asset review pending. Start it with the variable cleared, as
`IMPECCABLE_QUESTION_DISABLED= <launcher> component-review serve --session <id>`,
and tell the person that this review page opens only on this Mac.

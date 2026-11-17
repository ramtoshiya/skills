---
name: held-drafts
description: Create a bb thread whose first message waits for a person to send it, with `bb draft create`. Use when work must be approved before an agent starts it, or when asked to hand work off as a draft.
---

# Held drafts {:#held-drafts}

`bb draft create` creates a thread whose first message waits in its Queue.
The person approves by pressing **Send now** and rejects by deleting the
thread. Until then nothing runs and no worktree exists.

```sh
bb draft create --json --title "<short title>" \
  --new-environment worktree --provider <provider-id> --model <model-id> \
  --prompt "$(cat <<'EOF'
<the complete brief>
EOF
)"
```

- `--prompt` is the entire first message. The receiving agent sees nothing
  else, so write a self-contained brief.
- `--project` defaults to the calling thread's project. Pass it when the work
  belongs to another project (`bb project list`).
- `--new-environment worktree` gives the work its own checkout when it is sent.
  Omit it to use the project's default environment.
- `--json` prints `{"threadId": "...", "held": true|false}`. `held` is false
  when the plugin's `mode` setting is `direct`, and then the message was sent
  immediately.
- Report the thread to the person as `@thread:<threadId>` and say that sending
  it is the approval.

Do not send the draft yourself with `bb thread queue send`. Approval belongs
to the person. Do not change the plugin's `mode` setting unless the person
asks.

# Paseo Desktop on macOS {:#paseo}

When `PASEO_AGENT_ID` is set and `BB_THREAD_ID` is unset, use the bundled helper. It requires an
installed macOS Paseo Desktop bundle and a provider that advertises `/compact`. Set
`PASEO_DESKTOP_APP` if the bundle is not at `/Applications/Paseo.app`. It uses the installed
bundle's SDK and runtime without installing dependencies. Standalone and remote daemons are
not supported by this helper.

This is an exclusive-session proof of concept. Do not use it while another controller or worker
can send prompts to this agent. Paseo has no atomic send-only-if-idle operation, so an incoming
prompt between the idle check and a send could be interrupted. Do not send more work until the
helper finishes. Other agents can continue their own work.

Launch this command with the shell tool's background execution option and completion
notifications, using this skill's actual directory for `<skill-directory>` and the absolute
handoff note path. If the shell tool cannot notify you when background work fails, use the
automatic-compaction fallback instead:

```sh
sh "<skill-directory>/scripts/paseo-compact.sh" "<handoff-note>"
```

The helper waits up to five minutes for your current turn to finish. End the turn immediately
after launch with one line saying compaction is scheduled and work will resume. Do not wait for
the helper in the foreground, because it is waiting for you to stop. If the next step needs the
user's answer, add `--no-resume` and end with the question instead.

The helper sends `/compact` as a native provider command, waits for a new completed compaction
event, then sends the resume instruction. Ordinary agent-originated `paseo send` and
`send_agent_prompt` wrap the text as an agent message, so they do not execute `/compact`.
A delivery receipt or an assistant's summary is not proof of compaction. Helper failure keeps
the note and does not send a resume instruction. Read the error before retrying.

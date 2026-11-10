---
name: codex-session-reader
description: Locate and read Codex CLI session transcripts directly from disk instead of assuming there's no way to access them. Use this whenever the user references a Codex session, a Codex run, a Codex conversation, or a session ID that looks like a UUID, and asks to read, check, verify, summarize, search, or recall something from it, even if no dedicated "read codex session" tool is available. Codex transcripts are plain JSONL files on the same filesystem under ~/.codex/sessions/ (not an unreachable resource), so don't report a missing dedicated tool as a missing capability.
---

# Reading Codex session transcripts

A Codex CLI session transcript is a plain file on disk, readable the same way you'd read
any other log file — with `find`, `jq`, and `rg`. There is no dedicated tool for this and
none is needed. If a question about a Codex session comes up, treat it as a file-lookup
task, not a missing-capability question.

## Where sessions live

```
~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-<ISO8601-timestamp>-<session-id>.jsonl
```

Sessions are filed under the date the rollout started, so a bare session ID doesn't tell
you which date folder to look in. Search by suffix instead of guessing the path:

```sh
find ~/.codex/sessions -name "*<session-id-or-fragment>*.jsonl"
```

If more than one file matches (a short fragment, or a vague reference like "yesterday's
codex session"), list the candidates with their embedded timestamps and disambiguate
before reading further, or ask the user which one they mean.

There's no Codex CLI subcommand for reading a transcript non-interactively — `codex
resume` is an interactive picker, not something you can pipe a session ID into. Direct
file access is the reliable path, not a fallback.

## File format

Confirmed against Codex CLI 0.162.1 on 2026-10-15. If a transcript's
`session_meta.payload.cli_version` is newer and a recipe returns nothing, inspect the
line types (`jq -r '.type + " " + (.payload.type? // "")' "$FILE" | sort | uniq -c`)
before concluding the session is empty.

JSONL — one JSON object per line. Transcripts commonly run to thousands of lines, and
the first line alone can be huge (it embeds the full system prompt), so don't `cat` or
blindly `Read` the whole file. Filter with `jq`/`rg` first, then read only the slice you
need.

Each line has a top-level `type`:

- `session_meta` (always line 1) — session id, cwd, model_provider, cli_version, git
  branch/commit. Read this first for orientation.
- `event_msg` — curated, human-readable events. The useful `payload.type` values:
  - `item_completed` — one finished item; `payload.item.type` is `UserMessage`,
    `AgentMessage`, `CommandExecution`, or `Reasoning`. Message text is in
    `payload.item.content[].text`; a command execution carries `command`, `exit_code`,
    and `aggregated_output`.
  - `task_started` / `task_complete` — turn boundaries
  - `token_count` — usage stats per turn
- `response_item` — the raw model-facing conversation items (`message`, `reasoning`,
  `function_call` / `function_call_output`, `custom_tool_call` /
  `custom_tool_call_output`). Richer than `event_msg` but noisier, and `message` items
  include injected developer and context text — reach for this only when `event_msg`
  doesn't have what's needed, e.g. the exact arguments a tool call received.

Other top-level types such as `turn_context` also appear; ignore them.

## Recipes

Reconstruct the conversation in order:

```sh
jq -r 'select(.type=="event_msg" and .payload.type=="item_completed") | .payload.item
  | if .type=="UserMessage" then "USER: " + ([.content[]?.text // empty] | join(""))
    elif .type=="AgentMessage" then "AGENT: " + ([.content[]?.text // empty] | join(""))
    else empty end' "$FILE"
```

Get session metadata:

```sh
jq -c 'select(.type=="session_meta")' "$FILE" | head -1
```

Search for a keyword or topic across the transcript:

```sh
rg -n "keyword" "$FILE"
```

See what tool calls were run:

```sh
jq -r 'select(.type=="response_item") | .payload
  | if .type=="function_call" then "\(.name) \(.arguments)"
    elif .type=="custom_tool_call" then "\(.name) \(.input)"
    else empty end' "$FILE"
```

Shell commands with exit codes:

```sh
jq -r 'select(.payload.type=="item_completed" and .payload.item.type=="CommandExecution")
  | .payload.item | "[\(.exit_code)] \(.command)"' "$FILE"
```

## Answering "can you read/verify this session" questions

The task is almost always answerable in three steps: find the file, confirm it parses
(a `session_meta` line on top is a good sanity check), then pull out whatever specific
information was actually asked for. Don't stop at "I don't have a tool for this" — a
missing dedicated tool doesn't mean the file is unreachable.

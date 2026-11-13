# Hooks

The plugins add four hooks. One comes with `ramtoshiya` and runs in Claude
Code and Codex. Three come with `ramtoshiya-cc` and run only in Claude Code. The
`ramtoshiya` plugin also ships a Git hygiene check that is not registered, so
no agent runs it.

| Hook | Runs | Plugin |
| --- | --- | --- |
| Package and Python guard | Before each shell command | `ramtoshiya` |
| Commit attribution guard | Before each shell command | `ramtoshiya-cc` |
| Context budget | After each tool call, on each prompt, and after a compaction | `ramtoshiya-cc` |

Each hook is a Python script that uses only the standard library. Claude Code
and Codex run it through `hooks/hooks.json`. Every hook runs as:

```sh
uv run --offline --no-project --managed-python --python '>=3.11' --no-config --exclude-newer '3 days' python <hook>
```

None of the hooks is a sandbox. They read command text and never execute it, so
a dynamic script, an alias, or a deliberate workaround gets past them.

The commit attribution guard's size limits are soft. It reads message files up
to 1 GiB, and a message file above 1 MiB is still used. Each such case adds a
line with the limit name, the byte count, and the soft limit to
`$XDG_STATE_HOME/ramtoshiya/size-warnings.log`, or
`~/.local/state/ramtoshiya/size-warnings.log`. Claude Code does not keep hook
stderr, so the warnings go to this log. A message file above 1 GiB is logged and
not checked.

## Package and Python guard

`plugins/ramtoshiya/hooks/global-package-guard.py` checks shell commands for these
rules:

- No global package changes: `npm`/`pnpm` global installs, removals, and
  links, Yarn `global` changes, and `uv tool` installs, upgrades, and
  removals.
- One-shot package runs must pin an exact version: `npx tool@1.2.3`,
  `npm exec --package=tool@1.2.3 -- tool`, `pnpm dlx tool@1.2.3`,
  `yarn dlx tool@1.2.3`, and `uvx tool==1.2.3`. Every package named in the
  command must be pinned, including `--package`, `--from`, and uv's `--with`.
  Tags, ranges, missing versions, URLs, and local paths are rejected.
- Commands that resolve or install packages, including `uv run`, need a
  configured minimum release age of at least three days. Until a setting
  exists, the guard blocks them. [Agent plugins](agent-pack.md) lists the
  settings. The guard also rejects flags, environment variables, config
  values, and exemptions that would allow newer releases. It reads the npm, pnpm, and
  Yarn settings and the uv TOML files that apply to the command, and denies
  settings it cannot parse. A stronger flag does not excuse a weaker value in a
  config file. The package managers enforce the age themselves. The guard only
  checks that the setting is in place.
- Python itself runs normally. `pip`, `pip3`, `python -m pip`,
  `python -m ensurepip`, and `python setup.py install` or `develop` are
  blocked unless they use a virtual environment's executable by path, such as
  `.venv/bin/pip`, because they would install into a system or Homebrew
  Python. `uv pip` with `--break-system-packages` is blocked too. For
  packages, use `uv add`, `uv pip` inside a project, or
  `uv run --with package==1.2.3 python`.

After a `cd` to a variable path such as `cd "$DIR"`, the guard cannot find
project settings or resolve relative paths. Commands that need them, such as
`npm install` or `uv sync`, are denied until a `cd` to a literal absolute path
or the home directory. An absolute directory option such as
`uv --directory /path/to/project sync` also supplies the missing path.
Commands that use only user settings, such as `uvx tool==1.2.3`, and commands
such as `git status` still run.

The same shared guard checks common model commands:

- `hf download` and `huggingface-cli download` require `--revision` with a
  full 40-character commit hash. Branches, tags, short hashes, missing values,
  and conflicting mutable revision declarations are denied. This also applies
  to dataset and space downloads, which can carry model artifacts or code.
- `ollama pull`, `run`, and `create` are denied because these command forms do
  not establish reviewed, immutable artifact provenance. Even a cached `run`
  is denied because it can fetch a missing model.
- oMLX and vLLM `serve`, `mlx_lm.server`, `mlx_vlm.server`, `llama-server`,
  `llama-cli`, and MLX `generate`/`convert` commands require an explicit,
  existing local model path beginning with `/`, `./`, `../`, or `~/`.
  A Hub repository id is not a local path. Servers also require an explicit
  loopback `--host` (`127.0.0.1`, `::1`, or `localhost`).
- Recognized oMLX, vLLM, llama, and MLX commands reject `--trust-remote-code`
  and `--trust_remote_code`, including abbreviated spellings and explicit
  false values. Omit the flag. MLX adapter paths must also be local.
- llama commands reject Hub and URL source flags and the environment settings
  `LLAMA_ARG_HF_REPO`, `LLAMA_ARG_HF_REPO_V`, `LLAMA_ARG_HF_FILE`, and
  `LLAMA_ARG_MODEL_URL` even alongside a local model path. Download through
  the pinned acquisition step instead.

Subcommand help remains available. The guard also recognizes these entry points
through `uv run` and Python `-m`, including attached module arguments. Existing
Python and package-age checks still apply.

A full revision identifies bytes, not a trustworthy publisher or safe behavior.
Before loading, review the publisher and revision, record the source repository,
revision, filenames, and SHA-256 hashes, and verify those hashes after download
and conversion. Prefer non-executable weight formats such as safetensors.
Review tokenizer, configuration, templates, and loader code too. A clean
benchmark does not rule out a trigger-based backdoor in weights.

Run inference in a separate, least-privilege process with only the required
inputs and model files mounted. Remove credentials and project secrets, deny
outbound network access after acquisition, and give the process no shell or
agent tool authority. Treat model output as untrusted data and validate it
before any downstream action. Loopback binding alone does not provide this
isolation. A pinned local model can still produce malicious or incorrect output.

These are command-text checks, not artifact attestation or OS isolation.
They do not fetch metadata, enforce a model release-age floor, hash large
artifacts, inspect model contents, verify local directory provenance, or apply
network/filesystem restrictions. Local files can change after review. Direct
SDK calls, inline scripts, HTTP clients, other loaders, custom wrappers, and
already-running inference services are outside model-rule coverage. Download
and review first, then use a local path with a separately isolated runtime.

`uv python install` is always allowed. The guard
splits command sequences, follows `sh -c` and similar wrappers, and skips
heredoc bodies. A denial reaches the agent as the hook's reason.

When the guard cannot run, Claude Code and Codex apply their own rules for a
failing hook process.

## Git hygiene check

`plugins/ramtoshiya/hooks/git-hygiene-guard.py` is not registered in
`plugins/ramtoshiya/hooks/hooks.json`, so Claude Code and Codex do not run it.
It is off to see whether agents leave uncommitted work behind without it. To
turn it on, add this entry under `"hooks"` in that file, then follow the update
steps in [Agent plugins](agent-pack.md). Codex asks you to trust the new `Stop`
hook in `/hooks`.

```json
"Stop": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "uv run --offline --no-project --managed-python --python '>=3.11' --no-config --exclude-newer '3 days' python \"${CLAUDE_PLUGIN_ROOT}/hooks/git-hygiene-guard.py\"",
        "timeout": 10
      }
    ]
  }
]
```

The rest of this section describes the check when it is registered.

Multica tasks skip this check when `MULTICA_TASK_ID` is non-empty. Multica owns
its generated runtime files and task completion flow. Other hooks remain active,
and sessions outside Multica still run the Git hygiene check.

The script runs when the agent is about to stop. It runs `git status --porcelain` in the repository that contains the
session's working directory. If anything is uncommitted, it blocks the stop
once, lists up to 80 changed paths, and tells the agent to:

- commit completed work it owns,
- otherwise ignore, stash, keep as explicit work in progress, or remove its own
  changes,
- leave unrelated or pre-existing changes alone.

The second stop in the same prompt is allowed, so an instruction to leave work
uncommitted still wins.

Claude Code and Codex run it on the `Stop` event. It blocks with
`{"decision":"block","reason":...}` and treats `stop_hook_active` as the retry.
Any error allows the stop, for example no repository, a Git command that times
out, or hook input it cannot read.

Limits:

- The check keeps no state, so changes that existed before the session are
  listed too. The instructions tell the agent to leave them alone.
- Only the repository at the working directory is checked. Changes made in
  another repository, for example with `git -C`, are not.
- If another `Stop` hook blocks while the tree is clean, Claude Code and Codex
  mark the continuation with `stop_hook_active`, and changes made during it are
  not checked when it stops.

## Commit attribution guard

`plugins/ramtoshiya-cc/hooks/commit-trailer-guard.py` blocks Claude Code shell
commands that write commit, tag, or pull request text containing an AI
attribution line: a `Co-Authored-By` trailer that names Claude, Anthropic,
Codex, OpenAI, Copilot, or Cursor, a "Generated with Claude Code" footer, or a
`claude.ai/code/` session link. It checks `git commit`, `merge`, `tag`, `notes`,
[git-spice](https://abhinav.github.io/git-spice/) (`gs`), and
`gh pr`/`gh issue`, including heredocs and files passed with `-F`, `--file`, or
`--body-file`.

Claude Code adds these lines because it asks the model to. Setting `commit`
and `pr` to empty strings under `attribution` in `settings.json` turns that
request off, and the [machine setup](setup.md) does this. The hook catches the
lines when the model adds them anyway. On an internal error it allows the
command, so a bug in the hook cannot block every shell call.

## Context budget

`plugins/ramtoshiya-cc/hooks/context-budget.py` lets the agent compact at a
point it chooses instead of in the middle of a step. Hook input does not
include the context size, so after each tool call and each prompt the hook
reads the token usage of the last main-conversation reply from the transcript.
It compares that with the numeric `autoCompactWindow` setting, taken from the
project's `.claude/settings.local.json`, then `.claude/settings.json`, then the
user's `settings.json`. From 75% it adds a note to the agent's context that
asks it to compact at the next natural boundary with the `self-compact` skill.
The note names a handoff note path and, in T3 Code, the thread id from
`T3CODE_THREAD_ID`. The path is `handoff.md` in the session's scratchpad
directory when Claude Code provides one. Otherwise it is
`$XDG_STATE_HOME/ramtoshiya/handoff/<session id>.md`, or the same path under
`~/.local/state`. It repeats once at each
further five points, at 80%, 85%, and so on, and starts over after a
compaction. When Claude Code starts again after a compaction and the handoff
note exists, the hook tells the agent to read it.

The hook cannot start a compaction. In T3 Code the skill has the agent queue
`/compact` and a resume message to its own thread, and T3 Code runs them after
the turn ends. In a terminal session the agent can only keep the handoff note
current, and Claude Code still compacts on its own near the window.

Limits:

- The hook is silent when `autoCompactWindow` is missing or `auto`, and it
  does not see the `--autocompact` flag.
- The usage comes from the last reply, so it lags by one tool result. A large
  result can take the context past the window before the warning shows.
- Subagent tool calls do not trigger it, because a subagent cannot compact the
  main conversation.
- The last warned band per session is kept in
  `$XDG_STATE_HOME/ramtoshiya/context-budget.json`, or
  `~/.local/state/ramtoshiya/context-budget.json`, for the newest 100 sessions.
- On any error the hook adds nothing.

## Tests

`dev/tests/plugins/test_global_package_guard.py`, `dev/tests/plugins/test_git_hygiene_guard.py`,
`dev/tests/plugins/test_commit_trailer_guard.py`, and `dev/tests/plugins/test_context_budget.py`
cover the rules. Run them with `npm test`.

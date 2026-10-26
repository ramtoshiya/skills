# Hooks

The plugins add three hooks. Two come with `ramtoshiya` and run in Claude Code,
Codex, Pi, and Hermes. One comes with `ramtoshiya-cc` and runs only in Claude Code.

| Hook | Runs | Plugin |
| --- | --- | --- |
| Package and Python guard | Before each shell command | `ramtoshiya` |
| Git hygiene check | When the agent is about to stop | `ramtoshiya` |
| Commit attribution guard | Before each shell command | `ramtoshiya-cc` |

Each hook is a Python script that uses only the standard library. Claude Code
and Codex run it through `hooks/hooks.json`. Pi runs the `ramtoshiya` hooks through
the extension `hooks/pi.ts`. Hermes uses the native plugin adapter
`__init__.py`. Every hook runs as:

```sh
uv run --offline --no-project --managed-python --python '>=3.11' --no-config --exclude-newer '3 days' python <hook>
```

None of the hooks is a sandbox. They read command text and never execute it, so
a dynamic script, an alias, or a deliberate workaround gets past them.

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
- No bare `python`, `python3`, `python3.12`, `pip`, or `pip3`, including
  absolute paths to system or Homebrew Python and read-only calls such as
  `python -V`. Use `uv run python`, `uv pip`, or a virtual environment's
  interpreter by path, such as `.venv/bin/python`. An activated virtual
  environment does not make a bare `python` allowed.

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

When the guard cannot run, the outcome depends on the agent. Pi blocks the
command if uv fails, times out after five seconds, or returns output it cannot
read. Hermes does the same. Claude Code and Codex apply their own rules for a
failing hook process.

In Pi, the guard sees calls to the `bash` tool, including calls that other
extensions make through `ctx.executeTool()`. It does not see commands you type
with `!` or `!!`, processes that extensions start themselves, or shells hidden
inside other tools.

In Hermes, the package guard sees `terminal` tool calls. It checks an explicit
`workdir` when supplied, otherwise `TERMINAL_CWD` or the Hermes process's working
directory. It does not track persistent `cd` commands. The guards inspect the
local host filesystem, so use them with the local terminal backend. They do not
inspect remote or container package settings, interactive `process_manage`
input, or processes started directly by another plugin.

## Git hygiene check

`plugins/ramtoshiya/hooks/git-hygiene-guard.py` runs when the agent is about to
stop. It runs `git status --porcelain` in the repository that contains the
session's working directory. If anything is uncommitted, it blocks the stop
once, lists up to 80 changed paths, and tells the agent to:

- commit completed work it owns,
- otherwise ignore, stash, keep as explicit work in progress, or remove its own
  changes,
- leave unrelated or pre-existing changes alone.

The second stop in the same prompt is allowed, so an instruction to leave work
uncommitted still wins.

| Agent | Event | Retry signal |
| --- | --- | --- |
| Claude Code, Codex | `Stop`, answered with `{"decision":"block","reason":...}` | `stop_hook_active` |
| Pi | `agent_before_settle`, answered with a message and `continue: true` | One warning per run, reset on `agent_settled` |
| Hermes | `pre_verify`, answered with the shared `decision: block` result | `attempt > 0` allows the retry |

Pi skips runs that were aborted or failed. Every error allows the stop: no
repository, no uv, a timeout after ten seconds, or unreadable output.

Hermes fires `pre_verify` only after it records file edits and while its
`agent.max_verify_nudges` budget remains. A turn with no recorded edits does not
run the Git check, even if the repository was already dirty. The check uses
`TERMINAL_CWD` or the Hermes process's working directory, not the last terminal
`workdir` or `cd`. A previous verification continuation also allows the retry.

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

## Tests

`test/test_global_package_guard.py`, `test/test_git_hygiene_guard.py`, and
`test/test_commit_trailer_guard.py` cover the rules. `test/*.test.mjs` cover the
Pi extension, including its behavior when uv fails. The Hermes adapter has
protocol and failure tests in `test/test_hermes.py`. Plugin Doctor checks its
registration against an installed Hermes runtime. Run them all with
`npm test`.

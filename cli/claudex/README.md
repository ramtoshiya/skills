# claudex

Run Claude Code with GPT models through a running
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) server.
The command discovers models at startup and passes your arguments to `claude`.

## Install

Install [Node.js](https://nodejs.org/en/download) 22 or newer and
[Claude Code](https://code.claude.com/docs/en/setup), with `node` and `claude`
on `PATH`. Start CLIProxyAPI with a working GPT upstream, then run from this
repository:

```sh
sh cli/claudex/install.sh
```

The installer copies the command into `~/.local/share/claudex` and links it
at `~/.local/bin/claudex`. Add `~/.local/bin` to `PATH` if needed. Run the
installer again after updating the checkout. It installs no dependencies.

## Connection

Create `~/.config/claudex/config.json` with your proxy's client key:

```json
{
  "baseUrl": "http://127.0.0.1:8317",
  "apiKey": "$MY_LOCAL_PROXY_KEY"
}
```

Set `MY_LOCAL_PROXY_KEY` in the shell that launches `claudex`. `apiKey` also
accepts a literal key. Keep a file containing a literal key readable only by
you with `chmod 600`. Never put that file in this repository.

Without that file, `claudex` reads `~/.pi/agent/cliproxy-provider.json` if it
exists, so an existing Pi proxy connection can be reused. `CLAUDEX_CONFIG`
selects another configuration file. `CLIPROXY_BASE_URL` and
`CLIPROXY_API_KEY` override the file values. The URL defaults to
`http://127.0.0.1:8317` and can end in `/v1`. Remote proxies require HTTPS.
Catalog discovery times out after five seconds and refuses redirects.

The client key goes to Claude Code through its environment, without being
included in command arguments or written to a generated settings file.

## Use

```sh
claudex
claudex --fast
claudex --model gpt-6.1-sol
claudex -p 'Explain this project'
```

Put `--fast` first to request GPT priority processing for the session. The wrapper
sets `speed: "fast"` through `CLAUDE_CODE_EXTRA_BODY`, which CLIProxyAPI's Codex
translator maps to `service_tier: "priority"`. Other extra-body fields are
preserved. This does not lower reasoning effort or enable Claude Code's `/fast`
toggle. Your upstream must support priority processing, which can have different
billing or usage limits. Requesting it does not guarantee lower latency.
Without `--fast`, the wrapper leaves the service tier unchanged.

Only visible OpenAI models with IDs matching `gpt-<major>[.<minor>]` and an
optional `astra`, `sol`, `terra`, `luna`, `codex`, `mini`, or `nano` suffix
are considered. Selection prefers the highest major and minor version first,
then the first available tier in each row:

| Claude Code role | Preferred tiers |
| --- | --- |
| Fable | `astra` |
| Main and Opus | `astra`, `sol`, `codex`, no suffix, `terra` |
| Sonnet and subagents | `sol`, `terra`, `codex`, no suffix |
| Haiku | `luna`, `mini`, `nano` |

If a role has no matching tier, it uses the main model. If no main tier
matches, the main model is the first recognized model in the catalog.
Discovery still runs when you pass `--model`, which overrides the main model.
The Fable slot in `/model` shows the selected Astra model ID, even when a newer
Sol model is selected for main and Opus. If no Astra is available, it shows
the main model instead.
`--help`, `-h`, `--version`, and `-v` alone run Claude Code without discovery.

The wrapper enables auto-compact for `claudex` sessions without changing the
saved preference used by regular `claude` launches. At startup it fetches
`/v1/models?client_version=0.155.0` for the Codex catalog and uses the starting
model's advertised `max_context_window`, falling back to `context_window` when
the maximum is unavailable. `--model` and `--model=...` overrides, including the
role aliases in the table, select which model's limit to use. If the Codex
catalog has no usable entry, it uses `max_context_window`, `context_window`, or
`context_length` from the ordinary `/v1/models` response, in that order. If
neither catalog provides a positive integer limit, it prints a warning and uses
250,000 tokens.
The extra catalog request times out after five seconds and refuses redirects.

The context setting applies to the whole Claude Code session. Restart claudex
with `--model` to discover another model's limit after switching models.
Use base model IDs such as `gpt-6.1-sol`. Hermes's `-900k` suffix is a local alias
that claudex does not translate.

The wrapper also enables effort controls, limits concurrent tool use to three,
and disables tool search. Other Claude Code settings and hooks still apply.

Tested with Claude Code 2.1.308 for fast request capture and a live GPT-6.1 Sol
fast request, and 2.1.304 for live discovery and 872k-input requests to GPT-6
Astra, GPT-6.1 Sol, GPT-6 Sol, and GPT-6 Luna.

## Checks

From the repository root, run `node --test test/claudex.test.mjs` or `npm test`.
The command tests use a local HTTP server and a substitute `claude` executable.
They check role selection, argument forwarding, credential handling, failures,
and exit status without contacting an upstream provider.

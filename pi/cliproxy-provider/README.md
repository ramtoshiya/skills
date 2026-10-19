# CLIProxyAPI provider for Pi

A Pi extension that discovers the Claude and GPT models of a
[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) server and
registers them as the provider `cliproxy-native`. Each model family uses Pi's
built-in transport for its own wire protocol:

| Family | Model IDs | Pi transport | Proxy endpoint |
| --- | --- | --- | --- |
| Claude | `claude-*` | `anthropic-messages` | `/v1/messages` |
| GPT | `gpt-*`, except `gpt-image-*` and `gpt-oss-*` | `openai-responses` | `/v1/responses` |

```text
Pi (history, agent loop, tools)
  -> Anthropic Messages or OpenAI Responses over HTTP/SSE
  -> CLIProxyAPI (routing and upstream authentication)
  -> Anthropic or OpenAI
```

Other IDs the proxy lists, such as image models, `gpt-oss-*`, and `codex-*`,
are not registered.

The extension does not log in to providers, start or configure the proxy, or
rewrite prompts and tool definitions. CLIProxyAPI may change requests on its
own. Whether a provider allows its subscription to be used through a proxy is
up to that provider's terms, and a working request does not settle it.

## Requirements

- [Pi](https://pi.dev) 1.2.0 or a later version with the same extension API.
- A running CLIProxyAPI server, a client key for it, and a working
  `/v1/messages` endpoint.
- Node.js 22 or newer to run the tests.

## Install

Pi installs a Git package from the repository root, which is the `ramtoshiya`
plugin, so install this package from a clone:

```sh
git clone https://github.com/ramtoshiya/skills.git
pi install ./skills/pi/cliproxy-provider
```

Pi loads the package from that folder, so keep the clone. Run `/reload` or
restart Pi, then pick a model under `cliproxy-native` in `/model`. Installing
does not change your default model. Remove it with
`pi remove ./skills/pi/cliproxy-provider`.

To try it without installing, run Pi from `pi/cliproxy-provider` in the clone:

```sh
pi -ne --no-mcp -e ./index.ts --list-models cliproxy-native
pi -ne --no-mcp -e ./index.ts --model cliproxy-native/claude-sonnet-5-5
```

`-ne` turns off your other extensions but still loads the one given with `-e`.

## Connection settings

Create `~/.pi/agent/cliproxy-provider.json`:

```json
{
  "baseUrl": "http://127.0.0.1:8317",
  "apiKey": "$MY_LOCAL_PROXY_KEY"
}
```

`apiKey` is a client key for the proxy, not an Anthropic or OpenAI API key. It
can be a literal or a single `$VAR` or `${VAR}` reference to an environment
variable that is set where Pi starts. A literal key belongs in a file only you
can read (`chmod 600`). Shell commands that print a key are not supported.

The environment variables `CLIPROXY_BASE_URL` and `CLIPROXY_API_KEY` override
the file. Without `cliproxy-provider.json`, the extension reads
`providers.cliproxy.baseUrl` and `apiKey` from `~/.pi/agent/models.json`, if
you already defined the proxy there. It only reads that file and does not
import its static model list. `baseUrl` defaults to `http://127.0.0.1:8317`.

The settings are read when Pi loads the extension, so run `/reload` after a
change. With a custom Pi agent directory, these files are read from that
directory.

`baseUrl` can be the proxy's root URL or end in `/v1`. A remote proxy must use
HTTPS. Plain HTTP is accepted only for localhost. Catalog requests do not
follow redirects, so the key cannot be sent to another origin.

## Choose and order models

Add `include`, `exclude`, and `sort` to `~/.pi/agent/cliproxy-provider.json`:

```json
{
  "baseUrl": "http://127.0.0.1:8317",
  "apiKey": "$MY_LOCAL_PROXY_KEY",
  "include": ["claude>=5", "gpt>=6"],
  "exclude": ["claude=5"],
  "sort": "id-desc"
}
```

A model is shown when it matches any `include` entry and no `exclude` entry.
Without `include`, every discovered model is allowed. `include: []` shows none.

An entry is either a version constraint or a glob. A version constraint has
the form `<family><op><version>`, where the family is `claude` or `gpt`
and the operator is `>=`, `>`, `<=`, `<`, or `=`. The version is the
first run of numeric segments in the ID. A trailing 8-digit date is ignored:

| ID | Version |
| --- | --- |
| `claude-opus-5-5` | 5.5 |
| `claude-fable-5` | 5 |
| `claude-haiku-4-5-20251001` | 4.5 |
| `claude-3-7-sonnet-20250219` | 3.7 |
| `gpt-6.1-sol` | 6.1 |
| `gpt-6-sol` | 6 |

Missing segments count as zero, so `claude=5` matches `claude-opus-5` but not
`claude-opus-5-5`. For a range, combine an include and an exclude, for example
`include: ["gpt>=5.6"]` with `exclude: ["gpt>=6"]`. An ID without a version
never matches a constraint. A version number says nothing about release dates,
so `gpt>=6` does not mean "the latest release".

A glob matches the whole model ID, case-sensitively. `*` is the only wildcard,
as in `claude-opus-*` or `*-thinking`. Invalid entries, such as `gpt=>6` or an
unknown family, are rejected when the extension loads.

Models are registered in descending ID order, compared numerically, so `5-10`
comes before `5-5`. Set `sort` to `id-asc` for ascending order. Some Pi views
sort the list again. Filters apply in every view.

Run `/reload` after editing the file. Filters also apply to the cached catalog,
which keeps excluded models, so widening a filter needs no network request.
Models of a separately defined static `cliproxy` provider are not filtered.

## Thinking levels

When a model ID exactly matches an entry in Pi's saved Anthropic or OpenAI
catalog, the model gets that entry's thinking levels and a short list of its
compatibility flags. Levels such as `xhigh` and `max` are then available only
where the catalog lists them. For
GPT models only `supportsStrictMode` is copied. OpenAI tool search, grammar
tools, and explicit prompt-cache modes stay off because they are untested
through the proxy. A model that is not in a catalog can advertise its levels
through the proxy's `thinking.levels` field.

```sh
pi --model cliproxy-native/claude-opus-5-5 --thinking xhigh
```

In the TUI, use `/thinking`.

## Commands

- `/cliproxy-refresh` fetches the model list again once the current agent run
  is idle.
- `/cliproxy-status` shows the model count, the last fetch time, and the last
  discovery error with secrets removed.

Discovery only calls `/v1/models`. It sends no test generations, and the
proxy's management API can stay disabled.

## Discovery and cache

- Models marked `visibility: "hide"` by the proxy are skipped.
- The catalog is cached in `~/.pi/agent/cliproxy-provider-models.json` with
  mode 0600. It holds model metadata and the proxy URL, but no keys. A cache
  from a different URL or an older cache format is ignored.
- On the first start, Pi waits up to five seconds for discovery before it
  selects a model. Later starts register the cached models at once and refresh
  a catalog older than five minutes. There is no background polling.
- A failed refresh keeps the previous models. A valid empty list removes them.
- A listed model is not proof that your account can use it.

The proxy's `/v1/models` may return only IDs. Context and output limits come
from the proxy's `context_window`, `context_length`, `max_completion_tokens`,
or `max_output_tokens` fields when they are positive. Otherwise they come from
the exact-ID catalog entry, and otherwise from defaults: 200,000 tokens of
context and 16,384 tokens of output. A model that is in no catalog gets text
input only and no reasoning, unless the proxy advertises `thinking.levels`.
Proxy aliases without an exact catalog match count as unknown. Run `/reload`
after Pi updates its catalogs.

Costs are set to zero because API list prices say nothing about subscription
billing. Pi still reports the actual token and cache usage. A zero cost
estimate does not mean the usage is free. The extension does not keep the
prompt cache warm while idle.

## Tests

```sh
cd pi/cliproxy-provider
npm test
```

The tests use no dependencies. They cover settings precedence, URL checks,
filters, sorting, metadata fallbacks, the cache (including corrupt and
mismatched files), refresh timing, cancellation, and concurrent discovery.
Tested with Pi 1.2.0 against CLIProxyAPI with Claude and GPT models,
including streaming, tool calls, and `xhigh` thinking. Image input,
cancellation during generation, and context overflow were not tested live.

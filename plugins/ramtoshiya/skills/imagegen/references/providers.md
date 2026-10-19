# Provider reference

Checked on 2026-10-15 against the sources listed at the end. Observations about proxy routes come from test
requests made that day through CLIProxyAPI 8.0.29 (commit `5fc580b`).

## OpenAI GPT Image 2.5

OpenAI offers two models. `gpt-image-2.5-sunburst` is the base model, with higher image quality than GPT
Image 2 and better precise editing. `gpt-image-2.5-flare` is the small model, faster, with quality OpenAI
calls comparable to GPT Image 2. Both generate, edit, and produce transparent backgrounds.

The script calls the Image API:

- `POST /images/generations` with a JSON body.
- `POST /images/edits` as multipart form data. One input goes in `image`, several go in `image[]`, and an
  optional `mask` PNG applies to the first input. The mask must match the input's size and format and have
  an alpha channel. Masking is guided by the prompt, so the edited area may not follow the mask exactly.

| Parameter | Values |
| --- | --- |
| `size` | `auto`, or `WIDTHxHEIGHT` with both edges multiples of 16, no edge over 3840, a ratio within 3:1, and 655,360 to 8,294,400 pixels. OpenAI calls sizes above 2560x1440 experimental |
| `quality` | `auto` (default), `low`, `medium`, `high`, `xhigh`, `max` |
| `background` | `auto`, `opaque`, `transparent`. Transparency needs `png` or `webp` |
| `output_format` | `png` (default), `jpeg`, `webp` |
| `output_compression` | 0 to 100, for `jpeg` and `webp` |
| `n` | 1 to 10 |

The response always carries base64 data in `data[].b64_json`, so the script does not send
`response_format`. The script turns `--aspect` into these sizes:

| Aspect | Size | Aspect | Size |
| --- | --- | --- | --- |
| 1:1 | 1024x1024 | 16:9 | 1536x864 |
| 3:2 | 1536x1024 | 9:16 | 864x1536 |
| 2:3 | 1024x1536 | 2:1 | 1536x768 |
| 4:3 | 1280x960 | 1:2 | 768x1536 |
| 3:4 | 960x1280 | 21:9 | 1680x720 |

Both models cost $30 per million image output tokens on the API. Token use per image depends on the model,
quality, and size. Errors with `error.type` `image_generation_user_error` need a changed prompt or input
before a retry. `moderation_blocked` may include `moderation_details` with the stage (`input` or `output`)
and broad categories. OpenAI advises against automatic retries for quota errors.

## xAI Grok Imagine

`grok-imagine-image-2.0` is the current model. `grok-imagine-image` (1.0) is still served.
`grok-imagine-image-quality` retires on 2026-11-02, after which xAI serves its requests with
`grok-imagine-image-2.0` at `low` quality.

Both endpoints take JSON. xAI does not accept the multipart edits that the OpenAI SDK sends. For edits the
script sends `image: {"url": <data URL>, "type": "image_url"}` for one input, or `images: [...]` for up to
five. The output's aspect ratio follows the first input unless `aspect_ratio` is set.

| Parameter | Values |
| --- | --- |
| `aspect_ratio` | `auto` (default), `1:1`, `3:4`, `4:3`, `9:16`, `16:9`, `2:3`, `3:2`, `1:2`, `2:1`, `9:19.5`, `19.5:9`, `9:20`, `20:9`, `21:9`, `5:2` |
| `resolution` | `1k` (default), `2k` |
| `quality` | `auto` (default, currently `low` for generations and `medium` for edits), `low`, `medium` |
| `n` | 1 to 10 |
| `response_format` | `url` (default, a temporary link) or `b64_json`. The script asks for `b64_json` |

Grok Imagine has no transparency and no masks. It returns JPEG, PNG, or WebP, so the script names each file
by the bytes it receives. xAI rewrites prompts before generating. Its prompting guide recommends four to six
plain sentences about one picture, opening with the subject, and few exclusions.

## CLIProxyAPI routes

### GPT Image through a ChatGPT (Codex) login

The proxy forwards the request unchanged, model name included, to
`https://chatgpt.com/backend-api/codex/images/generations` or `/images/edits`. Each image counts against the
ChatGPT plan's image allowance. Test results on 2026-10-15:

- The backend chooses the output size. At `low` quality, a 1024x1024 request returned 1370x1148, and a
  1536x1024 request with a top-down prompt returned 1254x1254. The same 1536x1024 request returned exactly
  1536x1024 once the prompt asked for a wide, horizontal 3:2 composition, and a 16:9 request with a 16:9
  prompt returned 1672x941. The CLIProxyAPI maintainer says upstream ignores `size` (issue #5860).
- Requested `low` quality came back as `low` for opaque images and `medium` for transparent ones.
- `gpt-image-2`, `gpt-image-2.5-flare`, and `gpt-image-2.5-sunburst` gave the same size, quality, and
  token counts on one transparent request. The content credential (C2PA) inside each PNG names only
  "gpt-image", so the served model cannot be confirmed. Issue #5762 found all three labeled
  "gpt-image 2.0" on 2026-09-12.
- Transparent backgrounds worked on all three models. About 42% of pixels were fully transparent. The
  subject's alpha was 252 or 253 instead of 255, so it is about 1% see-through.
- Complex requests can fail near 120 seconds with `unexpected EOF`. The maintainers attribute this to
  upstream and do not retry it (issue #4309).

### Grok through an xAI login

With an OAuth login, the proxy sends image requests to `https://cli-chat-proxy.grok.com/v1`, which draws on
the X Subscription allowance. The test account had no plan, so every request failed with HTTP 402 or 403
`personal-team-blocked:spending-limit`. After a few failures the proxy answered HTTP 503
`auth_unavailable`. A successful Grok request through this route has not been tested yet.

The proxy passes only these aspect ratios: `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`, `9:20`,
`20:9`. Any other value, including `auto`, becomes `1:1` without an error.

### Account terms

Sending a subscription login through a third-party proxy can break a provider's terms.
The OpenAI and xAI pages listed below do not address the question.

## Sources

- OpenAI: [image generation guide](https://developers.openai.com/api/docs/guides/image-generation),
  [GPT Image 2.5 prompting guide](https://developers.openai.com/api/docs/guides/image-prompting),
  [pricing](https://developers.openai.com/api/docs/pricing).
- xAI: [image generation](https://docs.x.ai/developers/model-capabilities/images/generation),
  [image editing](https://docs.x.ai/developers/model-capabilities/images/editing),
  [multi-image editing](https://docs.x.ai/developers/model-capabilities/images/multi-image-editing),
  [prompting guide](https://docs.x.ai/developers/model-capabilities/images/prompting-guide),
  [`grok-imagine-image-quality` retirement](https://docs.x.ai/developers/migration/imagine-image-quality-nov-2).
- CLIProxyAPI: [repository](https://github.com/router-for-me/CLIProxyAPI), issues
  [#4309](https://github.com/router-for-me/CLIProxyAPI/issues/4309),
  [#5762](https://github.com/router-for-me/CLIProxyAPI/issues/5762),
  [#5860](https://github.com/router-for-me/CLIProxyAPI/issues/5860).
- The workflow draws on OpenAI's Codex `imagegen` skill (Apache-2.0) and the `gpt-image` and `grok-imagine`
  skills in [nikships/droidproxy](https://github.com/nikships/droidproxy) (MIT). The text and code here are
  original.

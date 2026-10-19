---
name: imagegen
description: >-
  Generate or edit raster images (photos, illustrations, product shots, UI mockups, textures, sprites,
  transparent cutouts) with OpenAI GPT Image 2.5 or xAI Grok Imagine through a bundled script that calls an
  OpenAI-compatible Images API. Use when the user asks to create, draw, render, restyle, or edit an image, or
  when a task needs a new bitmap asset. Do not use for diagrams, icons, or logos that belong in SVG,
  HTML/CSS, or canvas, or to extend an existing vector asset set. In Codex, the built-in imagegen skill
  needs no setup, so use this one only when the user asks for it or for a model it covers.
metadata:
  short-description: Generate and edit images with GPT Image 2.5 or Grok Imagine
---

# Image generation

Checked against the OpenAI and xAI image guides and CLIProxyAPI 8.0.29 on 2026-10-15. When an API changes,
update `scripts/imagegen.py`, `references/providers.md`, and this line together.

`<skill-dir>` is the directory holding this file. The script needs only the Python standard library. Run it
as `uv run --no-project python <skill-dir>/scripts/imagegen.py ...`.

## Setup

The script reads the endpoint and key from the environment. It never takes a key as an argument. Do not ask
the user to paste a key into the chat. If nothing is configured, the script exits 2 and names the variable
to set.

| Route | Environment |
| --- | --- |
| A local proxy that serves both providers, such as CLIProxyAPI | `IMAGEGEN_BASE_URL=http://127.0.0.1:8317/v1` and `IMAGEGEN_API_KEY` set to one of the proxy's `api-keys` |
| OpenAI API | `OPENAI_API_KEY`, optionally `OPENAI_BASE_URL` |
| xAI API | `XAI_API_KEY`, optionally `XAI_BASE_URL` |

`IMAGEGEN_BASE_URL` takes priority for every model when it is set.

## Choose the model

| Model | Use for |
| --- | --- |
| `gpt-image-2.5-sunburst` (default) | Final assets, small or exact text, precise edits, transparent cutouts |
| `gpt-image-2.5-flare` | Fast drafts and many variants. OpenAI rates its quality close to GPT Image 2 |
| `grok-imagine-image-2.0` | A different look when the user asks for Grok. No transparency and no masks |

Use `gpt-image-2` or older models only when the user asks for them. xAI retires
`grok-imagine-image-quality` on 2026-11-02.

## Workflow

1. Decide what the inputs are for. With no input images, run `generate`. When the user wants an existing
   image changed, run `edit` with that image. Images given only as references for subject, style, or layout
   also go through `edit`, one `--image` each, and the prompt says how to use them.
2. In the prompt, refer to each input by its position and say its role: the image to edit, a subject
   reference, a style reference, or an object to insert.
3. Write the prompt as described below. Keep a detailed request close to the user's words and only organize
   it. For a vague request, add the details that change the result, such as intended use, framing, medium,
   and lighting. Do not add characters, brands, slogans, or text the user did not ask for.
4. Run the script. Use `--quality low` while exploring and `medium` or higher for the final image,
   especially when it contains text.
5. Read the JSON on stdout. Open every file listed under `files` with your image-viewing tool and check it
   as described in [Check the result](#check-the-result). The `notes` array lists requested settings the
   service did not apply.
6. Change one thing per iteration. When refining an edit, pass the previous output as the next `--image`
   and restate everything that must stay the same.
7. Report the final path, the model, and the final prompt. Save images that belong to the project inside it
   with `--out`, and update the code or documents that reference them.

## Write the prompt

For GPT Image, labeled lines work well when a request has several requirements. Leave out lines that add
nothing.

```text
Intended use: landing page hero, wide 16:9 landscape
Subject: a white ceramic mug of black coffee
Scene: oak desk by a window, plant and notebook in soft focus
Style: clean product photography
Lighting and mood: warm morning light from the left
Text (exact): none
Avoid: logos, watermarks
```

- State the aspect ratio and orientation in the prompt as well as in `--aspect` or `--size`. Some routes
  ignore the size setting and follow the prompt.
- Put required text in quotes with its typeface and placement, ask for no other text, and spell unusual
  words letter by letter.
- For an edit, say "change only X" and list what must stay the same, such as identity, layout, lighting,
  and labels. Repeat that list on every iteration.
- For a transparent cutout, describe an isolated subject with no backdrop, floor, or shadow, and pass
  `--background transparent --format png`. If the prompt describes a scene, the model paints that scene
  instead of transparency.

For Grok, write four to six plain sentences that describe one picture. Open with the subject and what holds
it, then the setting, light, and crop. Keep avoid-lists short. For an edit, lead with the one to three
changes, then add one sentence keeping the same subject, angle, and crop.

## Run the script

```sh
# New image. A prompt file avoids shell quoting problems with long prompts.
uv run --no-project python <skill-dir>/scripts/imagegen.py generate \
  --prompt-file /tmp/prompt.txt --aspect 16:9 --quality low --out assets/hero.png

# Edit an image, or build a new one from references (repeat --image).
uv run --no-project python <skill-dir>/scripts/imagegen.py edit \
  --image assets/photo.png --prompt "Change only the mug to matte navy. Keep everything else." \
  --out assets/photo-navy.png

# Transparent cutout (GPT Image only).
uv run --no-project python <skill-dir>/scripts/imagegen.py generate \
  --prompt "A single red apple, isolated, no backdrop, no shadow." \
  --background transparent --format png --out assets/apple.png

# Grok.
uv run --no-project python <skill-dir>/scripts/imagegen.py generate \
  --model grok-imagine-image-2.0 --prompt-file /tmp/prompt.txt --aspect 3:2 --quality medium
```

Add `--dry-run` to print the request without sending it. `--help` lists every option. The ones that depend
on the provider are `--size`, `--background`, `--format`, `--compression`, and `--mask` (GPT Image only),
and `--resolution 1k|2k` (Grok only). `--aspect` works for both.

The saved file's extension follows the bytes the service returned, so `--out hero.jpg` may save
`hero.png`. The script does not overwrite an existing file. It writes `hero-v2.png` instead unless
`--force` is given. Without `--out`, files go to `output/imagegen/` under the current directory.

## Check the result

- Does the image show the requested subject, style, and composition?
- Is all required text spelled correctly and readable?
- For an edit, did only the requested part change?
- Does the shape match? If `notes` reports a different aspect ratio, restate it in the prompt and try once
  more, or crop locally.
- For transparency, does the file entry show `"alpha": true`? A drawn checkerboard is not transparency.

If a region must stay pixel-identical, composite the approved edit into the original instead of relying on
the prompt.

## Errors

Exit 1 means the service or network failed. Stderr has the service's message and a hint. Do not retry
moderation blocks, quota or credit errors, or `auth_unavailable`. Report them to the user. A timeout on a
proxy route usually means the upstream closed the request after about 120 seconds, so lower the quality or
simplify the prompt before one more try. Exit 2 means a bad option or missing configuration, and the
message names it.

## Reference

`references/providers.md` lists each provider's parameters and limits, and what the CLIProxyAPI routes
actually do with them.

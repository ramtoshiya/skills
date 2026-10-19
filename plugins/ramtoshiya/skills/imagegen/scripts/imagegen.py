#!/usr/bin/env python3
"""Generate or edit images through an OpenAI-compatible Images API.

Providers, chosen from the model name or --provider:
  openai  gpt-image-* models. JSON for generations, multipart for edits.
  xai     grok-imagine-image* models. JSON for generations and edits.

Endpoint and credentials come from the environment:
  IMAGEGEN_BASE_URL, IMAGEGEN_API_KEY  one endpoint for every provider, such as a
                                       local proxy. The key is optional here.
  OPENAI_BASE_URL, OPENAI_API_KEY      OpenAI, used when IMAGEGEN_BASE_URL is unset.
  XAI_BASE_URL, XAI_API_KEY            xAI, used when IMAGEGEN_BASE_URL is unset.

On success, prints one JSON object on stdout that lists the saved files with
their real format, pixel size, and alpha channel, plus notes about requested
settings the service did not honor. Errors go to stderr.

Exit codes: 0 success, 1 API or network failure, 2 invalid arguments or
configuration. Standard library only.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

DEFAULT_MODEL = "gpt-image-2.5-sunburst"
DEFAULT_OUT_DIR = "output/imagegen"
DEFAULT_TIMEOUT = 300
MAX_INPUT_BYTES = 50 * 1024 * 1024
USER_AGENT = "imagegen-skill/1"

OPENAI_QUALITIES = ("auto", "low", "medium", "high", "xhigh", "max")
OPENAI_BACKGROUNDS = ("auto", "opaque", "transparent")
OPENAI_FORMATS = ("png", "jpeg", "webp")
# Sizes chosen for each aspect ratio: multiples of 16, about 1 to 1.5 megapixels.
OPENAI_ASPECT_SIZES = {
    "1:1": "1024x1024",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
    "4:3": "1280x960",
    "3:4": "960x1280",
    "16:9": "1536x864",
    "9:16": "864x1536",
    "2:1": "1536x768",
    "1:2": "768x1536",
    "21:9": "1680x720",
}

XAI_QUALITIES = ("auto", "low", "medium")
XAI_RESOLUTIONS = ("1k", "2k")
XAI_ASPECTS = (
    "auto", "1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2", "1:2", "2:1",
    "9:19.5", "19.5:9", "9:20", "20:9", "21:9", "5:2",
)
XAI_MAX_EDIT_IMAGES = 5

ERROR_HINTS = (
    ("moderation_blocked", "Blocked by moderation. Do not retry the same request or reword it to get around the filter."),
    ("usage_limit_reached", "The subscription image quota is used up. Do not retry in a loop. Tell the user when it resets if the body says."),
    ("run out of credits", "The xAI account has no usable plan or credits. Do not retry."),
    ("auth_unavailable", "The proxy has no usable account for this model right now. Do not retry until the account is fixed."),
    ("insufficient_quota", "The account is out of quota or has a billing problem. Do not retry."),
    ("image_generation_user_error", "Fix the prompt or input images before retrying."),
    ("auth_not_found", "The endpoint has no signed-in account for this provider."),
)


class UsageError(Exception):
    """Invalid arguments or configuration (exit code 2)."""


class ApiError(Exception):
    """The service or the network failed (exit code 1)."""


# Argument handling


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or edit images through an OpenAI-compatible Images API.")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Create new images from a prompt")
    edit = sub.add_parser("edit", help="Edit or combine existing images")
    for p in (gen, edit):
        p.add_argument("--prompt", help="Prompt text")
        p.add_argument("--prompt-file", help="Read the prompt from a file, or - for stdin")
        p.add_argument("--model", default=DEFAULT_MODEL, help=f"Model id (default {DEFAULT_MODEL})")
        p.add_argument("--provider", choices=("openai", "xai"), help="Override the provider inferred from the model")
        p.add_argument("--size", help="OpenAI only: WIDTHxHEIGHT or auto")
        p.add_argument("--aspect", help="Aspect ratio such as 16:9. Mapped to a size for OpenAI")
        p.add_argument("--quality", help="openai: auto|low|medium|high|xhigh|max, xai: auto|low|medium")
        p.add_argument("--background", choices=OPENAI_BACKGROUNDS, help="OpenAI only")
        p.add_argument("--format", dest="output_format", choices=OPENAI_FORMATS, help="OpenAI only")
        p.add_argument("--compression", type=int, help="OpenAI only: 0-100 for jpeg or webp")
        p.add_argument("--resolution", choices=XAI_RESOLUTIONS, help="xAI only")
        p.add_argument("--n", type=int, default=1, help="Number of images, 1-10")
        p.add_argument("--out", help="Output file path. The extension follows the returned format")
        p.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help=f"Directory for generated names (default {DEFAULT_OUT_DIR})")
        p.add_argument("--force", action="store_true", help="Overwrite existing files instead of writing -v2 siblings")
        p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Seconds to wait (default {DEFAULT_TIMEOUT})")
        p.add_argument("--dry-run", action="store_true", help="Print the request without sending it")
    edit.add_argument("--image", action="append", required=True, help="Input image. Repeat for several")
    edit.add_argument("--mask", help="OpenAI only: PNG whose transparent area marks the region to edit")
    return parser.parse_args(argv)


def read_prompt(args: argparse.Namespace) -> str:
    if bool(args.prompt) == bool(args.prompt_file):
        raise UsageError("pass exactly one of --prompt or --prompt-file")
    if args.prompt:
        text = args.prompt
    elif args.prompt_file == "-":
        text = sys.stdin.read()
    else:
        path = Path(args.prompt_file)
        if not path.is_file():
            raise UsageError(f"prompt file not found: {path}")
        text = path.read_text(encoding="utf-8")
    text = text.strip()
    if not text:
        raise UsageError("the prompt is empty")
    return text


def infer_provider(model: str, override: str | None) -> str:
    if override:
        return override
    name = model.lower()
    if name.startswith("gpt-image-"):
        return "openai"
    if name.startswith("grok-imagine-image"):
        return "xai"
    raise UsageError(f"cannot tell the provider for model {model!r}. Pass --provider openai or --provider xai")


def endpoint_config(provider: str) -> tuple[str, str | None]:
    shared_base = os.environ.get("IMAGEGEN_BASE_URL", "").strip()
    if shared_base:
        return shared_base.rstrip("/"), os.environ.get("IMAGEGEN_API_KEY", "").strip() or None
    if provider == "openai":
        base = os.environ.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
        return base.rstrip("/"), os.environ.get("OPENAI_API_KEY", "").strip() or None
    base = os.environ.get("XAI_BASE_URL", "").strip() or "https://api.x.ai/v1"
    return base.rstrip("/"), os.environ.get("XAI_API_KEY", "").strip() or None


def validate_openai_size(size: str) -> None:
    if size == "auto":
        return
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", size)
    if not match:
        raise UsageError("--size must be WIDTHxHEIGHT, for example 1536x1024, or auto")
    width, height = int(match.group(1)), int(match.group(2))
    if width % 16 or height % 16:
        raise UsageError("--size edges must be multiples of 16")
    if max(width, height) > 3840:
        raise UsageError("--size edges must be at most 3840")
    if max(width, height) / min(width, height) > 3:
        raise UsageError("--size aspect ratio must be between 1:3 and 3:1")
    if not 655_360 <= width * height <= 8_294_400:
        raise UsageError("--size must total between 655,360 and 8,294,400 pixels")


def check_options(args: argparse.Namespace, provider: str) -> None:
    if not 1 <= args.n <= 10:
        raise UsageError("--n must be between 1 and 10")
    if args.timeout < 1:
        raise UsageError("--timeout must be positive")
    if provider == "openai":
        if args.resolution:
            raise UsageError("--resolution is for xAI. Use --size or --aspect with OpenAI")
        if args.quality and args.quality not in OPENAI_QUALITIES:
            raise UsageError(f"--quality for OpenAI must be one of {', '.join(OPENAI_QUALITIES)}")
        if args.aspect and args.aspect not in OPENAI_ASPECT_SIZES:
            raise UsageError(f"--aspect for OpenAI must be one of {', '.join(OPENAI_ASPECT_SIZES)}, or pass --size")
        if args.size:
            validate_openai_size(args.size)
        if args.compression is not None:
            if not 0 <= args.compression <= 100:
                raise UsageError("--compression must be between 0 and 100")
            if args.output_format not in ("jpeg", "webp"):
                raise UsageError("--compression needs --format jpeg or webp")
        if args.background == "transparent" and args.output_format == "jpeg":
            raise UsageError("a transparent background needs --format png or webp")
    else:
        for flag, value in (("--size", args.size), ("--background", args.background),
                            ("--format", args.output_format), ("--compression", args.compression)):
            if value is not None:
                hint = " Grok Imagine has no transparency. Generate on a flat background and key it out locally." \
                    if flag == "--background" else ""
                raise UsageError(f"{flag} is not supported for xAI.{hint}")
        if getattr(args, "mask", None):
            raise UsageError("--mask is not supported for xAI. Describe the region to change in the prompt")
        if args.quality and args.quality not in XAI_QUALITIES:
            raise UsageError(f"--quality for xAI must be one of {', '.join(XAI_QUALITIES)}")
        if args.aspect and args.aspect not in XAI_ASPECTS:
            raise UsageError(f"--aspect for xAI must be one of {', '.join(XAI_ASPECTS)}")
        if args.command == "edit" and len(args.image) > XAI_MAX_EDIT_IMAGES:
            raise UsageError(f"xAI accepts at most {XAI_MAX_EDIT_IMAGES} input images")


# Image files


def sniff_format(blob: bytes) -> str | None:
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if blob[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    return None


def png_info(blob: bytes) -> tuple[int, int, bool]:
    width, height = struct.unpack(">II", blob[16:24])
    alpha = blob[25] in (4, 6)
    pos = 8
    while not alpha and pos + 8 <= len(blob):
        length = struct.unpack(">I", blob[pos:pos + 4])[0]
        kind = blob[pos + 4:pos + 8]
        if kind == b"tRNS":
            alpha = True
        if kind in (b"IDAT", b"IEND"):
            break
        pos += 12 + length
    return width, height, alpha


def jpeg_info(blob: bytes) -> tuple[int, int, bool]:
    pos = 2
    while pos + 9 < len(blob):
        if blob[pos] != 0xFF:
            pos += 1
            continue
        marker = blob[pos + 1]
        if marker in (0xD8, 0x01, 0xFF) or 0xD0 <= marker <= 0xD7:
            pos += 1 if marker == 0xFF else 2
            continue
        length = struct.unpack(">H", blob[pos + 2:pos + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", blob[pos + 5:pos + 9])
            return width, height, False
        pos += 2 + length
    return 0, 0, False


def webp_info(blob: bytes) -> tuple[int, int, bool]:
    chunk = blob[12:16]
    if chunk == b"VP8X":
        alpha = bool(blob[20] & 0x10)
        width = 1 + int.from_bytes(blob[24:27], "little")
        height = 1 + int.from_bytes(blob[27:30], "little")
        return width, height, alpha
    if chunk == b"VP8L":
        bits = int.from_bytes(blob[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1, bool((bits >> 28) & 1)
    if chunk == b"VP8 ":
        width = int.from_bytes(blob[26:28], "little") & 0x3FFF
        height = int.from_bytes(blob[28:30], "little") & 0x3FFF
        return width, height, False
    return 0, 0, False


def image_info(blob: bytes) -> dict:
    fmt = sniff_format(blob)
    readers = {"png": png_info, "jpeg": jpeg_info, "webp": webp_info}
    width, height, alpha = readers[fmt](blob) if fmt else (0, 0, False)
    return {"format": fmt or "unknown", "width": width, "height": height, "alpha": alpha}


def load_input_image(path_text: str, role: str) -> tuple[Path, bytes, str]:
    path = Path(path_text)
    if not path.is_file():
        raise UsageError(f"{role} not found: {path}")
    blob = path.read_bytes()
    if len(blob) > MAX_INPUT_BYTES:
        raise UsageError(f"{role} is larger than 50 MB: {path}")
    fmt = sniff_format(blob)
    if not fmt:
        raise UsageError(f"{role} must be PNG, JPEG, or WebP: {path}")
    return path, blob, f"image/{fmt}"


# Requests


def encode_multipart(fields: list[tuple[str, str]], files: list[tuple[str, Path, bytes, str]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields:
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, path, blob, mime in files:
        filename = re.sub(r'["\r\n]', "_", path.name)
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        )
        chunks.append(head.encode() + blob + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def requested_openai_size(args: argparse.Namespace) -> str | None:
    if args.size:
        return args.size
    return OPENAI_ASPECT_SIZES[args.aspect] if args.aspect else None


def build_request(args: argparse.Namespace, provider: str, prompt: str) -> dict:
    """Return the request path, body, content type, and a printable preview."""
    is_edit = args.command == "edit"
    path = "/images/edits" if is_edit else "/images/generations"
    if provider == "openai":
        params: dict = {"model": args.model, "prompt": prompt}
        if args.n != 1:
            params["n"] = args.n
        for key, value in (("size", requested_openai_size(args)), ("quality", args.quality),
                           ("background", args.background), ("output_format", args.output_format),
                           ("output_compression", args.compression)):
            if value is not None:
                params[key] = value
        if not is_edit:
            body = json.dumps(params).encode()
            return {"path": path, "body": body, "content_type": "application/json", "preview": params}
        images = [load_input_image(p, "input image") for p in args.image]
        field = "image" if len(images) == 1 else "image[]"
        files = [(field, p, blob, mime) for p, blob, mime in images]
        if args.mask:
            mask_path, mask_blob, mask_mime = load_input_image(args.mask, "mask")
            if mask_mime != "image/png":
                raise UsageError("the mask must be a PNG with an alpha channel")
            files.append(("mask", mask_path, mask_blob, mask_mime))
        body, content_type = encode_multipart([(k, str(v)) for k, v in params.items()], files)
        preview = dict(params)
        preview["files"] = [f"{name}: {p} ({len(blob)} bytes)" for name, p, blob, _ in files]
        return {"path": path, "body": body, "content_type": content_type, "preview": preview}

    params = {"model": args.model, "prompt": prompt, "response_format": "b64_json"}
    if args.n != 1:
        params["n"] = args.n
    for key, value in (("aspect_ratio", args.aspect), ("resolution", args.resolution), ("quality", args.quality)):
        if value is not None:
            params[key] = value
    preview = dict(params)
    if is_edit:
        refs, described = [], []
        for p in args.image:
            image_path, blob, mime = load_input_image(p, "input image")
            refs.append({"url": f"data:{mime};base64,{base64.b64encode(blob).decode()}", "type": "image_url"})
            described.append(f"{image_path} ({len(blob)} bytes)")
        key = "image" if len(refs) == 1 else "images"
        params[key] = refs[0] if len(refs) == 1 else refs
        preview[key] = described[0] if len(refs) == 1 else described
    body = json.dumps(params).encode()
    return {"path": path, "body": body, "content_type": "application/json", "preview": preview}


def describe_http_error(status: int, text: str) -> str:
    lines = [f"HTTP {status}: {text[:2000]}"]
    hints = [hint for marker, hint in ERROR_HINTS if marker in text]
    if not hints:
        if status == 401:
            hints.append("Check the API key for this endpoint.")
        elif status == 429:
            hints.append("Rate limited. Wait before trying again.")
        elif status >= 500:
            hints.append("Server error. One later retry is reasonable.")
    lines.extend(hints)
    return "\n".join(lines)


def send(url: str, body: bytes, content_type: str, api_key: str | None, timeout: int) -> dict:
    headers = {"Content-Type": content_type, "Accept": "application/json", "User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as err:
        text = err.read().decode("utf-8", "replace")
        raise ApiError(describe_http_error(err.code, text)) from None
    except (TimeoutError, socket.timeout):
        raise ApiError(
            f"no response within {timeout} s. ChatGPT-backed proxy routes close long requests after about "
            "120 s. Try a lower --quality or a simpler prompt rather than retrying the same request."
        ) from None
    except urllib.error.URLError as err:
        raise ApiError(f"cannot reach {url}: {err.reason}. If this is a local proxy, check that it is running.") from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(f"the response is not JSON: {raw[:500].decode('utf-8', 'replace')}") from None


def download(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, socket.timeout) as err:
        raise ApiError(f"cannot download the returned image URL: {err}") from None


# Saving and reporting


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40].strip("-") or "image"


def target_path(args: argparse.Namespace, prompt: str, index: int, count: int, fmt: str, stamp: str) -> Path:
    ext = "jpg" if fmt == "jpeg" else fmt
    if args.out:
        base = Path(args.out)
        stem = base.with_suffix("") if base.suffix else base
    else:
        stem = Path(args.out_dir) / f"{slugify(prompt)}-{stamp}"
    if count > 1:
        stem = stem.with_name(f"{stem.name}-{index}")
    return stem.with_name(f"{stem.name}.{ext}")


def free_path(path: Path, force: bool) -> Path:
    if force or not path.exists():
        return path
    version = 2
    while True:
        candidate = path.with_name(f"{path.stem}-v{version}{path.suffix}")
        if not candidate.exists():
            return candidate
        version += 1


def mismatch_notes(args: argparse.Namespace, provider: str, info: dict, meta: dict) -> list[str]:
    notes = []
    width, height = info["width"], info["height"]
    wanted = None
    if provider == "openai":
        size = requested_openai_size(args)
        if size and size != "auto":
            w, h = (int(v) for v in size.split("x"))
            wanted = (w, h, size)
    elif args.aspect and args.aspect != "auto":
        a, b = (float(v) for v in args.aspect.split(":"))
        wanted = (a, b, args.aspect)
    if wanted and width and height:
        if abs((width / height) / (wanted[0] / wanted[1]) - 1) > 0.03:
            notes.append(
                f"requested {wanted[2]} but got {width}x{height} ({width / height:.2f}:1). State the orientation "
                "and aspect ratio in the prompt, or crop locally if the exact shape matters."
            )
        elif provider == "openai" and (width, height) != wanted[:2]:
            notes.append(f"requested {wanted[2]} but got {width}x{height}. The shape matches. Resize locally if exact pixels matter.")
    if args.background == "transparent" and not info["alpha"]:
        notes.append("requested a transparent background but the file has no alpha channel. "
                     "Remove backdrop words from the prompt and try once more.")
    returned_quality = meta.get("quality")
    if args.quality and returned_quality and returned_quality != args.quality:
        notes.append(f"requested quality {args.quality} but the service reports {returned_quality}.")
    return notes


def run(argv: list[str]) -> int:
    args = parse_args(argv)
    prompt = read_prompt(args)
    provider = infer_provider(args.model, args.provider)
    check_options(args, provider)
    base_url, api_key = endpoint_config(provider)
    request = build_request(args, provider, prompt)
    url = base_url + request["path"]

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "provider": provider,
            "url": url,
            "content_type": request["content_type"].split(";")[0],
            "api_key": "set" if api_key else "missing",
            "request": request["preview"],
        }, indent=2))
        return 0
    if not api_key and not os.environ.get("IMAGEGEN_BASE_URL", "").strip():
        variable = "OPENAI_API_KEY" if provider == "openai" else "XAI_API_KEY"
        raise UsageError(f"{variable} is not set. Set it, or set IMAGEGEN_BASE_URL and IMAGEGEN_API_KEY for a proxy")

    started = time.monotonic()
    response = send(url, request["body"], request["content_type"], api_key, args.timeout)
    elapsed = round(time.monotonic() - started, 1)

    items = response.get("data") or []
    if not items:
        raise ApiError(f"the response has no images: {json.dumps(response)[:1000]}")
    meta = {k: v for k, v in response.items() if k not in ("data", "usage")}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    files, notes = [], []
    for index, item in enumerate(items, start=1):
        if item.get("b64_json"):
            blob = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            blob = download(item["url"], args.timeout)
        else:
            raise ApiError(f"image {index} has neither b64_json nor url")
        info = image_info(blob)
        path = free_path(target_path(args, prompt, index, len(items), info["format"], stamp), args.force)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        asked_suffix = Path(args.out).suffix.lower() if args.out else ""
        if asked_suffix and asked_suffix != path.suffix and not (asked_suffix == ".jpeg" and path.suffix == ".jpg"):
            notes.append(f"saved {path.name} because the service returned {info['format']}, not {asked_suffix}.")
        for note in mismatch_notes(args, provider, info, meta):
            if note not in notes:
                notes.append(note)
        extra = {k: v for k, v in item.items() if k not in ("b64_json", "url")}
        files.append({"path": str(path), **info, **extra})

    print(json.dumps({
        "provider": provider,
        "model": args.model,
        "url": url,
        "elapsed_s": elapsed,
        "files": files,
        "returned": meta,
        "usage": response.get("usage"),
        "notes": notes,
    }, indent=2))
    return 0


def main() -> int:
    try:
        return run(sys.argv[1:])
    except UsageError as err:
        print(f"imagegen: {err}", file=sys.stderr)
        return 2
    except ApiError as err:
        print(f"imagegen: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Generate or edit images using Hermes's active Codex session."""

from __future__ import annotations

import argparse
import base64
import binascii
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Any
from urllib import error, request
import warnings

from PIL import Image, UnidentifiedImageError


GENERATIONS_URL = "https://chatgpt.com/backend-api/codex/images/generations"
EDITS_URL = "https://chatgpt.com/backend-api/codex/images/edits"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_TIMEOUT = 600
MAX_TIMEOUT = 600
MAX_COUNT = 10
MAX_INPUT_IMAGES = 16
MAX_PROMPT_CHARS = 32_000
MAX_INPUT_IMAGE_BYTES = 15 * 1024 * 1024
MAX_TOTAL_INPUT_IMAGE_BYTES = 45 * 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_BASE64_CHARS = 64 * 1024 * 1024
MAX_DECODED_PIXELS = 40_000_000
AUTH_CLAIM = "https://api.openai.com/auth"
ACCOUNT_ID_CLAIM = "chatgpt_account_id"
FORMATS = {"png": "PNG", "jpeg": "JPEG", "jpg": "JPEG", "webp": "WEBP"}
MIME_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class CliError(RuntimeError):
    """A safe error suitable for display to the caller."""


def read_prompt(prompt: str | None, prompt_file: str | None) -> str:
    if prompt is not None and prompt_file is not None:
        raise CliError("Use --prompt or --prompt-file, not both.")
    if prompt_file is not None:
        try:
            with Path(prompt_file).open("r", encoding="utf-8", newline="") as stream:
                value = stream.read(MAX_PROMPT_CHARS + 1)
        except (OSError, UnicodeError) as exc:
            raise CliError(f"Cannot read prompt file: {prompt_file}") from exc
    elif prompt is not None:
        value = prompt
    else:
        raise CliError("Missing prompt. Use --prompt or --prompt-file.")
    if not value.strip():
        raise CliError("Prompt is empty.")
    if len(value) > MAX_PROMPT_CHARS:
        raise CliError(f"Prompt exceeds {MAX_PROMPT_CHARS} characters.")
    return value


def normalize_format(value: str) -> str:
    lowered = value.lower()
    if lowered not in FORMATS:
        raise CliError("output-format must be png, jpeg, jpg, or webp.")
    return "jpeg" if lowered == "jpg" else lowered


def parse_size(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"([1-9][0-9]*)x([1-9][0-9]*)", value)
    return (int(match.group(1)), int(match.group(2))) if match else None


def validate_size(size: str, model: str) -> None:
    if size == "auto":
        return
    dimensions = parse_size(size)
    if dimensions is None:
        raise CliError("size must be auto or WIDTHxHEIGHT.")
    width, height = dimensions
    if "gpt-image-2" not in model:
        if size not in {"1024x1024", "1536x1024", "1024x1536"}:
            raise CliError("This model supports 1024x1024, 1536x1024, 1024x1536, or auto.")
        return
    if max(width, height) > 3840:
        raise CliError("gpt-image-2 max edge must be <= 3840.")
    if width % 16 or height % 16:
        raise CliError("gpt-image-2 dimensions must be multiples of 16.")
    if max(width, height) / min(width, height) > 3:
        raise CliError("gpt-image-2 aspect ratio must be <= 3:1.")
    if not 655_360 <= width * height <= 8_294_400:
        raise CliError("gpt-image-2 pixels must be between 655360 and 8294400.")


def detect_format(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "WEBP"
    raise CliError("Image bytes are not PNG, JPEG, or WebP.")


def fully_decode_image(data: bytes, expected_format: str | None = None) -> tuple[str, tuple[int, int]]:
    magic_format = detect_format(data)
    if expected_format is not None and magic_format != expected_format:
        raise CliError(
            f"Image format mismatch: expected {expected_format}, received {magic_format}."
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                declared_format = image.format
                dimensions = image.size
                if dimensions[0] * dimensions[1] > MAX_DECODED_PIXELS:
                    raise CliError(
                        f"Image exceeds the {MAX_DECODED_PIXELS}-pixel decoded limit."
                    )
                image.load()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        EOFError,
        OSError,
        OverflowError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise CliError("Image failed full Pillow decoding.") from exc
    if declared_format != magic_format:
        raise CliError("Image magic bytes and decoded format do not match.")
    return magic_format, dimensions


def read_input_image(raw_path: str) -> bytes:
    path = Path(raw_path)
    try:
        with path.open("rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise CliError(f"Input image is not a file: {raw_path}")
            data = stream.read(MAX_INPUT_IMAGE_BYTES + 1)
    except OSError as exc:
        raise CliError(f"Cannot read input image: {raw_path}") from exc
    if len(data) > MAX_INPUT_IMAGE_BYTES:
        raise CliError(f"Input image exceeds {MAX_INPUT_IMAGE_BYTES} bytes: {raw_path}")
    return data


def read_input_images(paths: list[str]) -> list[bytes]:
    images: list[bytes] = []
    total = 0
    for path in paths:
        data = read_input_image(path)
        total += len(data)
        if total > MAX_TOTAL_INPUT_IMAGE_BYTES:
            raise CliError(
                f"Aggregate input images exceed {MAX_TOTAL_INPUT_IMAGE_BYTES} bytes."
            )
        images.append(data)
    return images


def image_data_url(data: bytes) -> str:
    image_format, _ = fully_decode_image(data)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{MIME_TYPES[image_format]};base64,{encoded}"


def build_request(args: argparse.Namespace, prompt: str) -> tuple[str, str, dict[str, Any], bytes]:
    images = args.image or []
    if len(images) > MAX_INPUT_IMAGES:
        raise CliError(f"At most {MAX_INPUT_IMAGES} input images are supported.")
    if args.mask and not images:
        raise CliError("--mask requires at least one --image.")
    input_paths = [*images, *([args.mask] if args.mask else [])]
    input_data = read_input_images(input_paths)
    if not 1 <= args.count <= MAX_COUNT:
        raise CliError(f"--count must be between 1 and {MAX_COUNT}.")
    if not 1 <= args.timeout <= MAX_TIMEOUT:
        raise CliError(f"--timeout must be between 1 and {MAX_TIMEOUT} seconds.")
    if args.quality not in {"low", "medium", "high", "auto"}:
        raise CliError("quality must be low, medium, high, or auto.")
    if args.background not in {"auto", "opaque"}:
        raise CliError("background must be auto or opaque.")
    if args.moderation not in {"low", "auto"}:
        raise CliError("moderation must be low or auto.")
    output_format = normalize_format(args.output_format)
    compression = args.output_compression
    if compression is None and output_format in {"jpeg", "webp"}:
        compression = 100
    if compression is not None:
        if output_format not in {"jpeg", "webp"}:
            raise CliError("output-compression is only valid for jpeg or webp.")
        if not 0 <= compression <= 100:
            raise CliError("output-compression must be between 0 and 100.")
    validate_size(args.size, args.model)

    body: dict[str, Any] = {
        "prompt": prompt,
        "model": args.model,
        "n": args.count,
        "size": args.size,
        "quality": args.quality,
        "background": args.background,
        "moderation": args.moderation,
        "output_format": output_format,
    }
    if compression is not None:
        body["output_compression"] = compression
    operation = "edit" if images else "generate"
    if images:
        body["images"] = [
            {"image_url": image_data_url(data)} for data in input_data[: len(images)]
        ]
        if args.mask:
            body["mask"] = {"image_url": image_data_url(input_data[-1])}
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise CliError(f"Request exceeds {MAX_REQUEST_BYTES} bytes.")
    url = EDITS_URL if operation == "edit" else GENERATIONS_URL
    return operation, output_format, body, encoded


def decode_jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise CliError("Hermes Codex credential is not a valid JWT; authenticate through Hermes.")
    segment = parts[1]
    try:
        raw = base64.b64decode(segment + "=" * (-len(segment) % 4), altchars=b"-_", validate=True)
        claims = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeError, json.JSONDecodeError) as exc:
        raise CliError("Hermes Codex credential has invalid JWT claims; authenticate through Hermes.") from exc
    if not isinstance(claims, dict):
        raise CliError("Hermes Codex credential has invalid JWT claims; authenticate through Hermes.")
    return claims


def account_id_from_token(token: str) -> str:
    auth_claim = decode_jwt_claims(token).get(AUTH_CLAIM)
    account_id = auth_claim.get(ACCOUNT_ID_CLAIM) if isinstance(auth_claim, dict) else None
    if not isinstance(account_id, str) or not account_id.strip():
        raise CliError("Hermes Codex credential lacks an account claim; authenticate through Hermes.")
    return account_id.strip()


def resolve_credentials() -> tuple[str, str]:
    try:
        from hermes_cli.auth import resolve_codex_runtime_credentials

        runtime = resolve_codex_runtime_credentials(refresh_if_expiring=True)
    except Exception as exc:
        raise CliError("Codex credentials are unavailable; authenticate through Hermes.") from exc
    token = runtime.get("api_key") if isinstance(runtime, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise CliError("Codex credentials are unavailable; authenticate through Hermes.")
    token = token.strip()
    return token, account_id_from_token(token)


class NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_request(url: str, encoded: bytes, token: str, account_id: str, timeout: int) -> dict[str, Any]:
    if url not in {GENERATIONS_URL, EDITS_URL}:
        raise CliError("Refusing a non-Codex Images destination.")
    req = request.Request(
        url,
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "ChatGPT-Account-ID": account_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "originator": "hermes-codex-gpt-image",
            "User-Agent": "hermes-codex-gpt-image-skill/1.0",
        },
    )
    try:
        opener = request.build_opener(NoRedirectHandler())
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except error.HTTPError as exc:
        if 300 <= exc.code < 400:
            message = f"Codex Images redirect refused (HTTP {exc.code})."
        elif exc.code in {401, 403}:
            message = f"Codex authorization rejected (HTTP {exc.code}); re-authenticate through Hermes."
        elif exc.code == 429:
            message = "Codex Images rate limit reached (HTTP 429); no retry was attempted."
        else:
            message = f"Codex Images request failed (HTTP {exc.code}); no retry was attempted."
        raise CliError(message) from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise CliError("Codex Images network request failed; no retry was attempted.") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise CliError(f"Response exceeds {MAX_RESPONSE_BYTES} bytes.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CliError("Codex Images returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise CliError("Codex Images returned a non-object JSON response.")
    if "error" in value:
        raise CliError("Codex Images returned an API error; no retry was attempted.")
    return value


def extract_payloads(response: dict[str, Any], count: int) -> list[str]:
    items = response.get("data")
    if not isinstance(items, list) or not items:
        raise CliError("Codex Images response contains no image data.")
    if len(items) != count:
        raise CliError(
            f"Codex Images returned {len(items)} images; {count} were requested."
        )
    payloads: list[str] = []
    for item in items:
        payload = item.get("b64_json") if isinstance(item, dict) else None
        if not isinstance(payload, str):
            raise CliError("Codex Images response contains an invalid image entry.")
        payloads.append(payload)
    return payloads


def output_paths(out: str, count: int, output_format: str) -> list[Path]:
    target = Path(out)
    accepted_suffixes = {
        "jpeg": {".jpg", ".jpeg"},
        "png": {".png"},
        "webp": {".webp"},
    }[output_format]
    if not target.suffix:
        target = target.with_name(
            target.name + (".jpg" if output_format == "jpeg" else f".{output_format}")
        )
    elif target.suffix not in accepted_suffixes:
        accepted = " or ".join(sorted(accepted_suffixes))
        raise CliError(
            f"Output extension {target.suffix} does not match {output_format}; use {accepted}."
        )
    if count == 1:
        return [target]
    stem = target.stem or "image"
    return [
        target.with_name(f"{stem}-{index:02d}{target.suffix}")
        for index in range(1, count + 1)
    ]


def decode_payload(payload: str, output_format: str) -> tuple[bytes, str, tuple[int, int]]:
    if len(payload) > MAX_BASE64_CHARS:
        raise CliError("Image payload exceeds the encoded size limit.")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CliError("Image payload is not strict base64.") from exc
    image_format, dimensions = fully_decode_image(data, FORMATS[output_format])
    return data, image_format, dimensions


def atomic_write(path: Path, data: bytes, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise CliError(f"Output exists; use --overwrite: {path}")
    partial = path.with_name(f".{path.name}.partial-{os.getpid()}")
    try:
        with partial.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(partial, path)
        else:
            try:
                os.link(partial, path)
            except FileExistsError as exc:
                raise CliError(f"Output exists; use --overwrite: {path}") from exc
            partial.unlink()
    except CliError:
        raise
    except OSError as exc:
        raise CliError(f"Cannot write output: {path}") from exc
    finally:
        try:
            partial.unlink()
        except FileNotFoundError:
            pass


def save_images(
    payloads: list[str], out: str, output_format: str, requested_size: str, overwrite: bool
) -> list[dict[str, Any]]:
    paths = output_paths(out, len(payloads), output_format)
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        raise CliError(f"Output exists; use --overwrite: {existing[0]}")
    results: list[dict[str, Any]] = []
    for payload, path in zip(payloads, paths):
        try:
            data, actual_format, (width, height) = decode_payload(payload, output_format)
            atomic_write(path, data, overwrite)
        except CliError as exc:
            if results:
                validated = ", ".join(item["path"] for item in results)
                raise CliError(f"{exc} Validated outputs before failure: {validated}") from exc
            raise
        requested = parse_size(requested_size)
        mismatch = requested is not None and requested != (width, height)
        results.append(
            {
                "path": str(path),
                "bytes": len(data),
                "actual_format": actual_format.lower(),
                "requested_dimensions": (
                    {"width": requested[0], "height": requested[1]} if requested else None
                ),
                "actual_dimensions": {"width": width, "height": height},
                "dimension_mismatch": mismatch,
            }
        )
    return results


def command_generate(args: argparse.Namespace) -> int:
    prompt = read_prompt(args.prompt, args.prompt_file)
    operation, output_format, body, encoded = build_request(args, prompt)
    output_paths(args.out, args.count, output_format)
    url = EDITS_URL if operation == "edit" else GENERATIONS_URL
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "operation": operation,
                    "destination": url,
                    "model": args.model,
                    "size": args.size,
                    "quality": args.quality,
                    "background": args.background,
                    "moderation": args.moderation,
                    "output_format": output_format,
                    "output_compression": body.get("output_compression"),
                    "count": args.count,
                    "input_images": len(args.image or []),
                    "mask": bool(args.mask),
                    "request_bytes": len(encoded),
                    "authentication": "not resolved",
                    "network": "not used",
                },
                indent=2,
            )
        )
        return 0
    token, account_id = resolve_credentials()
    started = time.monotonic()
    response = post_request(url, encoded, token, account_id, args.timeout)
    outputs = save_images(
        extract_payloads(response, args.count),
        args.out,
        output_format,
        args.size,
        args.overwrite,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "operation": operation,
                "model": args.model,
                "requested_size": args.size,
                "output_count": len(outputs),
                "outputs": outputs,
                "warnings": [
                    f"Actual dimensions differ from requested dimensions: {item['path']}"
                    for item in outputs
                    if item["dimension_mismatch"]
                ],
                "elapsed_seconds": round(time.monotonic() - started, 3),
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or edit GPT images using the active Hermes Codex session."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="Generate or edit images.")
    prompt_group = generate.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt", "-p")
    prompt_group.add_argument("--prompt-file")
    generate.add_argument("--image", "-i", action="append", help="Edit/reference image; repeatable.")
    generate.add_argument("--mask", help="Mask image; requires --image.")
    generate.add_argument("--out", "-o", required=True)
    generate.add_argument("--model", default=DEFAULT_MODEL)
    generate.add_argument("--size", default="auto")
    generate.add_argument("--quality", default="auto", choices=["auto", "high", "low", "medium"])
    generate.add_argument("--background", default="auto", choices=["auto", "opaque"])
    generate.add_argument("--moderation", default="auto", choices=["auto", "low"])
    generate.add_argument("--output-format", default="png", choices=["jpeg", "jpg", "png", "webp"])
    generate.add_argument("--output-compression", type=int)
    generate.add_argument("--count", type=int, default=1)
    generate.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    generate.add_argument("--overwrite", action="store_true")
    generate.add_argument("--dry-run", action="store_true")
    generate.set_defaults(func=command_generate)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except CliError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

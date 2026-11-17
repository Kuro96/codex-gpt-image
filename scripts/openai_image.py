#!/usr/bin/env python3
"""Official OpenAI Images API; reuse bounded image I/O from the legacy helper."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import time
from urllib import request, error
from dotenv import dotenv_values
import hermes_codex_image as io

GENERATIONS_URL = "https://api.openai.com/v1/images/generations"
EDITS_URL = "https://api.openai.com/v1/images/edits"
MODELS = ("gpt-image-2.6-flare", "gpt-image-2.6-sunburst")

def resolve_key():
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    key = os.environ.get("OPENAI_API_KEY") or dotenv_values(home / ".env").get("OPENAI_API_KEY")
    if not key or not key.strip():
        raise io.CliError("Set OPENAI_API_KEY in the active Hermes .env.")
    return key.strip()

def post(url, encoded, key, timeout):
    if url not in (GENERATIONS_URL, EDITS_URL):
        raise io.CliError("Refusing a non-official OpenAI Images destination.")
    req = request.Request(url, data=encoded, method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": "hermes-openai-image/1.0"})
    try:
        with request.build_opener(io.NoRedirectHandler()).open(req, timeout=timeout) as response:
            raw = response.read(io.MAX_RESPONSE_BYTES + 1)
            request_id = response.headers.get("x-request-id")
    except error.HTTPError as exc:
        # Never print request headers, credential strings or unfiltered response bodies.
        raise io.CliError(f"OpenAI Images HTTP {exc.code}; no retry attempted.") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise io.CliError("OpenAI Images network failure; no retry attempted.") from exc
    if len(raw) > io.MAX_RESPONSE_BYTES:
        raise io.CliError("Response exceeds byte limit.")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise io.CliError("OpenAI Images returned invalid JSON.") from exc
    if not isinstance(data, dict) or "error" in data:
        raise io.CliError("OpenAI Images returned an API error.")
    return data, request_id

def build_parser():
    parser = io.build_parser()
    parser.description = "Generate/edit through the official OpenAI Images API."
    sub = next(a for a in parser._actions if getattr(a, "choices", None) and isinstance(a.choices, dict))
    generate = sub.choices["generate"]
    generate.set_defaults(model="gpt-image-2.6-sunburst", quality="medium", func=run)
    for action in generate._actions:
        if action.dest == "model":
            action.choices = MODELS
    generate.add_argument("--complexity", choices=["low", "medium", "high"])
    return parser

def run(args):
    prompt = io.read_prompt(args.prompt, args.prompt_file)
    operation, fmt, body, _ = io.build_request(args, prompt)
    if args.complexity:
        body["complexity"] = args.complexity
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > io.MAX_REQUEST_BYTES:
        raise io.CliError("Request exceeds byte limit.")
    paths = io.output_paths(args.out, args.count, fmt)
    if not args.overwrite and any(p.exists() for p in paths):
        raise io.CliError("Output exists; select a new path or use --overwrite.")
    url = EDITS_URL if operation == "edit" else GENERATIONS_URL
    summary = {"operation": operation, "destination": url, "model": args.model,
               "quality": args.quality, "complexity": args.complexity,
               "requested_size": args.size, "count": args.count}
    if args.dry_run:
        print(json.dumps(dict(summary, dry_run=True, authentication="not resolved", network="not used")))
        return 0
    key = resolve_key()
    start = time.monotonic()
    data, request_id = post(url, encoded, key, args.timeout)
    outputs = io.save_images(io.extract_payloads(data, args.count), args.out, fmt, args.size, args.overwrite)
    print(json.dumps(dict(summary, ok=True, request_id=request_id, usage=data.get("usage"),
        elapsed_seconds=round(time.monotonic()-start, 3), output_count=len(outputs), outputs=outputs,
        warnings=["Dimension mismatch: " + x["path"] for x in outputs if x["dimension_mismatch"]]),
        ensure_ascii=False, indent=2))
    return 0

def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except io.CliError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())

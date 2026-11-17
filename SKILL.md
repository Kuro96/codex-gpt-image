---
name: codex-gpt-image
description: "Use when generating or editing GPT images through the OpenAI Images API."
version: 2.0.1
license: MIT
---

# OpenAI Image Generation

Generate raster images, edit supplied references, and create animated GIFs through the OpenAI Images API.

## Setup

Requires Python 3.10+, Pillow, and python-dotenv. Run commands from this skill directory with a Python environment containing these dependencies.

Credentials are resolved from `OPENAI_API_KEY`, then from `$HERMES_HOME/.env`. When `HERMES_HOME` is unset, the fallback is `~/.hermes/.env`.

## Still images and edits

```bash
python scripts/openai_image.py generate --prompt "A whale swimming among clouds" --out image.png
```

For an edit, add `--image reference.png`; repeat the option for multiple references. `--mask mask.png` requires a reference. Use `--prompt-file prompt.txt` for multiline input. Preserve the supplied prompt and use explicitly selected reference images.

Options:

- `--model`: `gpt-image-2.6-sunburst` (default), `gpt-image-2.6-flare`.
- `--quality`: `auto`, `low`, `medium` (default), `high`.
- `--size`: `auto` (default) or `WIDTHxHEIGHT`. The validator accepts multiples of 16, a maximum edge of 3840, aspect ratio up to 3:1, and 655360–8294400 pixels. Service acceptance may impose additional constraints.
- `--complexity`: `low`, `medium`, `high`; omitted by default.
- `--output-format`: `png`, `jpeg`/`jpg`, `webp`; match the output extension.
- `--output-compression`: 0–100 for JPEG/WebP.
- `--background`: `auto`, `opaque`.
- `--moderation`: `auto` (default), `low`.
- `--count`: 1–10.
- `--timeout`: 1–600 seconds.
- `--overwrite`: replace existing output files.
- `--dry-run`: validate inputs and report request metadata before authentication or network access.

## Animated GIFs

```bash
python scripts/openai_gif.py --prompt "A whale waving its tail, seamless loop" --out animation.gif
```

GIF generation accepts `--model`, `--quality`, `--prompt-file`, `--size`, `--frame-count`, `--frame-duration-ms`, `--timeout`, and `--dry-run`. Defaults are 512×512, 12 frames, and 150 ms per frame. The helper accepts 2–16 requested frames, 20–2000 ms per frame, and sizes with edges divisible by 16 and at most 1024 pixels. Reference inputs are available through the still-image helper.

## Outputs and delivery

Helpers decode returned media before writing it. Results include paths, dimensions, elapsed time, request identifiers, and usage metadata when supplied by the service. Inspect the visual result for prompt adherence and reference identity before delivery.

Choose artifact paths according to the host workspace policy. Deliver generated media as attachments when supported. For clients that display GIFs as still images, convert the existing animation to H.264/yuv420p MP4 with faststart, composite transparency on a chosen background, and verify playback. Preserve the original GIF.

## Authentication and data flow

Requests use fixed HTTPS image endpoints with redirects rejected. The service receives the prompt and selected reference images. Credentials are placed in the authorization header. See `references/api-security-and-verification.md` for request boundaries and output handling.

API usage is billed separately from ChatGPT subscriptions. Authentication, billing, quota, and network errors stop the invocation. Retrying an ambiguous billed request requires caller direction.

## Implementation

- `scripts/openai_image.py`: still-image generation and edits.
- `scripts/openai_gif.py`: animated GIF generation.
- `scripts/hermes_codex_image.py`: shared validation and atomic file writing, plus an optional legacy CLI requiring the Hermes Codex authentication runtime.

## Maintenance

Keep documentation focused on reusable behavior, configuration, and interfaces. Personal identities, conversation excerpts, task histories, and machine-specific paths belong in deployment-local records. Keep credentials and generated media outside version control. Dry-run output contains request metadata; prompt contents remain in the request construction path.

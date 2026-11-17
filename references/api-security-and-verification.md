# Request boundaries and output handling

## Official API helpers

`openai_image.py` posts to the fixed OpenAI Images generation and edit endpoints. `openai_gif.py` uses the generation endpoint. Both resolve `OPENAI_API_KEY` from the environment, then the active Hermes `.env` file. Redirects are rejected.

The request carries the supplied prompt and generation parameters. Edits include the selected local reference images and mask encoded as data URLs. Input image bytes are sent intact, including any embedded metadata; sanitize reference files before use when metadata is private.

Dry-run output contains operation metadata. Still-image and GIF execution summaries contain output paths and service-provided request/usage metadata. Handled HTTP errors report status codes, and handled network errors report a fixed message. Credentials are placed in the authorization header.

Use `--prompt-file` when command-line arguments may be visible in process listings or shell history. Store prompt files and generated images with access permissions appropriate to their contents.

## Media validation

Still images are checked for PNG, JPEG, or WebP signatures and fully decoded with Pillow. Encoded and decoded sizes are bounded. GIFs are decoded frame by frame and checked for dimensions, changing frames, and positive timing.

Files are written to sibling temporary files and published atomically. Existing outputs require explicit replacement for still images; GIF generation requires a new output path. Output summaries report actual dimensions.

## Request limits

- Prompt: 32000 characters.
- Still-image references: 16, plus an optional mask.
- Each reference: 15 MiB; aggregate references: 45 MiB.
- Still-image serialized request: 64 MiB.
- Response read: 64 MiB.
- Still-image decoded pixels: 40000000.
- Still-image count: 1–10.
- Timeout: 1–600 seconds.

Each invocation makes one request. Inspect errors before deciding whether to retry a billed operation.

## Legacy helper

The optional `hermes_codex_image.py` CLI uses the Hermes Codex authentication runtime and fixed ChatGPT Codex image endpoints. It resolves the access token and account identifier at runtime. Its validation and atomic-writing functions are also imported by the official helpers.

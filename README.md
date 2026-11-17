# GPT Image Skill

A Python CLI and agent skill for still-image generation, reference edits, and animated GIFs.

## Setup

Requires Python 3.10 or newer. Install dependencies in your Python environment:

```bash
python -m pip install -r requirements.txt
```

Set `OPENAI_API_KEY` through your secret manager or environment. The helpers also support the active Hermes `.env` file.

```bash
python scripts/openai_image.py generate --prompt "A whale swimming among clouds" --out image.png
python scripts/openai_gif.py --prompt "A whale waving its tail" --out animation.gif
```

Add `--dry-run` to validate inputs before making a billed request. See [SKILL.md](SKILL.md) for options and [request boundaries](references/api-security-and-verification.md) for data handling.

The official helpers run independently of Hermes. The optional legacy CLI requires its authentication runtime. Model availability depends on the API account.

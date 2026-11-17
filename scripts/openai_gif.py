#!/usr/bin/env python3
"""Native animated GIF generation through the official Images API."""
import argparse
import base64
import binascii
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
from PIL import Image
import openai_image as api

def validate_gif(raw):
    if len(raw) > api.io.MAX_RESPONSE_BYTES or raw[:6] not in (b'GIF87a', b'GIF89a'):
        raise api.io.CliError('Invalid or oversized GIF payload.')
    try:
        with Image.open(BytesIO(raw)) as im:
            width, height = im.size
            frames = im.n_frames
            if not 2 <= frames <= 64 or width * height * frames > 70_000_000:
                raise api.io.CliError('GIF frame count or total pixel budget exceeded.')
            loop = im.info.get('loop')
            durations, hashes = [], set()
            for index in range(frames):
                im.seek(index); im.load()
                durations.append(im.info.get('duration', 0))
                hashes.add(hashlib.sha256(im.convert('RGBA').tobytes()).hexdigest())
            if len(hashes) < 2 or any(d <= 0 for d in durations):
                raise api.io.CliError('GIF has no changing frames or invalid timing.')
    except (OSError, ValueError, EOFError) as exc:
        raise api.io.CliError('GIF decode failed.') from exc
    return {'width': width, 'height': height, 'frames': frames, 'unique_frames': len(hashes),
            'duration_ms': sum(durations), 'frame_durations_ms': durations, 'loop': loop}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    prompt = p.add_mutually_exclusive_group(required=True)
    prompt.add_argument('--prompt'); prompt.add_argument('--prompt-file')
    p.add_argument('--model', choices=api.MODELS, default='gpt-image-2.6-sunburst')
    p.add_argument('--out', required=True)
    p.add_argument('--size', default='512x512')
    p.add_argument('--quality', choices=['low','medium','high','auto'], default='medium')
    p.add_argument('--frame-count', type=int, default=12)
    p.add_argument('--frame-duration-ms', type=int, default=150)
    p.add_argument('--timeout', type=int, default=600)
    p.add_argument('--dry-run', action='store_true')
    a=p.parse_args(argv)
    try:
        out=Path(a.out)
        if out.suffix.lower() != '.gif' or out.exists():
            raise api.io.CliError('Use a new .gif output path.')
        if not 2 <= a.frame_count <= 16 or not 20 <= a.frame_duration_ms <= 2000 or not 1 <= a.timeout <= 600:
            raise api.io.CliError('Use 2-16 frames, 20-2000 ms per frame, timeout 1-600.')
        if a.size != 'auto':
            dims=api.io.parse_size(a.size)
            if not dims or any(x % 16 or x > 1024 for x in dims) or dims[0]*dims[1]*a.frame_count > 16_777_216:
                raise api.io.CliError('GIF size must use multiples of 16, <=1024 edges and <=16M requested pixels.')
        body={'model':a.model,'prompt':api.io.read_prompt(a.prompt,a.prompt_file),'n':1,
              'size':a.size,'quality':a.quality,'output_format':'gif',
              'frame_count':a.frame_count,'frame_duration_ms':a.frame_duration_ms}
        if a.dry_run:
            print(json.dumps({'dry_run':True,'destination':api.GENERATIONS_URL,
                'model':a.model,'size':a.size,'quality':a.quality,
                'frame_count':a.frame_count,'frame_duration_ms':a.frame_duration_ms,
                'network':'not used'},ensure_ascii=False));return 0
        start=time.monotonic()
        data,request_id=api.post(api.GENERATIONS_URL,json.dumps(body,ensure_ascii=False).encode(),api.resolve_key(),a.timeout)
        payload=api.io.extract_payloads(data,1)[0]
        if len(payload)>api.io.MAX_BASE64_CHARS:raise api.io.CliError('Payload exceeds limit.')
        try:raw=base64.b64decode(payload,validate=True)
        except (ValueError,binascii.Error) as exc:raise api.io.CliError('Invalid base64.') from exc
        metadata=validate_gif(raw)
        api.io.atomic_write(out,raw,False)
        result={'ok':True,'model':a.model,'path':str(out),'bytes':len(raw),'request_id':request_id,
                'elapsed_seconds':round(time.monotonic()-start,3),'usage':data.get('usage'),
                'requested_frame_count':a.frame_count,'animation':metadata}
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except api.io.CliError as exc:
        print(json.dumps({'ok':False,'error':str(exc)}),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())

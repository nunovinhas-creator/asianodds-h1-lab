"""Manual-only V6 investigative LLM: dossier, review, or explicitly opt-in HTTPS call."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from h1lab.v6_llm_investigator import build_packet, invoke, strict_json, validate_proposals

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--mode', choices=('dossier', 'review', 'invoke', 'cloudflare'), default='dossier')
    parser.add_argument('--response-file', type=Path)
    parser.add_argument('--allow-network', action='store_true')
    parser.add_argument('--endpoint')
    parser.add_argument('--model')
    args = parser.parse_args(argv)
    packet = build_packet(args.root)
    if args.mode == 'review':
        if not args.response_file:
            parser.error('--response-file is required for review')
        if args.response_file.stat().st_size > 80_000:
            raise ValueError('Response file exceeds limit')
        output = validate_proposals(packet, strict_json(args.response_file.read_text(encoding='utf-8')))
    elif args.mode == 'cloudflare':
        if not args.allow_network:
            parser.error('Cloudflare calls require explicit --allow-network')
        account_id = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
        api_key = os.environ.get('MASTER_BRAIN_LLM_API_KEY', '')
        if not re.fullmatch(r'[0-9a-fA-F]{32}', account_id):
            parser.error('CLOUDFLARE_ACCOUNT_ID must be a 32-character hex account identifier')
        if not api_key:
            parser.error('Cloudflare API token missing from MASTER_BRAIN_LLM_API_KEY')
        endpoint = ('https://api.cloudflare.com/client/v4/accounts/'
                    + account_id + '/ai/v1/chat/completions')
        output = invoke(packet, endpoint=endpoint, model='@cf/meta/llama-3.1-8b-instruct',
                        api_key=api_key)
    elif args.mode == 'invoke':
        if not args.allow_network:
            parser.error('Network is disabled by default; pass --allow-network explicitly')
        if not args.endpoint or not args.model:
            parser.error('--endpoint and --model are required')
        output = invoke(packet, endpoint=args.endpoint, model=args.model,
                        api_key=os.environ.get('MASTER_BRAIN_LLM_API_KEY', ''))
    else:
        output = packet
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return output


if __name__ == '__main__':
    main()

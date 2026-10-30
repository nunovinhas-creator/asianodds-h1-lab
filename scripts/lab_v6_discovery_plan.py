"""Print an offline discovery queue; no external calls or file writes."""
import argparse
import json
from pathlib import Path
from h1lab.v6_discovery_planner import plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(plan(args.root, limit=args.limit), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

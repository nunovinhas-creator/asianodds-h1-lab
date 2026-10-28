"""V6.2 P2#14 archive integrity and SHA replay; no API, no extra schedule."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
from h1lab.lab_archive import build

ROOT = Path(__file__).resolve().parents[1]

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args(argv)
    result = build(args.root, datetime.now(timezone.utc), verify_only=args.verify_only)
    print("V6_ARCHIVE", "REPLAY_OK" if args.verify_only else "INTEGRITY_SHADOW",
          "files", result["lab_files_checked"],
          "sealed", result["sealed_parts"],
          "largest", result["largest_file_bytes"],
          "forecast_rows", result["replay"]["v6_forecasts"])
    return result

if __name__ == "__main__":
    main()

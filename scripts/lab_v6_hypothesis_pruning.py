"""V6.2 P2#13 freeze/replay without API or match outcomes."""
import argparse
from pathlib import Path
from h1lab.v6_hypothesis_pruning import run

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args(argv)
    report = run(args.root, verify_only=args.verify_only)
    s = report["scope"]
    print("V6_P2_13", "VERIFIED" if args.verify_only else "SHADOW",
          s["original_catalog"], "to", s["representatives"],
          "m_eff", report["effective_tests"]["estimate"])
    return report

if __name__ == "__main__":
    main()

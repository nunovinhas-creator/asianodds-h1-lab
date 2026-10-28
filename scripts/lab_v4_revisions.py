"""Rebuild V4 edit/revision evidence from the immutable journal.

A read-only verifier never synthesizes historical messages or edits. The
collector itself bootstraps old source projections as BASELINE_IMPORT using the
real collection clock when this feature is first deployed.
"""
import argparse
import json
from pathlib import Path

from h1lab.v4_revisions import report, verify_projection

ROOT=Path(__file__).resolve().parents[1]


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--verify-only", action="store_true")
    args=p.parse_args(argv)
    verify_projection(args.root)
    result=report(args.root)
    out=args.root/"docs/lab/v4-revisions.json"
    if args.verify_only:
        if not out.exists() or json.loads(out.read_text(encoding="utf-8")) != result:
            raise SystemExit("V4_REVISION_REPORT_NOT_REPRODUCIBLE")
        print("V4_REVISION_REPLAY_OK",result["messages"],result["revision_events"])
        return result
    out.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    if not out.exists() or out.read_text(encoding="utf-8")!=payload:
        out.write_text(payload,encoding="utf-8")
    print("V4_REVISIONS",result["messages"],"events",result["revision_events"],
          "edited",result["telegram_edited_messages"],
          "unproven",result["changed_without_edit_proof"])
    return result


if __name__=="__main__":
    main()

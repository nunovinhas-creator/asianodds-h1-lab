"""Verifiable permanent archive of the MASTER BRAIN P0 stability audits (issue #107).

The 24h and 48h audits exist only as issue comments. This tool copies a comment VERBATIM
(``comment.md``, the exact UTF-8 body returned by the GitHub REST API) and writes a manifest with
its provenance and checksums. It never rewrites, summarises or re-runs an audit: every derived
field is parsed from the archived text and is null when the text does not state it.

    python -m tools.archive_p0_audit archive --comment-id 6628273701   # needs `gh` (read only)
    python -m tools.archive_p0_audit verify                             # offline checksums
    python -m tools.archive_p0_audit verify --online                    # + body still identical

Layout: ``reports/p0-audits/<label>/comment.md`` + ``manifest.json``, and
``reports/p0-audits/INDEX.json`` (sha256 of every manifest). ``reports/**`` is the human-reviewed
area of the ownership matrix: no automatic publisher writes it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path("reports/p0-audits")
REPO = "nunovinhas-creator/asianodds-h1-lab"
ISSUE = 107
ARCHIVER_VERSION = 1
MARKER = re.compile(r"<!-- MASTER_BRAIN_P0_AUDIT:([0-9]+[hd]) -->")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _first(pattern, text, group=1, flags=0):
    match = re.search(pattern, text, flags)
    return match.group(group).strip() if match else None


def parse(body: str) -> dict:
    """Facts stated by the audit text itself (None when absent). Pure, offline."""
    label = _first(MARKER.pattern, body)
    window = re.search(r"\[(\d{4}-\d{2}-\d{2}T[\d:]+Z),\s*(\d{4}-\d{2}-\d{2}T[\d:]+Z)\)", body)
    manual_at = body.find("Revisão manual")
    automatic_part = body if manual_at < 0 else body[:manual_at]
    manual_part = None if manual_at < 0 else body[manual_at:]
    return {
        "label": label,
        "window_utc": ({"start": window.group(1), "end_exclusive": window.group(2)}
                       if window else None),
        "closing_sha_prefix": _first(r"fecho `([0-9a-f]{7,40})`", body),
        "audited_head_prefix": _first(r"Head auditada `([0-9a-f]{7,40})`", body),
        # Both phrasings used so far: "`tools/x.py` @ `<commit>`, sha256 `<h>`" (48h) and
        # "Ferramenta: `<commit>` · `tools/x.py` sha256 `<h>`" (24h).
        "auditor": {
            "path": _first(r"`(tools/p0_stability_audit(?:_v\d+)?\.py)`", body),
            "commit": (_first(r"p0_stability_audit(?:_v\d+)?\.py` @ `([0-9a-f]{40})`", body)
                       or _first(r"Ferramenta: `([0-9a-f]{40})`", body)),
            "sha256": _first(r"sha256 `([0-9a-f]{64})`", body),
        },
        # The automatic verdict and the manual review are kept in SEPARATE fields.
        "automatic_verdict": _first(r"Classificação operacional: \*\*([^*]+)\*\*", automatic_part),
        "manual_review_verdict": (_first(r"veredito revisto: \*\*([^*]+)\*\*", manual_part)
                                  if manual_part else None),
        "scientific_state_63": _first(r"Estado científico #63: ([A-ZÇÃÕÉ_]+)", body),
        "has_post_cutoff_snapshot": "Fotografia B" in body,
    }


def manifest_for(comment: dict, body_bytes: bytes, archived_at: str) -> dict:
    body = body_bytes.decode("utf-8")
    facts = parse(body)
    return {
        "schema_version": 1, "archiver_version": ARCHIVER_VERSION, "archived_at": archived_at,
        "source": {"repository": REPO, "issue": ISSUE, "comment_id": comment["id"],
                   "comment_url": comment["html_url"], "author": comment["user"]["login"],
                   "created_at": comment["created_at"], "updated_at": comment["updated_at"],
                   "edited_after_creation": comment["created_at"] != comment["updated_at"]},
        "comment_md": {"path": "comment.md", "bytes": len(body_bytes),
                       "sha256": sha256(body_bytes)},
        **facts,
        "data_boundary": ("Indicators and verdict cover the half-open window only (photograph A at "
                          "the closing SHA). 'Fotografia B' figures are state at audit time, "
                          "outside the verdict." if facts["has_post_cutoff_snapshot"] else None),
        "machine_report": {"json": None, "reason": "The auditor's JSON output was not retained "
                           "as a run artifact; only the issue comment exists. Not reconstructed."},
    }


def _gh_comment(comment_id: int) -> dict:
    out = subprocess.run(["gh", "api", "repos/%s/issues/comments/%d" % (REPO, comment_id)],
                         check=True, stdout=subprocess.PIPE).stdout
    return json.loads(out)


def write_index(root: Path) -> dict:
    base = root / ARCHIVE
    entries = []
    for manifest in sorted(base.glob("*/manifest.json")):
        raw = manifest.read_bytes()
        doc = json.loads(raw)
        entries.append({"label": doc["label"], "manifest": manifest.relative_to(base).as_posix(),
                        "manifest_sha256": sha256(raw), "comment_id": doc["source"]["comment_id"],
                        "window_utc": doc["window_utc"]})
    index = {"schema_version": 1, "issue": ISSUE, "audits": entries}
    (base / "INDEX.json").write_text(json.dumps(index, indent=1, sort_keys=True) + "\n",
                                     encoding="utf-8")
    return index


def archive(root: Path, comment: dict, *, archived_at=None) -> Path:
    body_bytes = comment["body"].encode("utf-8")
    label = parse(comment["body"])["label"]
    if not label:
        raise ValueError("Comment %s is not a MASTER_BRAIN_P0_AUDIT comment" % comment["id"])
    target = root / ARCHIVE / label
    if (target / "manifest.json").exists():
        old = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        if old["comment_md"]["sha256"] != sha256(body_bytes):
            raise ValueError("Archive for %s exists with different content: never overwritten"
                             % label)
        return target
    target.mkdir(parents=True, exist_ok=True)
    (target / "comment.md").write_bytes(body_bytes)
    stamp = archived_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    (target / "manifest.json").write_text(
        json.dumps(manifest_for(comment, body_bytes, stamp), indent=1, sort_keys=True,
                   ensure_ascii=False) + "\n", encoding="utf-8")
    write_index(root)
    return target


def verify(root: Path, *, fetch=None) -> list:
    """Return a list of problems (empty = archive intact)."""
    base = root / ARCHIVE
    problems = []
    index = json.loads((base / "INDEX.json").read_text(encoding="utf-8"))
    listed = {e["manifest"]: e for e in index["audits"]}
    found = {m.relative_to(base).as_posix() for m in base.glob("*/manifest.json")}
    if set(listed) != found:
        problems.append("INDEX does not list exactly the archived manifests")
    for rel in sorted(found):
        raw = (base / rel).read_bytes()
        doc = json.loads(raw)
        if rel in listed and listed[rel]["manifest_sha256"] != sha256(raw):
            problems.append("manifest checksum mismatch: " + rel)
        body = (base / rel).parent.joinpath(doc["comment_md"]["path"]).read_bytes()
        if sha256(body) != doc["comment_md"]["sha256"] or len(body) != doc["comment_md"]["bytes"]:
            problems.append("comment.md checksum mismatch: " + rel)
        derived = parse(body.decode("utf-8"))
        for key, value in derived.items():
            if doc.get(key) != value:
                problems.append("derived field %s differs from the archived text: %s" % (key, rel))
        if fetch is not None:
            live = fetch(doc["source"]["comment_id"])
            if sha256(live["body"].encode("utf-8")) != doc["comment_md"]["sha256"]:
                problems.append("issue comment changed since archiving: " + rel)
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("archive")
    a.add_argument("--comment-id", type=int, required=True, action="append")
    v = sub.add_parser("verify")
    v.add_argument("--online", action="store_true")
    for p in (a, v):
        p.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.mode == "archive":
        for cid in args.comment_id:
            print("P0_AUDIT_ARCHIVED", archive(args.root, _gh_comment(cid)))
        return 0
    problems = verify(args.root, fetch=_gh_comment if args.online else None)
    for problem in problems:
        print("P0_AUDIT_ARCHIVE_PROBLEM", problem)
    print("P0_AUDIT_ARCHIVE", "OK" if not problems else "FAILED")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

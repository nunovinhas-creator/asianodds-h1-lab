"""Concurrency-safe publication of an H1 results commit (no force push, no provider calls).

Replaces ``git pull --rebase && git push`` in ``results.yml`` after the
2026-11-02 06:57 UTC rejection (run 41403070558): ``cannot lock ref
'refs/heads/main': is at 1612e8e… but expected fd38613…`` — a LAB V4 commit
landed between the final rebase and the push.

The H1 job already did its provider work and committed its outputs on top of
``--base``. This tool transports exactly those outputs over the *current*
remote ``main`` with an isolated Git index (shared machinery with the FT
publisher), after proving that every concurrent remote change is independent
data. It never re-queries providers; a Git conflict is only a Git problem.

Refusals (no publication, remote untouched):
* another writer changed an H1-owned output (``results.csv``,
  ``result_audit.json``, the H1 receipt) with different bytes — two writers
  could otherwise publish contradictory results for the same key;
* program/configuration changes (``h1lab/``, ``scripts/``, ``.github/``,
  ``tests/``, ``config/``, requirements);
* a fixture identity rewrite in ``data/state.json``;
* unknown paths.

Own-change guards (base → candidate): certified rows of ``results.csv`` are
immutable and unique per key, ``expired_unverified`` and ``settled`` audit
entries are never reopened, audit timestamps and counters never go back.

``docs/data.json`` is a rendered view of ``data/state.json`` + ``results.csv``.
When the remote changed either input concurrently, it is re-rendered offline
on the merged tree (``python -m h1lab.cli render``) instead of overwriting
the newer collector view.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from scripts import git_publish_outcome as outcome
from datetime import datetime, timezone

from scripts import lab_ft_publish_safe as ft_publisher
from scripts.lab_ft_publish_safe import (
    H1_NOTIFICATION_RECEIPTS, JOURNAL, SHA, TELEGRAM_BLOCK, TELEGRAM_ELIGIBILITY_REPORT,
    V4_ARCHIVE, UnsafeFTPublication, append_only_jsonl, blob_or_none, changed_paths, git,
    run, sha, stable_fixtures, tree_entry)

RESULTS = "data/results.csv"
AUDIT = "data/result_audit.json"
RECEIPT = "data/health/h1-results.json"
RENDERED = "docs/data.json"
STATE = "data/state.json"
OWNED = frozenset({RESULTS, AUDIT, RECEIPT})
OUTPUTS = OWNED | {RENDERED}
CODE_PREFIXES = ("h1lab/", "scripts/", ".github/", "tests/", "config/", "scheduler/", "tools/")
CODE_FILES = ("requirements.txt", "requirements-test.txt")
INDEPENDENT_PREFIXES = ("data/lab/", "docs/lab/")
MESSAGE = "data: reconcile verified H1 finals [skip ci]"
FT_LEDGER = "data/lab/ft-ledger.json"  # the only LAB input of the H1 job (h1lab.lab_promotion)


class UnsafeH1Publication(UnsafeFTPublication):
    pass


# ---------------------------------------------------------------- own-change guards
def _rows(raw):
    if raw is None:
        return {}
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    if reader.fieldnames != ["match_key", "status", "home_goals", "away_goals", "source"]:
        raise UnsafeH1Publication("Invalid results.csv header")
    rows = {}
    for row in reader:
        key = row["match_key"]
        if None in row or any(v is None for v in row.values()) or not key:
            raise UnsafeH1Publication("Incomplete results.csv row")
        if key in rows:
            if rows[key] != row:
                raise UnsafeH1Publication("Contradictory results for one key: " + key)
            raise UnsafeH1Publication("Duplicate result key: " + key)
        rows[key] = row
    return rows


def verify_results(before, after):
    old, new = _rows(before), _rows(after)
    for key, row in old.items():
        if new.get(key) != row:
            raise UnsafeH1Publication("Certified H1 result changed or removed: " + key)
    return len(new) - len(old)


def _numbers(entry, prefix=""):
    for name, value in entry.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            yield prefix + name, value
        elif isinstance(value, dict):
            yield from _numbers(value, prefix + name + ".")


def _instant(value):
    """Audit timestamps are compared as UTC instants, never as strings."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise UnsafeH1Publication("Unparseable audit timestamp: %r" % (value,))
    if parsed.tzinfo is None:
        raise UnsafeH1Publication("Naive audit timestamp: %r" % (value,))
    return parsed.astimezone(timezone.utc)


def verify_ft_inputs(before, after):
    """A concurrent FT publication is independent only if every FINAL the H1 job could have
    imported at its base is still FINAL with the identical result (no invalidated proof)."""
    try:
        old = json.loads(before)["matches"] if before else {}
        new = json.loads(after)["matches"] if after else None
    except (ValueError, KeyError, TypeError):
        raise UnsafeH1Publication("Unreadable FT ledger in concurrent change")
    if new is None:
        raise UnsafeH1Publication("FT ledger deleted concurrently")
    for key, row in old.items():
        if isinstance(row, dict) and row.get("status") == "FINAL":
            cur = new.get(key)
            if not isinstance(cur, dict) or cur.get("status") != "FINAL" \
                    or cur.get("result") != row.get("result"):
                raise UnsafeH1Publication("FT FINAL used by H1 changed concurrently: " + key)


def verify_audit(before, after):
    old = json.loads(before) if before else {}
    new = json.loads(after) if after else {}
    if not isinstance(old, dict) or not isinstance(new, dict):
        raise UnsafeH1Publication("Invalid result_audit.json")
    for key, entry in old.items():
        if not isinstance(entry, dict):
            continue
        current = new.get(key)
        if not isinstance(current, dict):
            raise UnsafeH1Publication("Audit entry removed: " + key)
        if entry.get("status") in ("expired_unverified", "settled") and \
                current.get("status") != entry.get("status"):
            raise UnsafeH1Publication("Terminal audit entry reopened: " + key)
        for stamp in ("checked_at", "expired_at"):
            if entry.get(stamp) and (not current.get(stamp)
                                      or _instant(current[stamp]) < _instant(entry[stamp])):
                raise UnsafeH1Publication("Audit timestamp went back: %s %s" % (key, stamp))
        now = dict(_numbers(current))
        for name, value in _numbers(entry):
            if name in now and now[name] < value:
                raise UnsafeH1Publication("Audit counter decreased: %s %s" % (key, name))


# ---------------------------------------------------------------- remote change policy
def check_remote_path(root, base, remote, path):
    if path in OWNED:
        raise UnsafeH1Publication("Concurrent H1 result writer changed " + path)
    if path.startswith(CODE_PREFIXES) or path in CODE_FILES:
        raise UnsafeH1Publication("Incompatible program change: " + path)
    if path == STATE:
        previous, current = blob_or_none(root, base, path), blob_or_none(root, remote, path)
        if previous is None or current is None or not stable_fixtures(previous, current):
            raise UnsafeH1Publication("H1 fixture identity changed: " + path)
        return "rerender"
    if path == RENDERED:
        if blob_or_none(root, remote, path) is None:
            raise UnsafeH1Publication("Dashboard data deleted: " + path)
        return "rerender"
    if path in H1_NOTIFICATION_RECEIPTS or path in (TELEGRAM_BLOCK, TELEGRAM_ELIGIBILITY_REPORT):
        # Exactly the strict validators of the FT publisher (modes, symlinks, rollback, secrets).
        try:
            ft_publisher._check_remote_path(root, base, remote, path)
        except UnsafeFTPublication as exc:
            raise UnsafeH1Publication(str(exc))
        return "keep"
    if path == FT_LEDGER:
        verify_ft_inputs(blob_or_none(root, base, path), blob_or_none(root, remote, path))
        return "keep"
    if JOURNAL.fullmatch(path) or V4_ARCHIVE.fullmatch(path):
        if not append_only_jsonl(blob_or_none(root, base, path),
                                 blob_or_none(root, remote, path) or b""):
            raise UnsafeH1Publication("LAB journal rewritten: " + path)
        return "keep"
    if path.startswith(INDEPENDENT_PREFIXES) or path == "data/results.json":
        return "keep"
    raise UnsafeH1Publication("Unknown concurrent path: " + path)


def remote_policy(root, base, remote):
    changes = changed_paths(root, base, remote)
    rerender = False
    for path in sorted(changes):
        rerender |= check_remote_path(root, base, remote, path) == "rerender"
    return changes, rerender


# ---------------------------------------------------------------- transport
def transport(root, remote, source, paths):
    with tempfile.TemporaryDirectory(prefix="h1-git-index-") as d:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(d) / "index")}
        git(root, "read-tree", remote, env=env)
        for path in sorted(paths):
            row = tree_entry(root, source, path)
            if row is None:
                git(root, "update-index", "--force-remove", "--", path, env=env)
            else:
                git(root, "update-index", "--add", "--cacheinfo",
                    "%s,%s,%s" % (row[0], row[1], path), env=env)
        tree = git(root, "write-tree", env=env).decode().strip()
        return git(root, "commit-tree", tree, "-p", remote, "-m", MESSAGE, env=env).decode().strip()


def default_render(root):
    proc = subprocess.run([sys.executable, "-m", "h1lab.cli", "render"], cwd=str(root),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise UnsafeH1Publication("Offline dashboard re-render failed: "
                                  + proc.stderr.decode("utf-8", "replace")[-300:])


def write_receipt(path, document):
    print("H1_PUBLISH_RECEIPT", json.dumps(document, sort_keys=True))
    if path:
        Path(path).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def publish(root, *, base, receipt=None, bundle=None, **kwargs):
    """Publish, or fail with a complete receipt and the unpublished commit kept for diagnosis.

    Failure statuses: RETRY_EXHAUSTED (persistent contention), OUTCOME_UNRESOLVED (transport,
    remote unreadable), REFUSED (integrity/compatibility). The local branch is put back on the
    unpublished H1 commit and, when ``bundle`` is given, that commit is exported as a Git bundle
    (uploaded by the workflow as an artifact) so its outputs are never silently lost.
    """
    root = Path(root)
    trace = {"attempts": 0, "remote_heads": [], "kinds": []}
    try:
        return _publish(root, base=base, receipt=receipt, trace=trace, **kwargs)
    except UnsafeFTPublication as exc:
        message = str(exc)
        status = ("RETRY_EXHAUSTED" if message.startswith("Remote advanced during all bounded")
                  else "OUTCOME_UNRESOLVED" if "outcome unresolved" in message else "REFUSED")
        source = trace.get("source")
        if source:
            run(root, "reset", "--hard", source, check=False)
            if bundle:
                made = run(root, "bundle", "create", str(bundle), "HEAD", "^" + base, check=False)
                if made.returncode:
                    print("H1_BUNDLE_FAILED", made.stderr.decode("utf-8", "replace")[-200:])
        write_receipt(receipt, {"status": status, "reason": message[:500], "base": base,
                                "source_commit": source, "published_commit": None,
                                "attempts": trace["attempts"], "remote_heads": trace["remote_heads"],
                                "push_failures": trace["kinds"], "provider_requeries": 0,
                                "bundle": str(bundle) if bundle and source else None,
                                "run_id": os.environ.get("GITHUB_RUN_ID")})
        raise


def _publish(root, *, base, receipt, trace, max_attempts=6, max_transport_failures=3,
             render=default_render, sleep=time.sleep):
    if not SHA.fullmatch(base) or not 1 <= max_attempts <= 10:
        raise UnsafeH1Publication("Invalid H1 base or retry bound")
    source = sha(root, "HEAD")
    if sha(root, "HEAD^") != base:
        raise UnsafeH1Publication("H1 commit is not based on the pinned checkout")
    trace["source"] = source
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise UnsafeH1Publication("H1 checkout is not clean")
    produced = changed_paths(root, base, source)
    if not produced or not produced <= OUTPUTS:
        raise UnsafeH1Publication("Unexpected H1 commit paths: %r" % sorted(produced - OUTPUTS)[:8])
    added = verify_results(blob_or_none(root, base, RESULTS), blob_or_none(root, source, RESULTS))
    verify_audit(blob_or_none(root, base, AUDIT), blob_or_none(root, source, AUDIT))
    owned = produced & OWNED
    doc = {"source_commit": source, "base": base, "new_certified_rows": added,
           "provider_requeries": 0, "run_id": os.environ.get("GITHUB_RUN_ID")}
    transport_failures = 0
    for attempt in range(1, max_attempts + 1):
        trace["attempts"] = attempt
        git(root, "fetch", "--no-tags", "origin", "main")
        remote = sha(root, "FETCH_HEAD")
        trace["remote_heads"].append(remote)
        if run(root, "merge-base", "--is-ancestor", base, remote, check=False).returncode:
            raise UnsafeH1Publication("Remote main no longer descends from the H1 base")
        if remote != base and owned and outcome.same_paths(root, source, remote, owned):
            git(root, "reset", "--hard", remote)
            write_receipt(receipt, {**doc, "status": "ALREADY_PUBLISHED_EQUIVALENT",
                                    "attempt": attempt, "published_commit": remote})
            return remote
        changes, rerender = remote_policy(root, base, remote)
        if remote == base:
            candidate = source
        else:
            moved = produced - ({RENDERED} if rerender else set())
            candidate = transport(root, remote, source, moved)
            git(root, "reset", "--hard", candidate)
            if rerender and RENDERED in produced:
                render(root)
                if git(root, "status", "--porcelain", "--", RENDERED).strip():
                    git(root, "add", RENDERED)
                    git(root, "commit", "-q", "--amend", "--no-edit")
                candidate = sha(root, "HEAD")
        git(root, "reset", "--hard", candidate)
        # Re-verify the exact candidate against the remote it will extend.
        extra = changed_paths(root, remote, candidate) - OUTPUTS
        if extra:
            raise UnsafeH1Publication("Candidate touches non-H1 paths: %r" % sorted(extra)[:8])
        verify_results(blob_or_none(root, remote, RESULTS), blob_or_none(root, candidate, RESULTS))
        verify_audit(blob_or_none(root, remote, AUDIT), blob_or_none(root, candidate, AUDIT))
        result = run(root, "push", "origin", "HEAD:refs/heads/main", check=False)
        if result.returncode == 0:
            write_receipt(receipt, {**doc, "status": "PUBLISHED", "attempt": attempt,
                                    "published_commit": candidate, "remote_base": remote,
                                    "concurrent_paths": len(changes), "rerendered": rerender})
            return candidate
        err = result.stderr.decode("utf-8", "replace")
        kind = outcome.classify_push_failure(err, "main")
        trace["kinds"].append(kind)
        print("H1_PUSH_FAILURE", json.dumps({"attempt": attempt, "kind": kind,
                                             "candidate": candidate, "remote_before_push": remote}))
        if kind == outcome.CAS_REJECTED:
            continue
        if kind in (outcome.UNCERTAIN, outcome.TRANSIENT):
            transport_failures += 1
            state, now = outcome.probe_remote(root, candidate, "main", sleep=sleep)
            if state == outcome.PUBLISHED:
                write_receipt(receipt, {**doc, "status": "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR",
                                        "attempt": attempt, "published_commit": candidate,
                                        "remote_after": now})
                return candidate
            if state == outcome.UNRESOLVED or transport_failures > max_transport_failures:
                raise UnsafeH1Publication("H1 push outcome unresolved: " + err[-200:])
            sleep(2 ** transport_failures)
            continue
        raise UnsafeH1Publication("H1 push refused (%s): %s" % (kind, err[-300:]))
    raise UnsafeH1Publication("Remote advanced during all bounded H1 publication attempts")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--bundle", type=Path, help="export the unpublished commit here on failure")
    parser.add_argument("--max-attempts", type=int, default=6)
    args = parser.parse_args(argv)
    publish(args.root, base=args.base, receipt=args.receipt, bundle=args.bundle,
            max_attempts=args.max_attempts)


if __name__ == "__main__":
    main()

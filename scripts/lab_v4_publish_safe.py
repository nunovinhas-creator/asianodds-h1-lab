"""Concurrency-safe publication of the sealed LAB V4 audit bundle (no rebase, no force push).

Replaces the five-attempt ``git fetch && git rebase origin/main && publication_guard
verify && git push`` loop of ``lab-v4-audit.yml``. ``publication_guard`` (producer
outcomes + seal of the staged bytes) is kept unchanged and still runs before the
commit; this publisher then moves the sealed commit over the current ``main`` with
the shared selective engine (``scripts.git_selective_publish``).

Why not rebase: a rebase 3-way merges text. The seal protects the bytes of the
sealed LAB files, but NOT the inputs the reports were computed from. Reproduced
(``tests/test_lab_v4_publish_safe.py``): an FT append to a closed month that the
new ``v6-archive-index.json`` already sealed rebases cleanly, passes the seal and
is published — the index then contradicts ``main`` and every later archive build
fails with SEALED_MONTH_MUTATED. Likewise an ``ft-ledger.json`` FINAL rewritten
concurrently, or a Telegram receipt rolled back, is not seen by the old loop.

Dependency policy of every concurrent remote path (``scripts.publication_ownership``):

* integrity violations refuse (REFUSED, failure): another LAB V4 writer of the same
  artifacts/journals/archive generation; program/config; frozen legacy ledger; unknown
  path; Golden labels changed; fixture identity rewritten; Telegram receipts rolled back;
  Telegram block shortened; V4 revision or FT event journal rewritten; certified
  ``results.csv`` row changed; FT FINAL changed;
* a VALID change of a material report input (collector state, V4 views/journal, receipt
  ledgers; H1 results; any FT output) -> ``SUPERSEDED_BY_NEWER_INPUTS``: the sealed
  reports were computed on the input commit, so they are NOT published over newer inputs
  (no stale report presented as current). The job exits 0 with a notice; the next LAB run,
  triggered by the next collector completion, recomputes on the new main;
* non-material: ``docs/data.json`` (derived H1 view) and the Telegram pause (read only by
  the notifiers); LLM, statistics, quality, site and documentation commits are kept.

Provenance: every LAB commit carries ``LAB-Input-Commit: <sha>``; the publisher proves that
no material path differs between that commit and the parent of the published commit.

The exact candidate tree is then re-verified: the publication seal (bytes and
journal inventory), every sealed entry of the produced archive index against the
candidate's blobs, every terminal Telegram receipt in the produced eligibility
report against the candidate's ledgers, and append-only growth of the LAB journals.
An incompatible change is an explicit refusal; nothing partial is ever pushed.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
from pathlib import Path

from scripts import git_selective_publish as sel
from scripts import publication_guard
from scripts import publication_ownership as own
from scripts.h1_publish_safe import UnsafeH1Publication, verify_ft_inputs, verify_results
from scripts.lab_ft_publish_safe import (append_only_jsonl, stable_fixtures,
                                         valid_notification_update, valid_telegram_block_update)

MESSAGE = "data(lab): refresh V4 comparison and log checks [skip ci]"
ELIGIBILITY = "docs/lab/telegram-eligibility.json"
TERMINAL = ("sent", "delivery_uncertain_manual_review", "delivery_rejected_final",
            "expired_not_sent")
KEEP_OWNERS = frozenset({own.LLM, own.OFFLINE_STATS, own.LAB_QUALITY, own.SITE, own.DOCUMENTATION})
# Written by others, never read by any LAB V4 producer (derived H1 dashboard; Telegram pause).
NON_MATERIAL = frozenset({own.COLLECT_RENDERED, own.TELEGRAM_BLOCK, own.E5_LEDGER})
TRAILER = "LAB-Input-Commit: "


def _refuse(message, kind="DEPENDENCY_CHANGED"):
    raise sel.PublicationRefused(message, kind)


@contextlib.contextmanager
def inside(root):
    """publication_guard runs plain ``git`` in the current directory."""
    previous = os.getcwd()
    os.chdir(str(root))
    try:
        yield
    finally:
        os.chdir(previous)


def verify_archive_index(root, ref):
    """Every sealed closed-month entry of the index must describe the blob in ``ref`` exactly."""
    raw = sel.blob(root, ref, own.LAB_V4_ARCHIVE_INDEX)
    if raw is None:
        return 0
    try:
        sealed = json.loads(raw)["sealed"]
    except (ValueError, KeyError, TypeError):
        _refuse("Unreadable archive index", "INTEGRITY")
    for entry in sealed:
        content = sel.blob(root, ref, entry.get("path", ""))
        if content is None or hashlib.sha256(content).hexdigest() != entry.get("sha256_bytes") \
                or len(content) != entry.get("bytes") or len(content.splitlines()) != entry.get("rows"):
            _refuse("Archive index contradicts the tree it would be published on: %s"
                    % entry.get("path"))
    return len(sealed)


def verify_eligibility_receipts(root, ref):
    """Terminal receipts quoted by the report must exist, identical, in the ledgers of ``ref``."""
    raw = sel.blob(root, ref, ELIGIBILITY)
    if raw is None:
        return 0
    try:
        games = json.loads(raw)["games"]
        ledgers = {"three": json.loads(sel.blob(root, ref, own.THREE_LEDGER) or b'{"entries":{}}'),
                   "two": json.loads(sel.blob(root, ref, own.TWO_LEDGER) or b'{"entries":{}}')}
    except (ValueError, KeyError, TypeError):
        _refuse("Unreadable Telegram eligibility report or ledgers", "INTEGRITY")
    checked = 0
    for key, game in games.items():
        for rule, receipt in (game.get("receipts") or {}).items():
            if receipt.get("status") not in TERMINAL:
                continue
            entry = (ledgers.get(rule) or {}).get("entries", {}).get(key)
            if not isinstance(entry, dict) or entry.get("status") != receipt["status"] or \
                    entry.get("telegram_message_id") != receipt.get("telegram_message_id"):
                _refuse("Eligibility report contradicts Telegram receipts on main: %s %s" % (rule, key))
            checked += 1
    return checked


class LabV4Policy(sel.Policy):
    name = "LAB_V4"
    message = MESSAGE

    def __init__(self, manifest, guard_verify=None):
        self.manifest = Path(manifest)
        self._guard = guard_verify or publication_guard.verify
        self.input_commit = None

    def owns(self, path):
        return own.is_lab_v4_owned(path)

    def _seal(self, root):
        with inside(root):
            try:
                self._guard(self.manifest)
            except (ValueError, OSError) as exc:
                _refuse("Publication seal rejected: %s" % exc, "INTEGRITY")

    def verify_own(self, root, base, source, produced):
        # Provenance: every LAB commit names the exact input commit its reports were computed on.
        self.input_commit = base
        self.message = MESSAGE + "\n\n" + TRAILER + base
        body = sel.git(root, "log", "-1", "--format=%B", source).decode()
        if TRAILER in body and (TRAILER + base) not in body:
            _refuse("LAB commit names a different input commit", "INVALID_INPUT")
        proof = json.loads(self.manifest.read_text(encoding="utf-8"))
        if proof.get("pipeline") != "audit":
            _refuse("Not an audit publication seal", "INVALID_INPUT")
        unsealed = sorted(p for p in produced if p not in proof.get("sha256", {})
                          and sel.blob(root, source, p) is not None)
        if unsealed:
            _refuse("Unsealed LAB V4 outputs: %r" % unsealed[:8], "INTEGRITY")
        for path in sorted(produced):
            if own.LAB_V4_JOURNALS.fullmatch(path):
                after = sel.blob(root, source, path)
                if after is None or not append_only_jsonl(sel.blob(root, base, path), after):
                    _refuse("LAB journal rewritten by its own producer: " + path, "INTEGRITY")
        self._seal(root)
        return {"input_commit": base, "sealed_files": len(proof.get("sha256", {})),
                "archive_entries_checked": verify_archive_index(root, source),
                "eligibility_receipts_checked": verify_eligibility_receipts(root, source)}

    def check_remote(self, root, base, remote, path, produced, source):
        owner = own.owner_of(path)
        before, after = sel.blob(root, base, path), sel.blob(root, remote, path)
        if path in self._sealed_paths(root, base, source):
            _refuse("Closed month sealed by the archive index changed concurrently: " + path)
        if owner == own.LAB_V4:
            _refuse("Concurrent LAB V4 writer changed " + path, "CONCURRENT_OWNER_WRITE")
        if owner == own.PROGRAM:
            _refuse("Incompatible program change: " + path, "INCOMPATIBLE_PROGRAM")
        if owner == own.LEGACY:
            _refuse("Frozen legacy Telegram ledger changed: " + path, "INTEGRITY")
        if owner == own.MANUAL_REVIEW:
            if path.startswith("data/lab/golden/"):
                _refuse("Golden review labels changed while the LAB report was built: " + path)
            return "keep"
        if owner == own.COLLECTOR:
            if path == own.COLLECT_STATE:
                if before is None or after is None or not stable_fixtures(before, after):
                    _refuse("Fixture identity changed under the LAB report: " + path)
            elif path in own.TELEGRAM_LEDGERS:
                if not valid_notification_update(before, after):
                    _refuse("Telegram receipts rolled back or invalid: " + path)
            elif path == own.TELEGRAM_BLOCK:
                if not valid_telegram_block_update(before, after):
                    _refuse("Telegram delivery block shortened or invalid: " + path)
            elif own.V4_REVISIONS.fullmatch(path):
                if after is None or not append_only_jsonl(before, after):
                    _refuse("V4 revision journal rewritten: " + path)
            elif after is None:
                _refuse("Collector output deleted: " + path)
            return self._material(path)
        if owner == own.H1_RESULTS:
            if after is None:
                _refuse("H1 result output deleted: " + path)
            if path == "data/results.csv":
                try:
                    verify_results(before, after)
                except UnsafeH1Publication as exc:
                    _refuse(str(exc))
            return self._material(path)
        if owner == own.FT:
            if path == own.FT_LEDGER:
                try:
                    verify_ft_inputs(before, after)
                except UnsafeH1Publication as exc:
                    _refuse(str(exc))
            elif own.FT_EVENTS.fullmatch(path):
                if after is None or not append_only_jsonl(before, after):
                    _refuse("FT event journal rewritten: " + path)
            return self._material(path)
        if owner in KEEP_OWNERS:
            return "keep"
        _refuse("Unknown concurrent path: " + path, "UNKNOWN_PATH")

    def _sealed_paths(self, root, base, source):
        """Closed monthly files sealed by the base index or by the index this run produced."""
        key = (base, source)
        if getattr(self, "_sealed_key", None) != key:
            paths = set()
            for ref in (base, source):
                raw = sel.blob(root, ref, own.LAB_V4_ARCHIVE_INDEX)
                try:
                    paths |= {e["path"] for e in json.loads(raw)["sealed"]} if raw else set()
                except (ValueError, KeyError, TypeError):
                    _refuse("Unreadable archive index", "INTEGRITY")
            self._sealed_key, self._sealed = key, paths
        return self._sealed

    def _material(self, path):
        """A valid concurrent change of a report INPUT: the sealed reports were computed on the
        input commit, so publishing them over newer inputs would present stale results as current.
        Not published; the next LAB run (triggered by the next collector completion) recomputes."""
        if path in NON_MATERIAL:
            return "keep"
        raise sel.Superseded("LAB inputs advanced on main since %s: %s"
                             % ((self.input_commit or "?")[:12], path))

    def verify_candidate(self, root, remote, candidate, produced):
        # Every path that differs between the input commit and the candidate's parent must be
        # non-material: the published reports describe exactly the inputs they sit on.
        moved = sel.changed_paths(root, self.input_commit, remote)
        material = sorted(p for p in moved if p not in NON_MATERIAL
                          and own.owner_of(p) not in KEEP_OWNERS)
        if material:
            raise sel.Superseded("Material LAB inputs differ from the input commit: %r" % material[:8])
        self._seal(root)
        verify_archive_index(root, candidate)
        verify_eligibility_receipts(root, candidate)
        for path in sorted(produced):
            if own.LAB_V4_JOURNALS.fullmatch(path):
                if not append_only_jsonl(sel.blob(root, remote, path),
                                         sel.blob(root, candidate, path) or b""):
                    _refuse("LAB journal would be rewritten on main: " + path, "INTEGRITY")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--max-attempts", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        sel.publish(args.root, base=args.base, policy=LabV4Policy(args.manifest),
                    receipt=args.receipt, bundle=args.bundle, max_attempts=args.max_attempts)
    except sel.Superseded as exc:
        # Deliberate safe skip: nothing stale is published; the next run recomputes.
        print("::notice title=LAB_AUDIT_SUPERSEDED::%s" % str(exc)[:300])
        print("LAB_AUDIT_SUPERSEDED")
        return 0
    except sel.PublicationRefused as exc:
        print("::error title=LAB_AUDIT_PUBLISH_FAILED::%s %s" % (exc.kind, str(exc)[:300]))
        print("LAB_AUDIT_PUBLISH_FAILED")
        raise
    print("LAB_AUDIT_PUBLISHED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

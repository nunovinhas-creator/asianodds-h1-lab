"""Concurrency-safe publication of the H1 collector commit (no rebase, no force push).

Replaces ``git add data/lab ... && git pull --rebase origin main && git push origin main``
in ``collect.yml``. That sequence ran AFTER the Telegram notifiers had already sent
messages: any rebase conflict, ``cannot lock ref`` race or HTTP 408 failed the job
and discarded the new Telegram receipts, the cooldown and the collected
observations (see docs/audit/collector-lab-publication-2026-11-02.md).

Two subcommands:

``stage``    stage exactly the collector-owned paths that changed (the explicit
             ownership matrix in ``scripts.publication_ownership``) instead of
             ``git add data/lab``; any other local change is reported, never
             published.
``publish``  transport the collector commit over the current remote ``main`` with
             the shared selective publisher (``scripts.git_selective_publish``).

Collector-owned outputs: ``data/state.json``, ``docs/data.json`` (derived; re-rendered
offline when H1 results moved), the two active Telegram receipt ledgers, the shared
Telegram delivery block, the V4 market and format latest views and the V4 revision
journal. Concurrent changes by FT, LAB V4, LLM, statistics, quality, site or
documentation commits are kept byte-for-byte: none of them is a collector input.
A concurrent change to any collector-owned path (a second collector), a program
change, a frozen legacy ledger or an unknown path refuses the publication.

The publisher never re-collects, never calls Telegram (neither the channel nor the
Bot API) and never changes alert eligibility. Delivery remains AT-LEAST-ONCE with
``TG_DURABLE_INTENT=0``: when publication fails after a send, the failure receipt
lists every receipt that is not on ``main`` so the operator knows which alerts the
next cycle may resend. Exactly-once is not claimed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts import git_selective_publish as sel
from scripts import publication_ownership as own
from scripts.lab_ft_publish_safe import (append_only_jsonl, stable_fixtures,
                                         valid_telegram_block_update)

MESSAGE = "data: collect and notify H1 [skip ci]"
TERMINAL = ("sent", "delivery_uncertain_manual_review", "delivery_rejected_final",
            "expired_not_sent")
KEEP_OWNERS = frozenset({own.FT, own.LAB_V4, own.LLM, own.OFFLINE_STATS, own.LAB_QUALITY,
                         own.SITE, own.MANUAL_REVIEW, own.DOCUMENTATION})
RENDER_INPUTS = frozenset({"data/results.csv"})


def _refuse(message, kind="INTEGRITY"):
    raise sel.PublicationRefused(message, kind)


def _json(raw, path):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, AttributeError):
        _refuse("Unreadable JSON: " + path)


# ------------------------------------------------------------------ own-change guards
def verify_state(before, after):
    """Observations are only ever added: checkpoint, alerts, signals and tickets never go back."""
    new = _json(after, own.COLLECT_STATE)
    if not isinstance(new, dict) or not all(isinstance(new.get(k), list)
                                            for k in ("alerts", "signals", "tickets")):
        _refuse("Invalid collector state")
    if type(new.get("last_id")) is not int or new["last_id"] < 0:
        _refuse("Invalid Telegram checkpoint")
    if before is None:
        return {"alerts_added": len(new["alerts"]), "last_id": new["last_id"]}
    old = _json(before, own.COLLECT_STATE)
    if new["last_id"] < old.get("last_id", 0):
        _refuse("Telegram checkpoint went back: %s -> %s" % (old.get("last_id"), new["last_id"]))
    for field, key in (("alerts", "event_id"), ("signals", "signal_id"), ("tickets", "ticket_id")):
        had = {r.get(key) for r in old.get(field, []) if isinstance(r, dict)}
        has = {r.get(key) for r in new[field] if isinstance(r, dict)}
        if not had <= has:
            _refuse("Collected %s removed: %r" % (field, sorted(map(str, had - has))[:5]))
    if not stable_fixtures(before, after):
        _refuse("Fixture identity rewritten in collector state")
    return {"alerts_added": len(new["alerts"]) - len(old.get("alerts", [])),
            "last_id_before": old.get("last_id"), "last_id": new["last_id"]}


def receipts(raw, path):
    doc = _json(raw, path)
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or \
            not isinstance(doc.get("entries"), dict) or \
            any(not isinstance(k, str) or not isinstance(v, dict) for k, v in doc["entries"].items()):
        _refuse("Invalid Telegram receipt ledger: " + path)
    return doc


def verify_receipts(before, after, path):
    """Receipts are kept forever; a terminal receipt (sent/uncertain/final/expired) never changes."""
    new = receipts(after, path)
    if before is None:
        return
    old = receipts(before, path)
    if old.get("rule_version") != new.get("rule_version"):
        _refuse("Telegram rule version changed in receipts: " + path)
    for key, entry in old["entries"].items():
        cur = new["entries"].get(key)
        if cur is None:
            _refuse("Telegram receipt removed: %s %s" % (path, key))
        if entry.get("status") in TERMINAL and cur != entry:
            _refuse("Terminal Telegram receipt changed: %s %s" % (path, key))
        if entry.get("kickoff_utc") != cur.get("kickoff_utc"):
            _refuse("Telegram receipt identity changed: %s %s" % (path, key))


def changed_receipts(before, after):
    old = (_json(before, "ledger") or {}).get("entries", {}) if before else {}
    new = (_json(after, "ledger") or {}).get("entries", {}) if after else {}
    rows = []
    for key in sorted(new):
        if old.get(key) != new[key]:
            entry = new[key]
            rows.append({"match_key": key, "status": entry.get("status"),
                         "telegram_message_id": entry.get("telegram_message_id"),
                         "at": entry.get("at")})
    return rows


def _view_rows(raw, path):
    rows = {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("Undecodable V4 view: " + path)
    if text and not text.endswith("\n"):
        _refuse("Unterminated V4 view: " + path)
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            _refuse("Corrupt V4 view row: " + path)
        if not isinstance(row, dict) or not isinstance(row.get("event_id"), str):
            _refuse("V4 view row without event_id: " + path)
        if row["event_id"] in rows:
            _refuse("Duplicate event in V4 view: " + path)
        rows[row["event_id"]] = row
    return rows


def _view_family(path):
    """(prefix, month) of a latest-view partition (all parts of a month form one view)."""
    name = path.rsplit("/", 1)[1]
    prefix = "markets" if name.startswith("markets-") else "formats"
    return prefix, name[len(prefix) + 1:len(prefix) + 8]


def verify_views(root, before_ref, after_ref, paths):
    """A latest view may be updated or repartitioned, but never loses an observed event."""
    families = {_view_family(p) for p in paths}
    listing = {}
    for ref in (before_ref, after_ref):
        names = sel.git(root, "ls-tree", "-r", "--name-only", "-z", ref, "--", "data/lab/")
        listing[ref] = [n.decode() for n in names.split(b"\0") if n]
    for prefix, month in sorted(families):
        pattern = own.MARKETS_VIEW if prefix == "markets" else own.FORMATS_VIEW
        events = {}
        for ref in (before_ref, after_ref):
            merged = {}
            for name in listing[ref]:
                if pattern.fullmatch(name) and _view_family(name) == (prefix, month):
                    rows = _view_rows(sel.blob(root, ref, name), name)
                    if merged.keys() & rows.keys():
                        _refuse("Event duplicated across V4 view parts: %s-%s" % (prefix, month))
                    merged.update(rows)
            events[ref] = merged
        lost = events[before_ref].keys() - events[after_ref].keys()
        if lost:
            _refuse("V4 latest view lost observed events: %s-%s %r"
                    % (prefix, month, sorted(lost)[:5]))


def verify_change(root, before_ref, after_ref, paths, *, now=None):
    info = {"telegram_receipts_changed": [], "v4_revisions_appended": 0}
    views = []
    for path in sorted(paths):
        before, after = sel.blob(root, before_ref, path), sel.blob(root, after_ref, path)
        if path == own.COLLECT_STATE:
            if after is None:
                _refuse("Collector state deleted")
            info.update(verify_state(before, after))
        elif path in own.TELEGRAM_LEDGERS:
            if after is None:
                _refuse("Telegram receipt ledger deleted: " + path)
            verify_receipts(before, after, path)
            for row in changed_receipts(before, after):
                info["telegram_receipts_changed"].append({"ledger": path, **row})
        elif path == own.TELEGRAM_BLOCK:
            if not valid_telegram_block_update(before, after, now):
                _refuse("Telegram delivery block shortened, rewound or invalid")
            info["telegram_block"] = "removed" if after is None else "updated"
        elif own.V4_REVISIONS.fullmatch(path):
            if after is None or not append_only_jsonl(before, after):
                _refuse("V4 revision journal rewritten: " + path)
            info["v4_revisions_appended"] += after.count(b"\n") - (before or b"").count(b"\n")
        elif own.MARKETS_VIEW.fullmatch(path) or own.FORMATS_VIEW.fullmatch(path):
            views.append(path)
        elif path == own.COLLECT_RENDERED:
            if after is None or not isinstance(_json(after, path), dict):
                _refuse("Dashboard data invalid or deleted")
        else:
            _refuse("Not a collector output: " + path, "NOT_OWNER")
    if views:
        verify_views(root, before_ref, after_ref, views)
    return info


class CollectorPolicy(sel.Policy):
    name = "COLLECT"
    message = MESSAGE
    rerender_paths = frozenset({own.COLLECT_RENDERED})

    def __init__(self, render=None, now=None):
        self._render = render
        self._now = now

    def owns(self, path):
        return own.is_collector_owned(path)

    def verify_own(self, root, base, source, produced):
        return verify_change(root, base, source, produced, now=self._now)

    def check_remote(self, root, base, remote, path, produced, source):
        owner = own.owner_of(path)
        if path == own.COLLECT_RENDERED or path in RENDER_INPUTS:
            if sel.blob(root, remote, path) is None:
                _refuse("Dashboard input deleted concurrently: " + path)
            return "rerender"
        if owner == own.COLLECTOR:
            _refuse("Concurrent collector writer changed " + path, "CONCURRENT_OWNER_WRITE")
        if owner == own.PROGRAM:
            _refuse("Incompatible program change: " + path, "INCOMPATIBLE_PROGRAM")
        if owner == own.LEGACY:
            _refuse("Frozen legacy Telegram ledger changed: " + path)
        if owner == own.H1_RESULTS:
            if sel.blob(root, remote, path) is None:
                _refuse("H1 result output deleted: " + path)
            return "keep"
        if owner in KEEP_OWNERS:
            return "keep"
        _refuse("Unknown concurrent path: " + path, "UNKNOWN_PATH")

    def rerender(self, root):
        if self._render is not None:
            return self._render(root)
        proc = subprocess.run([sys.executable, "-m", "h1lab.cli", "render"], cwd=str(root),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode:
            _refuse("Offline dashboard re-render failed: "
                    + proc.stderr.decode("utf-8", "replace")[-300:], "RERENDER_FAILED")

    def verify_candidate(self, root, remote, candidate, produced):
        verify_change(root, remote, candidate, produced, now=self._now)

    def failure_diagnostics(self, root, base, source):
        produced = sel.changed_paths(root, base, source)
        rows = []
        for path in sorted(produced & set(own.TELEGRAM_LEDGERS)):
            for row in changed_receipts(sel.blob(root, base, path), sel.blob(root, source, path)):
                rows.append({"ledger": path, **row})
        sent = [r for r in rows if r["status"] == "sent"]
        state = {}
        if own.COLLECT_STATE in produced:
            try:
                state = verify_state(sel.blob(root, base, own.COLLECT_STATE),
                                     sel.blob(root, source, own.COLLECT_STATE))
            except sel.PublicationRefused:
                state = {"state": "invalid"}
        return {
            "telegram_receipts_unpublished": rows,
            "telegram_block_unpublished": own.TELEGRAM_BLOCK in produced,
            "resend_risk": ("AT_LEAST_ONCE: %d sent alert(s) are not recorded on main; the next "
                            "cycle may send them again (TG_DURABLE_INTENT=0)" % len(sent))
            if sent else "NONE_KNOWN",
            "observations_unpublished": state,
        }


# ------------------------------------------------------------------ stage
def stage(root):
    """Stage exactly the changed collector-owned paths; report anything else."""
    root = Path(root)
    raw = sel.git(root, "status", "--porcelain", "-z", "--untracked-files=all", "--no-renames")
    staged, unexpected = [], []
    for item in raw.split(b"\0"):
        if not item:
            continue
        path = item[3:].decode("utf-8")
        if own.is_collector_owned(path):
            staged.append(path)
        elif not path.endswith(".tmp"):
            unexpected.append(path)
    if staged:
        sel.git(root, "add", "-A", "--", *staged)
    print("COLLECT_STAGED", json.dumps({"paths": staged}, sort_keys=True))
    if unexpected:
        # Never published by the collector; visible so an unexpected writer is noticed.
        print("::warning title=COLLECT_UNEXPECTED_LOCAL_CHANGES::" + ", ".join(unexpected[:10]))
    return staged, unexpected


def _annotate(document):
    rows = document.get("telegram_receipts_unpublished") or []
    print("::error title=COLLECT_PUBLICATION_FAILED::status=%s kind=%s attempts=%s reason=%s"
          % (document.get("status"), document.get("reason_kind"), document.get("attempts"),
             str(document.get("reason"))[:300]))
    if rows:
        print("::error title=TELEGRAM_RECEIPTS_NOT_ON_MAIN::%s" % "; ".join(
            "%s %s %s msg=%s" % (r["ledger"].rsplit("/", 1)[1], r["match_key"], r["status"],
                                 r["telegram_message_id"]) for r in rows[:20]))
        print("::error title=TELEGRAM_RESEND_RISK::" + document.get("resend_risk", ""))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("stage").add_argument("--root", type=Path, default=Path.cwd())
    pub = sub.add_parser("publish")
    pub.add_argument("--root", type=Path, default=Path.cwd())
    pub.add_argument("--base", required=True)
    pub.add_argument("--receipt", type=Path)
    pub.add_argument("--bundle", type=Path)
    pub.add_argument("--max-attempts", type=int, default=6)
    args = parser.parse_args(argv)
    if args.mode == "stage":
        stage(args.root)
        return 0
    try:
        sel.publish(args.root, base=args.base, policy=CollectorPolicy(), receipt=args.receipt,
                    bundle=args.bundle, max_attempts=args.max_attempts)
    except sel.PublicationRefused:
        if args.receipt and args.receipt.exists():
            _annotate(json.loads(args.receipt.read_text()))
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())

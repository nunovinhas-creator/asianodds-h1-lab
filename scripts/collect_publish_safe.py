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
# Field policy (docs/audit/collector-lab-publication-2026-11-02.md, section 3.1):
#   state.json  alerts/signals/tickets: IMMUTABLE whole records once published (core.incorporate
#               only appends); last_id never decreases; diagnostics/collector are mutable status.
#   markets-*   latest V4 view: event_id and observed_at (original Telegram time) immutable; any
#               other change is legitimate ONLY when the V4 revision journal gained a revision of
#               that event whose snapshot is exactly the new row (verify_projection + SHA chain).
#   formats-*   structural signature: event_id/observed_at immutable; content may change only for
#               an event revised in the same commit's V4 journal.
#   v4-revisions append-only SHA chain (previous content, new content, known_at, parser provenance).
IMMUTABLE_COLLECTIONS = (("alerts", "event_id"), ("signals", "signal_id"), ("tickets", "ticket_id"))
REVISION_KINDS = ("EDIT_DATE_CHANGED", "CONTENT_CHANGED_EDIT_UNPROVEN")


def _keyed(rows, key, field):
    out = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row[key]:
            _refuse("Collected %s record without %s" % (field, key))
        if row[key] in out:
            _refuse("Duplicate collected %s: %s" % (field, row[key]))
        out[row[key]] = row
    return out


def verify_state(before, after):
    """Published observations are immutable records; only new ones may be appended."""
    new = _json(after, own.COLLECT_STATE)
    if not isinstance(new, dict) or not all(isinstance(new.get(k), list)
                                            for k in ("alerts", "signals", "tickets")):
        _refuse("Invalid collector state")
    if type(new.get("last_id")) is not int or new["last_id"] < 0:
        _refuse("Invalid Telegram checkpoint")
    current = {field: _keyed(new[field], key, field) for field, key in IMMUTABLE_COLLECTIONS}
    if before is None:
        return {"alerts_added": len(new["alerts"]), "last_id": new["last_id"]}
    old = _json(before, own.COLLECT_STATE)
    if new["last_id"] < old.get("last_id", 0):
        _refuse("Telegram checkpoint went back: %s -> %s" % (old.get("last_id"), new["last_id"]))
    for field, key in IMMUTABLE_COLLECTIONS:
        for ident, row in _keyed(old.get(field, []), key, field).items():
            if ident not in current[field]:
                _refuse("Collected %s removed: %s" % (field, ident))
            if current[field][ident] != row:
                changed = sorted(k for k in set(row) | set(current[field][ident])
                                 if row.get(k) != current[field][ident].get(k))
                _refuse("Published %s rewritten in place: %s fields %r" % (field, ident, changed[:6]))
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


def _v4_paths(root, ref):
    raw = sel.git(root, "ls-tree", "-r", "--name-only", "-z", ref, "--", "data/lab/")
    return [n.decode() for n in raw.split(b"\0") if n and (
        own.MARKETS_VIEW.fullmatch(n.decode()) or own.FORMATS_VIEW.fullmatch(n.decode())
        or own.V4_REVISIONS.fullmatch(n.decode()))]


def _materialise(root, ref, directory):
    """Write exactly the V4 files of ``ref`` so the production readers can replay them."""
    for name in _v4_paths(root, ref):
        target = Path(directory) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sel.blob(root, ref, name))
    (Path(directory) / "data/lab").mkdir(parents=True, exist_ok=True)


def _family_rows(directory, prefix):
    from h1lab.lab_archive import monthly_paths
    rows = {}
    for part in monthly_paths(directory, prefix):
        for event_id, row in _view_rows(part.read_bytes(), str(part.name)).items():
            if event_id in rows:
                _refuse("Event duplicated across V4 view parts: " + event_id)
            rows[event_id] = row
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


def verify_v4(root, before_ref, after_ref):
    """Replay the V4 journal and views of both trees with the production readers.

    * the revision journal of ``after`` is a valid SHA chain whose prefix is the ``before`` chain;
    * the markets latest view of ``after`` is exactly the latest journal snapshot of every event
      (``v4_revisions.verify_projection``) - a revision for a missing event, a broken hash or an
      unjournalled edit all fail here;
    * an event's view row may change only through a NEW revision (edit/content change) of that
      event, never its event_id or original Telegram time;
    * no observed event leaves a view; format rows change only for revised events.
    """
    import tempfile
    from h1lab import v4_revisions as rev
    with tempfile.TemporaryDirectory(prefix="v4-before-") as b, \
            tempfile.TemporaryDirectory(prefix="v4-after-") as a:
        _materialise(root, before_ref, b)
        _materialise(root, after_ref, a)
        try:
            old_events = rev.read_events(b)
            new_events = rev.read_events(a)
            rev.verify_projection(a)
        except (ValueError, KeyError, TypeError) as exc:
            _refuse("V4 revision journal or projection invalid: %s" % exc)
        if new_events[:len(old_events)] != old_events:
            _refuse("V4 revision journal history rewritten")
        added = new_events[len(old_events):]
        revised = {e["event_id"] for e in added if e.get("kind") in REVISION_KINDS}
        for prefix in ("markets", "formats"):
            old_rows, new_rows = _family_rows(b, prefix), _family_rows(a, prefix)
            lost = sorted(old_rows.keys() - new_rows.keys())
            if lost:
                _refuse("V4 latest view lost observed events: %s %r" % (prefix, lost[:5]))
            for event_id, row in old_rows.items():
                cur = new_rows[event_id]
                if cur.get("observed_at") != row.get("observed_at"):
                    _refuse("Original Telegram time rewritten: %s %s" % (prefix, event_id))
                if prefix == "markets":
                    if rev.fingerprint(cur) != rev.fingerprint(row) and event_id not in revised:
                        _refuse("V4 observation changed without an audited revision: " + event_id)
                elif cur != row and event_id not in revised:
                    _refuse("Format observation rewritten without a V4 revision: " + event_id)
        for e in added:
            if e.get("kind") in REVISION_KINDS:
                previous = next((x for x in reversed(old_events + added[:added.index(e)])
                                 if x["event_id"] == e["event_id"]), None)
                if previous is None or e["telegram_original_at"] != previous["telegram_original_at"]:
                    _refuse("V4 revision does not continue its event: " + e["event_id"])
        kinds = {}
        for e in added:
            kinds[e.get("kind")] = kinds.get(e.get("kind"), 0) + 1
        return {"v4_revisions_appended": len(added), "v4_revision_kinds": kinds,
                "v4_revised_events": sorted(revised)[:20]}


def dashboard_is_coherent(root, ref):
    """docs/data.json must be exactly public_data(state, results, generated_at) of ``ref``."""
    import tempfile
    from h1lab.core import load_results, public_data
    raw, state = sel.blob(root, ref, own.COLLECT_RENDERED), sel.blob(root, ref, own.COLLECT_STATE)
    if raw is None or state is None:
        return False
    try:
        view = json.loads(raw)
        moment = datetime.fromisoformat(view["generated_at"])
        with tempfile.TemporaryDirectory(prefix="results-") as d:
            path = Path(d) / "results.csv"
            path.write_bytes(sel.blob(root, ref, "data/results.csv") or b"")
            expected = public_data(json.loads(state), load_results(path), moment)
        return json.loads(json.dumps(expected, ensure_ascii=False)) == view
    except (ValueError, KeyError, TypeError):
        return False


def render_dashboard(root):
    """In-process equivalent of ``h1lab.cli render`` for an arbitrary checkout root."""
    from h1lab.core import dump_json, load_results, public_data
    root = Path(root)
    state = json.loads((root / own.COLLECT_STATE).read_text(encoding="utf-8"))
    dump_json(root / own.COLLECT_RENDERED,
              public_data(state, load_results(root / "data/results.csv"), datetime.now(timezone.utc)))


def verify_change(root, before_ref, after_ref, paths, *, now=None):
    info = {"telegram_receipts_changed": []}
    v4 = False
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
            v4 = True
        elif own.MARKETS_VIEW.fullmatch(path) or own.FORMATS_VIEW.fullmatch(path):
            v4 = True
        elif path == own.COLLECT_RENDERED:
            if after is None or not isinstance(_json(after, path), dict):
                _refuse("Dashboard data invalid or deleted")
            if not dashboard_is_coherent(root, after_ref):
                _refuse("docs/data.json is not the render of the published state and results")
        else:
            _refuse("Not a collector output: " + path, "NOT_OWNER")
    if v4:
        info.update(verify_v4(root, before_ref, after_ref))
    return info


class CollectorPolicy(sel.Policy):
    name = "COLLECT"
    message = MESSAGE
    rerender_paths = frozenset({own.COLLECT_RENDERED})

    def __init__(self, render=None, now=None):
        self._render = render or render_dashboard
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
        try:
            self._render(root)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _refuse("Offline dashboard re-render failed: %s" % exc, "RERENDER_FAILED")

    def verify_equivalent(self, root, remote):
        """An 'already published' main must also carry a coherent derived dashboard."""
        return dashboard_is_coherent(root, remote)

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
def stage(root, park=None):
    """Stage exactly the changed collector-owned paths; unstage and report anything else.

    Tracked non-collector files left modified by an earlier step are never published. With
    ``park`` their diff is saved to that patch file and the files are restored, so the selective
    publisher starts from a clean checkout instead of refusing the whole collector commit.
    """
    root = Path(root)
    pre = sel.git(root, "diff", "--cached", "--name-only", "-z", "--no-renames")
    foreign_staged = [n.decode() for n in pre.split(b"\0")
                      if n and not own.is_collector_owned(n.decode())]
    if foreign_staged:
        # Staged by an earlier step: never let them ride along in the collector commit.
        sel.git(root, "reset", "-q", "--", *foreign_staged)
        print("::warning title=COLLECT_FOREIGN_STAGED_REMOVED::" + ", ".join(foreign_staged[:10]))
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
    tracked = [p for p in unexpected
               if sel.run(root, "ls-files", "--error-unmatch", "--", p, check=False).returncode == 0]
    parked = []
    if park and tracked:
        Path(park).parent.mkdir(parents=True, exist_ok=True)
        Path(park).write_bytes(sel.git(root, "diff", "--binary", "--", *tracked))
        sel.git(root, "checkout", "-q", "--", *tracked)
        parked = tracked
        print("::warning title=COLLECT_FOREIGN_CHANGES_PARKED::%s (patch: %s)"
              % (", ".join(tracked[:10]), park))
    print("COLLECT_STAGED", json.dumps({"paths": staged, "foreign_unstaged": foreign_staged,
                                        "parked": parked}, sort_keys=True))
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
    st = sub.add_parser("stage")
    st.add_argument("--root", type=Path, default=Path.cwd())
    st.add_argument("--park", type=Path, help="save and restore tracked non-collector changes")
    pub = sub.add_parser("publish")
    pub.add_argument("--root", type=Path, default=Path.cwd())
    pub.add_argument("--base", required=True)
    pub.add_argument("--receipt", type=Path)
    pub.add_argument("--bundle", type=Path)
    pub.add_argument("--max-attempts", type=int, default=6)
    args = parser.parse_args(argv)
    if args.mode == "stage":
        stage(args.root, park=args.park)
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

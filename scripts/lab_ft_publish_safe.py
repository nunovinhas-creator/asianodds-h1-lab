"""Publish an already sealed FT commit across unrelated H1/V4 Git activity.

Use only AFTER the FT producers, immutable-FINAL guard, segment staging and
publication seal have succeeded. No provider calls, blind retries, rebases,
force pushes or rewrites of concurrent FT artifacts.

The original FT commit is transplanted byte-for-byte over the current remote
tree with an isolated Git index. The new tree is *fully* verified before an
ordinary fast-forward Git push. Changed FT files, mutated identities, rewritten
journals, code, or unknown remote paths always abort.

Every exit leaves an ``FT_PUBLISH_RECEIPT`` log line. Refusals and failures
(``UnsafeFTPublication`` and any unexpected error) emit status ``REFUSED``,
``PUSH_REFUSED``, ``RETRY_EXHAUSTED`` or ``OUTCOME_UNRESOLVED`` with the exact
reason, its classified ``reason_kind`` and the context reached (base, source
commit, remote head, attempt), optionally a JSON receipt file and a verified
Git bundle of the unpublished FT commit -- and then still fail. A receipt never
publishes anything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import git_publish_outcome as outcome
from scripts import publication_guard
from scripts import publication_ownership as own
from scripts.lab_discovery_authoritative_release import main as discovery_verify
from h1lab.lab_ft_final_guard import verify_files

SHA = re.compile(r"[a-f0-9]{40}\Z")
JOURNAL = re.compile(r"data/lab/(?:markets|formats|v4-revisions|v4-runchecks)-\d{4}-\d{2}\.jsonl\Z")
V4_REPORT = re.compile(
    r"docs/lab/(?:v4-audit|v4-revisions|golden-candidates|golden-report|"
    r"golden-priority|v6-shadow|v6-readiness|v6-price-quality|"
    r"v6-feature-coverage|v6-memory|v6-falsification|"
    r"match-trajectories|trajectory-research|outcome-readiness|"
    r"v6-scientific-radar|v6-weekly-drift|v6-archive-health|"
    r"v6-p0-null-simulation|v6-p0-gates)\.json\Z"
)
V4_ARCHIVE = re.compile(
    r"data/lab/(?:v6-forecasts-\d{4}-\d{2}|v6-memory-(?:observations|patterns)-\d{4}-\d{2}|v6-memory-\d{4}-\d{2}|"
    r"v6-hypotheses|v6-weekly-snapshots|v4-runchecks(?:-\d{4}-\d{2})?)\.jsonl\Z"
)
LLM_SHADOW = re.compile(
    r"docs/lab/(?:llm-discovery-plan|llm-investigator-index|"
    r"llm-investigator-runs/\d+)\.json\Z"
)

# Known H1 Telegram receipts are independent of FT evidence.
H1_NOTIFICATION_RECEIPTS = frozenset({
    "data/e5-over25-notifications.json",
    "data/three-total-moves-notifications.json",
    "data/two-up-total-notifications.json",
    "data/e4-notifications.json",
    "data/strategy-notifications.json",
    "data/pattern-notifications.json",
    "data/t05-notifications.json",
})
H1_RESULT_OUTPUTS = frozenset({
    "data/results.csv", "data/result_audit.json", "data/health/h1-results.json",
})


class UnsafeFTPublication(ValueError):
    pass


def run(root, *args, env=None, input_bytes=None, check=True):
    proc = subprocess.run(["git", "-C", str(root), *args], input=input_bytes,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if check and proc.returncode:
        raise UnsafeFTPublication(
            "Git operation failed: " + " ".join(args[:2])
            + " (" + proc.stderr.decode("utf-8", "replace")[-350:] + ")")
    return proc


def git(root, *args, env=None):
    return run(root, *args, env=env).stdout


def sha(root, ref):
    value = git(root, "rev-parse", "--verify", ref).decode().strip()
    if not SHA.fullmatch(value):
        raise UnsafeFTPublication("Invalid Git revision " + ref)
    return value


def changed_paths(root, base, target):
    result = git(root, "diff", "--name-only", "-z", base, target)
    names = set(p.decode("utf-8") for p in result.split(b"\0") if p)
    if any(not name or name.startswith("/") or "\\x00" in name
           for name in names):
        raise UnsafeFTPublication("Malformed Git paths")
    return names


def blob_or_none(root, ref, path):
    proc = run(root, "show", ref + ":" + path, check=False)
    if proc.returncode:
        return None
    return proc.stdout


def stable_fixtures(before, after):
    """H1 odds can change, but shared match identities may never change."""
    try:
        a, b = json.loads(before), json.loads(after)
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        def ids(state):
            result = {}
            for field in ("alerts", "signals"):
                rows = state.get(field, [])
                if not isinstance(rows, list):
                    raise ValueError("Invalid H1 events")
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError("Invalid H1 observation")
                    key = row.get("match_key")
                    if not isinstance(key, str) or not key:
                        continue
                    identity = (row.get("home"), row.get("away"),
                                row.get("kickoff_utc"), row.get("competition"))
                    if any(not isinstance(v, str) or not v for v in identity[:3]):
                        raise ValueError("Missing fixture identity")
                    result.setdefault(key, set()).add(identity[:3])
            return result
        previous, current = ids(a), ids(b)
        return all(previous[key] == current[key]
                   for key in previous.keys() & current.keys())
    except (ValueError, TypeError):
        return False


def append_only_jsonl(previous, current):
    if previous is None:
        previous = b""
    if not current.startswith(previous) or (previous and not previous.endswith(b"\n")):
        return False
    extra = current[len(previous):]
    if extra and not extra.endswith(b"\n"):
        return False
    try:
        return all(isinstance(json.loads(line), dict)
                   for line in extra.splitlines() if line)
    except (ValueError, UnicodeDecodeError):
        return False



def valid_notification_update(previous, current):
    """Accept only retained, schema-valid receipts; never discard H1 history."""
    if previous is None or current is None:
        return False
    try:
        old, new = json.loads(previous), json.loads(current)
        if not isinstance(old, dict) or not isinstance(new, dict):
            return False
        if old.get("schema_version") != 1 or new.get("schema_version") != 1:
            return False
        before, after = old.get("entries"), new.get("entries")
        if not isinstance(before, dict) or not isinstance(after, dict):
            return False
        if any(not isinstance(key, str) or not isinstance(row, dict)
               for key, row in after.items()):
            return False
        if not before.keys() <= after.keys():
            return False
        for key, prior in before.items():
            if not isinstance(prior, dict):
                return False
            updated = after[key]
            # Withdrawals may change status; fixture identity never changes.
            for field in ("match_key", "kickoff_utc"):
                if field in prior and prior[field] != updated.get(field):
                    return False
        return True
    except (ValueError, UnicodeDecodeError, TypeError):
        return False



# This is a derived read-only H1/Telegram diagnostic, not an FT dependency.
# It may be regenerated between FT checkout and FT publication.
TELEGRAM_ELIGIBILITY_REPORT = "docs/lab/telegram-eligibility.json"


def _eligibility_timestamp(value):
    from datetime import datetime, timezone
    if not isinstance(value, str):
        raise ValueError("Invalid UTC eligibility timestamp")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None or moment.utcoffset().total_seconds() != 0:
        raise ValueError("Eligibility timestamp must be UTC")
    return moment.astimezone(timezone.utc)


def _valid_eligibility_report(raw):
    """Validate the independent report without treating it as FT evidence.

    Its visible game window can legitimately rotate. Cross-version validation
    therefore protects identities of shared games, never requires key growth.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 512_000:
        return None
    try:
        from h1lab import telegram_eligibility as eligibility
        from h1lab import three_moves_notify, two_up_notify
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise ValueError("Duplicate JSON key")
                out[key] = value
            return out
        def reject_constant(value):
            raise ValueError("Nonfinite JSON number")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=reject_constant)
        if not isinstance(data, dict) or data.get("schema_version") != eligibility.SCHEMA:
            return None
        if data.get("status") != "READ_ONLY_PARITY_VERIFIED_NOT_DELIVERY_PROOF":
            return None
        if data.get("rules") != {
                "three": three_moves_notify.RULE_VERSION,
                "two": two_up_notify.RULE_VERSION}:
            return None
        _eligibility_timestamp(data.get("generated_at"))
        if (not isinstance(data.get("source_commit"), str)
                or data["source_commit"] != "unknown"
                and not SHA.fullmatch(data["source_commit"])):
            return None
        if not isinstance(data.get("limitations"), str) or not data["limitations"]:
            return None
        games, summary = data.get("games"), data.get("summary")
        if not isinstance(games, dict) or not isinstance(summary, dict):
            return None
        fields = (
            "future_three_eligible", "future_two_eligible", "visible_games",
            "future_visible_exclusions", "review_possible_false_negative",
            "v4_source_errors",
        )
        if any(type(summary.get(field)) is not int or summary[field] < 0
               for field in fields):
            return None
        if summary["visible_games"] != len(games):
            return None
        reviews = 0
        for key, game in games.items():
            if (not isinstance(key, str) or not key
                    or not isinstance(game, dict)
                    or game.get("match_key") != key
                    or not isinstance(game.get("match_label"), str)
                    or not game["match_label"]):
                return None
            kickoff = game.get("kickoff_utc")
            if kickoff is not None:
                _eligibility_timestamp(kickoff)
            for field in ("three_eligible", "two_eligible", "v4_down_observed",
                          "review_possible_false_negative"):
                if type(game.get(field)) is not bool:
                    return None
            for field in ("observed_messages", "v4_moves_observed",
                          "valid_three_moves", "v4_up_observed", "valid_up_moves"):
                if type(game.get(field)) is not int or game[field] < 0:
                    return None
            if (not isinstance(game.get("net_up"), (int, float))
                    or isinstance(game["net_up"], bool)):
                return None
            # json.loads rejects NaN and infinity through parse_constant.
            if (not isinstance(game.get("rejects"), dict)
                    or any(not isinstance(k, str) or not k or
                           type(v) is not int or v < 0
                           for k, v in game["rejects"].items())):
                return None
            if not isinstance(game.get("reason"), str):
                return None
            if game.get("review_note") is not None and not isinstance(game["review_note"], str):
                return None
            receipts = game.get("receipts")
            if (not isinstance(receipts, dict)
                    or any(kind not in ("three", "two") for kind in receipts)):
                return None
            for entry in receipts.values():
                if (not isinstance(entry, dict)
                        or entry.get("status") not in (
                            "sent", "delivery_uncertain_manual_review",
                            "delivery_rejected_final", "expired_not_sent")
                        or (entry.get("telegram_message_id") is not None and
                            (type(entry["telegram_message_id"]) is not int or
                             entry["telegram_message_id"] < 0))):
                    return None
            reviews += int(game["review_possible_false_negative"])
        if summary["review_possible_false_negative"] != reviews:
            return None
        return data
    except (ValueError, TypeError, UnicodeDecodeError, OverflowError, KeyError):
        return None


def valid_telegram_eligibility_update(previous, current):
    """Allow only a newer valid read-only report; never overwrite remote H1.

    A rotating visible-games window is allowed. Overlapping fixture identity
    and observed Telegram receipts are immutable, while eligibility flags can
    naturally change with incoming observations and kickoff.
    """
    old = _valid_eligibility_report(previous)
    new = _valid_eligibility_report(current)
    if old is None or new is None:
        return False
    try:
        if (_eligibility_timestamp(new["generated_at"]) <
                _eligibility_timestamp(old["generated_at"])):
            return False
        for key in old["games"].keys() & new["games"].keys():
            before, after = old["games"][key], new["games"][key]
            if any(before.get(field) != after.get(field)
                   for field in ("match_key", "match_label", "kickoff_utc")):
                return False
            for rule, receipt in before["receipts"].items():
                if after["receipts"].get(rule) != receipt:
                    return False
        return True
    except (KeyError, ValueError, TypeError):
        return False


# Shared Telegram flood-wait / auth pause (h1lab.telegram_block). It is read only
# by the Telegram sender and never by FT producers, so a concurrent update cannot
# change FT evidence. Only this exact path, schema and value set is accepted.
TELEGRAM_BLOCK = "data/telegram-delivery-block.json"
_BLOCK_FIELDS = frozenset({"schema_version", "until", "http_status", "set_at", "diagnosis"})
_BLOCK_DIAGNOSES = {
    429: frozenset({"FLOOD_WAIT_RETRY_AFTER", "FLOOD_WAIT_CONSERVATIVE_5MIN",
                    "FLOOD_WAIT_CONSERVATIVE_BACKOFF"}),
    401: frozenset({"AUTH_REJECTED_CHECK_TG_BOT_TOKEN_AND_TG_CHAT_ID"}),
    403: frozenset({"AUTH_REJECTED_CHECK_TG_BOT_TOKEN_AND_TG_CHAT_ID"}),
}
_BLOCK_MAX_BYTES = 1024
# Clock policy. Writer (collector job) and validator (FT job) are both GitHub-hosted runners
# synchronised by the host (skew well under a second). A legitimate set_at is never in the
# validator's future by more than that skew, so 60 s is generous without letting a block
# "pre-date" a pause. The emitter never sets until - set_at above 24 h (+1 s retry margin):
# retry_after > 24 h is ignored upstream and the auth probe interval is 24 h. Anything beyond
# that (hours/years ahead, year 9999, ...) is refused rather than accepted as a permanent pause.
_BLOCK_CLOCK_SKEW = timedelta(seconds=60)
_BLOCK_MAX_HORIZON = timedelta(hours=24, seconds=1) + _BLOCK_CLOCK_SKEW
_BLOCK_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\+00:00|Z)")


def _utcnow():
    return datetime.now(timezone.utc)


def _block_time(value):
    if not isinstance(value, str) or not _BLOCK_TIME.fullmatch(value):
        raise ValueError("Invalid block timestamp")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise ValueError("Block timestamp must be explicit UTC")
    return moment.astimezone(timezone.utc)


def _parse_telegram_block(raw, now=None):
    """Strict parse of one block record; None when anything is off.

    With ``now`` the record must also be temporally coherent: set_at not in the future beyond the
    clock skew, until not beyond now + the maximum legitimate horizon.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= _BLOCK_MAX_BYTES:
        return None
    try:
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise ValueError("Duplicate JSON key")
                out[key] = value
            return out
        def reject_constant(value):
            raise ValueError("Nonfinite JSON number")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=reject_constant)
        if not isinstance(data, dict) or set(data) != _BLOCK_FIELDS:
            return None
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            return None
        status = data["http_status"]
        if type(status) is not int or status not in _BLOCK_DIAGNOSES:
            return None
        if data["diagnosis"] not in _BLOCK_DIAGNOSES[status]:
            return None
        until, set_at = _block_time(data["until"]), _block_time(data["set_at"])
        if set_at > until or until - set_at > _BLOCK_MAX_HORIZON:
            return None
        if now is not None and (set_at > now + _BLOCK_CLOCK_SKEW or until > now + _BLOCK_MAX_HORIZON):
            return None
        return {**data, "_until": until, "_set_at": set_at}
    except (ValueError, TypeError, UnicodeDecodeError, OverflowError):
        return None


def valid_telegram_block_update(previous, current, now=None):
    """Accept only a well-formed block that never shortens, rewinds or drops an active pause.

    previous/current are the exact blobs (None = file absent). Rules:
    - creation: any strictly valid record;
    - removal: only when the previous pause has already expired;
    - update: until and set_at never decrease; an equal `until` must be byte-identical.
    The accepted remote blob is kept byte-for-byte by the isolated-index transport.
    """
    try:
        now = _utcnow() if now is None else now
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            return False
    except (OSError, ValueError, OverflowError, AttributeError):
        return False  # current time not obtainable safely: conservative refusal
    old = None if previous is None else _parse_telegram_block(previous)
    if previous is not None and old is None:
        # A corrupt base blob is never silently "repaired" by a concurrent writer.
        return False
    if current is None:
        return old is not None and old["_until"] <= now
    new = _parse_telegram_block(current, now)
    if new is None:
        return False
    if old is None:
        return True
    if new["_until"] < old["_until"] or new["_set_at"] < old["_set_at"]:
        return False
    if new["_until"] == old["_until"] and current != previous:
        return False
    return True


_MAX_REPORTED_REFUSALS = 7


def is_collector_v4_path(path):
    """Collector V4 files of the ownership matrix, including every ``-partNNNN`` partition."""
    return bool(own.V4_REVISIONS.fullmatch(path) or own.MARKETS_VIEW.fullmatch(path)
                or own.FORMATS_VIEW.fullmatch(path))


_V4_FAMILY_PROOFS = {}


def _v4_family_proven(root, base, remote):
    """The collector's own replay of the whole V4 family, once per (base, remote) pair."""
    key = (str(Path(root).resolve()), base, remote)
    if key not in _V4_FAMILY_PROOFS:
        from scripts import git_selective_publish as sel
        from scripts.collect_publish_safe import verify_v4
        try:
            verify_v4(root, base, remote)
            _V4_FAMILY_PROOFS[key] = None
        except sel.PublicationRefused as exc:
            _V4_FAMILY_PROOFS[key] = str(exc)
        if len(_V4_FAMILY_PROOFS) > 64:
            _V4_FAMILY_PROOFS.pop(next(iter(_V4_FAMILY_PROOFS)))
    return _V4_FAMILY_PROOFS[key]


def check_collector_v4_path(root, base, remote, path):
    """Validate a concurrent collector V4 change; raise UnsafeFTPublication when unsafe.

    * ``v4-revisions-YYYY-MM[-partNNNN]`` is an append-only SHA journal: every file only grows
      (a new part starts empty); a rewritten, truncated or deleted part is refused.
    * ``markets-``/``formats-YYYY-MM[-partNNNN]`` are mutable latest views that
      ``write_monthly_view`` repartitions: rows may be revised in place, files may be split,
      merged or removed. Byte growth proves nothing about a view, so ANY change is accepted
      only with the collector's own full replay of the family
      (``collect_publish_safe.verify_v4``: valid chain, exact projection of every row, no lost
      event, original Telegram time kept, rows change only through an audited revision).
    The same replay is also required for every journal change.
    """
    if own.V4_REVISIONS.fullmatch(path):
        current = blob_or_none(root, remote, path)
        if current is None or not append_only_jsonl(blob_or_none(root, base, path), current):
            raise UnsafeFTPublication("V4 revision journal rewritten: " + path)
    reason = _v4_family_proven(root, base, remote)
    if reason is not None:
        raise UnsafeFTPublication("Collector V4 change not proven: %s (%s)" % (path, reason))


def _check_remote_path(root, base, remote, path):
    """Raise UnsafeFTPublication unless this concurrent remote change is provably unrelated to FT."""
    if (path.startswith(("h1lab/", "scripts/", ".github/", "tests/"))
            or path.startswith(("data/lab/discovery-segmented/",
                                "docs/lab/discovery-pages/"))
            or path.startswith(("data/lab/ft-", "docs/lab/ft-",
                                "data/lab/discovery-events-"))
            or path.startswith(("docs/lab/pattern-", "data/lab/pattern-"))):
        raise UnsafeFTPublication("FT dependency or program changed: " + path)
    if path == "data/state.json":
        previous = blob_or_none(root, base, path)
        current = blob_or_none(root, remote, path)
        if previous is None or current is None or not stable_fixtures(previous, current):
            raise UnsafeFTPublication("H1 fixture identity changed: " + path)
    elif path in ("docs/data.json", "data/results.json"):
        if blob_or_none(root, remote, path) is None:
            raise UnsafeFTPublication("H1 artifact deleted: " + path)
    elif path in H1_RESULT_OUTPUTS:
        # H1 results have a separate producer; keep their exact remote blobs.
        if blob_or_none(root, remote, path) is None:
            raise UnsafeFTPublication("H1 result output deleted: " + path)
    elif path == TELEGRAM_ELIGIBILITY_REPORT:
        # Independent report from another H1/Telegram producer. The FT
        # isolated-index transport retains the exact REMOTE blob.
        if not valid_telegram_eligibility_update(
                blob_or_none(root, base, path),
                blob_or_none(root, remote, path)):
            raise UnsafeFTPublication("Telegram eligibility report invalid: " + path)
    elif path == TELEGRAM_BLOCK:
        # Telegram-only pause state, independent of FT evidence. Exact path only.
        # tree_entry refuses anything but a regular 100644 blob (symlink, gitlink, tree),
        # for the previous version as well as the remote one.
        base_entry = tree_entry(root, base, path)
        remote_entry = tree_entry(root, remote, path)
        previous, current = blob_or_none(root, base, path), blob_or_none(root, remote, path)
        if (base_entry is not None and previous is None) or (
                remote_entry is not None and current is None):
            raise UnsafeFTPublication("Telegram delivery block unreadable: " + path)
        if remote_entry is not None and not valid_telegram_block_update(previous, current):
            raise UnsafeFTPublication("Telegram delivery block invalid: " + path)
        if remote_entry is None and not valid_telegram_block_update(previous, None):
            raise UnsafeFTPublication("active Telegram delivery block removed: " + path)
    elif path in H1_NOTIFICATION_RECEIPTS:
        if not valid_notification_update(
                blob_or_none(root, base, path),
                blob_or_none(root, remote, path)):
            raise UnsafeFTPublication("H1 notification receipt invalid: " + path)
    elif is_collector_v4_path(path):
        check_collector_v4_path(root, base, remote, path)
    elif JOURNAL.fullmatch(path) or V4_ARCHIVE.fullmatch(path):
        if not append_only_jsonl(blob_or_none(root, base, path),
                                 blob_or_none(root, remote, path) or b""):
            raise UnsafeFTPublication("V4/H1 journal rewritten: " + path)
    elif V4_REPORT.fullmatch(path) or LLM_SHADOW.fullmatch(path):
        if blob_or_none(root, remote, path) is None:
            raise UnsafeFTPublication("Concurrent report deleted: " + path)
    elif path == "data/lab/v6-archive-index.json":
        # Archive index changes can invalidate V4 origin provenance.
        raise UnsafeFTPublication("V4 source archive index changed")
    elif own.LAB_V4_JOURNALS.fullmatch(path):
        # Every append-only LAB V4 journal of the ownership matrix (V6 forecasts and ALL memory
        # kinds -- evidence/decisions/hypotheses included -- weekly snapshots, run checks, any
        # -partNNNN file). No FT producer reads them; they may only grow (incident FT #41476501130:
        # data/lab/v6-memory-evidence-2026-11.jsonl was refused as "unknown").
        if not append_only_jsonl(blob_or_none(root, base, path),
                                 blob_or_none(root, remote, path) or b""):
            raise UnsafeFTPublication("V4/H1 journal rewritten: " + path)
    elif own.owner_of(path) == own.OFFLINE_STATS:
        # V6 offline statistics (research only, not an FT input). Immutable run history may only be
        # added; the latest report may be replaced but never deleted.
        current = blob_or_none(root, remote, path)
        if current is None:
            raise UnsafeFTPublication("Concurrent report deleted: " + path)
        if path != "docs/lab/llm-statistics.json" and blob_or_none(root, base, path) is not None:
            raise UnsafeFTPublication("Immutable V6 run history rewritten: " + path)
    elif path == own.QUALITY:
        if blob_or_none(root, remote, path) is None:
            raise UnsafeFTPublication("Concurrent report deleted: " + path)
    else:
        raise UnsafeFTPublication("Unknown concurrent path: " + path)


def allowed_remote_changes(root, base, remote, protected, produced):
    remote_changes = changed_paths(root, base, remote)
    overlap = remote_changes & (protected | produced)
    if overlap:
        raise UnsafeFTPublication(
            "Concurrent FT/sealed artifact changed: " + ", ".join(sorted(overlap)[:8]))
    violations = []
    for path in sorted(remote_changes):
        try:
            _check_remote_path(root, base, remote, path)
        except UnsafeFTPublication as exc:
            violations.append(str(exc))
    if violations:
        # Still a hard refusal (nothing is loosened). The first reason keeps the historical text;
        # every other refused path is listed so the primary cause is never hidden behind whichever
        # path sorts first (a code change must not be reported as "unknown docs/...").
        extra = ""
        if len(violations) > 1:
            first, rest = violations[0], violations[1:]
            # Program/identity/integrity causes first so truncation can never hide the primary cause
            # behind alphabetically earlier documentation paths.
            rest = sorted(rest, key=lambda v: 0 if not v.startswith("Unknown concurrent path") else 1)
            shown = rest[:_MAX_REPORTED_REFUSALS]
            kinds = {}
            for v in violations:
                kinds[v.split(":", 1)[0]] = kinds.get(v.split(":", 1)[0], 0) + 1
            extra = " | %d refused paths in total (%s); %d more shown: %s" % (
                len(violations), ", ".join("%s x%d" % kv for kv in sorted(kinds.items())),
                len(shown), "; ".join(v[:110] for v in shown))
            if len(rest) > len(shown):
                extra += " | TRUNCATED: %d refused paths not listed" % (len(rest) - len(shown))
        raise UnsafeFTPublication(violations[0] + extra)
    return sorted(remote_changes)


def tree_entry(root, source, path):
    raw = git(root, "ls-tree", "-z", source, "--", path)
    if not raw:
        return None
    items = [item for item in raw.split(b"\0") if item]
    if len(items) != 1:
        raise UnsafeFTPublication("Ambiguous FT tree entry: " + path)
    header, filename = items[0].split(b"\t", 1)
    mode, kind, item_sha = header.decode("ascii").split()
    if filename.decode() != path or kind != "blob" or mode != "100644" or not SHA.fullmatch(item_sha):
        raise UnsafeFTPublication("Unsafe FT tree entry: " + path)
    return mode, item_sha


def assemble(root, remote, source, produced):
    """Use a separate Git index: never mix collector changes with FT outputs."""
    with tempfile.TemporaryDirectory(prefix="ft-git-index-") as d:
        idx = Path(d) / "index"
        env = {**os.environ, "GIT_INDEX_FILE": str(idx)}
        git(root, "read-tree", remote, env=env)
        for path in sorted(produced):
            row = tree_entry(root, source, path)
            if row is None:
                git(root, "update-index", "--force-remove", "--", path, env=env)
            else:
                mode, obj_sha = row
                git(root, "update-index", "--add", "--cacheinfo",
                    mode + "," + obj_sha + "," + path, env=env)
        newtree = git(root, "write-tree", env=env).decode().strip()
        if not SHA.fullmatch(newtree):
            raise UnsafeFTPublication("Invalid candidate Git tree")
        message = ("data(lab): publish verified FT snapshot over unrelated H1/V4 updates "
                   "[skip ci]")
        candidate = git(root, "commit-tree", newtree, "-p", remote,
                        "-m", message, env=env).decode().strip()
        if not SHA.fullmatch(candidate):
            raise UnsafeFTPublication("Invalid candidate FT commit")
        return candidate


def retriable_main_push_race(stderr: str) -> bool:
    """Only normal non-FF errors or Git's exact main-ref CAS race may retry.

    GitHub can reject a concurrent fast-forward with "cannot lock ref ... is at
    <sha> but expected <sha>" instead of a conventional non-fast-forward hint.
    The next attempt must still fetch main and re-verify all protected paths.
    """
    return outcome.classify_push_failure(stderr, "main") == outcome.CAS_REJECTED


def _receipt(status, context=None, **fields):
    doc = {"status": status, "provider_requeries": 0, **fields}
    print("FT_PUBLISH_RECEIPT", json.dumps(doc, sort_keys=True))
    if context is not None:
        context["receipt"] = doc
    return doc


# (message prefix, receipt status, reason_kind). Statuses are the ones the receipt
# report and the P0 auditor already classify; first match wins.
REFUSAL_KINDS = (
    ("Push failed for reason other than a Git race", "PUSH_REFUSED", "PUSH_REFUSED"),
    ("FT push transport failed", "RETRY_EXHAUSTED", "TRANSPORT_RETRIES_EXHAUSTED"),
    ("Remote advanced during all bounded", "RETRY_EXHAUSTED", "CAS_RETRIES_EXHAUSTED"),
    ("FT push outcome unknown", "OUTCOME_UNRESOLVED", "OUTCOME_UNRESOLVED"),
    ("FT dependency or program changed", "REFUSED", "INCOMPATIBLE_PROGRAM"),
    ("Unknown concurrent path", "REFUSED", "UNKNOWN_CONCURRENT_PATH"),
    ("H1 notification receipt invalid", "REFUSED", "H1_NOTIFICATION_RECEIPT_INVALID"),
    ("Telegram", "REFUSED", "TELEGRAM_STATE_INVALID"),
    ("H1 ", "REFUSED", "H1_ARTIFACT_INVALID"),
    ("V4/H1 journal rewritten", "REFUSED", "JOURNAL_REWRITTEN"),
    ("Immutable V6 run history rewritten", "REFUSED", "JOURNAL_REWRITTEN"),
    ("V4 source archive index changed", "REFUSED", "ARCHIVE_INDEX_CHANGED"),
    ("Concurrent report deleted", "REFUSED", "CONCURRENT_DELETION"),
    ("Remote main no longer descends", "REFUSED", "BASE_NOT_ANCESTOR"),
    ("Unsealed FT output", "REFUSED", "UNSEALED_OUTPUT"),
    ("Missing authoritative FT publication seal", "REFUSED", "SEAL_MISSING"),
)


def classify_refusal(exc):
    """(status, reason_kind) for an exception that stopped the FT publication."""
    if not isinstance(exc, UnsafeFTPublication):
        return "REFUSED", "UNEXPECTED_ERROR:" + type(exc).__name__
    message = str(exc)
    for prefix, status, kind in REFUSAL_KINDS:
        if message.startswith(prefix):
            return status, kind
    return "REFUSED", "INTEGRITY_REFUSAL"


def write_bundle(root, context, bundle):
    """Verified Git bundle of the unpublished FT source commit (evidence only)."""
    import hashlib
    source, base = context.get("source_commit"), context.get("base")
    if not source or not SHA.fullmatch(str(source)):
        return {"bundle": None, "bundle_error": "NO_SOURCE_COMMIT"}
    ref = "refs/ft-unpublished/source"
    try:
        git(root, "update-ref", ref, source)
        spec = [ref] if not base or base == source else ["^" + base, ref]
        git(root, "bundle", "create", str(bundle), *spec)
        git(root, "bundle", "verify", str(bundle))
        digest = hashlib.sha256(Path(bundle).read_bytes()).hexdigest()
        return {"bundle": str(bundle), "bundle_sha256": digest, "bundle_ref": ref,
                "bundle_commit": source}
    except Exception as exc:  # noqa: BLE001 - evidence is best effort, refusal stands
        return {"bundle": None, "bundle_error": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    finally:
        run(root, "update-ref", "-d", ref, check=False)


def refusal_receipt(exc, context, *, root=None, bundle=None, env=None):
    """Emit (and return) the receipt of a refused/failed FT publication."""
    env = os.environ if env is None else env
    status, kind = classify_refusal(exc)
    fields = {k: context.get(k) for k in ("attempt", "base", "remote", "source_commit",
                                          "produced_files", "sealed_files",
                                          "transport_failures") if context.get(k) is not None}
    fields.update(reason=str(exc)[:500], reason_kind=kind, published_commit=None,
                  publication="NOT_PUBLISHED", run_id=env.get("GITHUB_RUN_ID"),
                  telegram_requests=0)
    if kind in {"INCOMPATIBLE_PROGRAM", "BASE_NOT_ANCESTOR"}:
        fields["recovery_action"] = "RECONCILE_FROM_CURRENT_MAIN"
    elif status == "OUTCOME_UNRESOLVED":
        fields["recovery_action"] = "VERIFY_REMOTE_BEFORE_RETRY"
    else:
        fields["recovery_action"] = "REVIEW_REFUSAL"
    if bundle is not None and root is not None:
        fields.update(write_bundle(root, context, bundle))
    return _receipt(status, context, **fields)


def publish(root, *, base, manifest, baseline, max_attempts=6, max_transport_failures=3,
            sleep=None, context=None):
    """Publish the sealed FT commit; idempotent across transport errors and crashes.

    Push outcomes: PUBLISHED, CAS_REJECTED (retry after full revalidation),
    UNCERTAIN/TRANSIENT (read the remote first; recognise an accepted commit,
    otherwise a bounded, fully revalidated retry), AUTH (abort), concurrent
    incompatible change (abort via allowed_remote_changes).
    """
    import time as _time
    sleep = sleep or _time.sleep
    context = {} if context is None else context
    context["base"] = base
    root, manifest, baseline = Path(root), Path(manifest), Path(baseline)
    if (not SHA.fullmatch(base) or not 1 <= max_attempts <= 10
            or not 0 <= max_transport_failures <= 5):
        raise UnsafeFTPublication("Invalid original run base or bounded retry count")
    source = sha(root, "HEAD")
    context["source_commit"] = source
    if sha(root, "HEAD^") != base:
        raise UnsafeFTPublication("FT source commit is not based on the pinned checkout")
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise UnsafeFTPublication("FT checkout is not clean")
    proof = json.loads(manifest.read_text(encoding="utf-8"))
    if proof.get("pipeline") != "ft" or not proof.get("segmented"):
        raise UnsafeFTPublication("Missing authoritative FT publication seal")
    sealed = set(proof["sha256"])
    produced = changed_paths(root, base, source)
    context.update(sealed_files=len(sealed), produced_files=len(produced))
    live_produced = {name for name in produced
                     if tree_entry(root, source, name) is not None}
    deleted = produced - live_produced
    # Old immutable generations disappear from HEAD once no longer reachable
    # through CURRENT/PREVIOUS. The segmented Git seal already proves those
    # are unreachable; deleted files are *not* live members in its hashes.
    retired = re.compile(
        r"data/lab/discovery-segmented/[a-f0-9]{64}/"
        r"(?:manifest\.json|legacy\.json\.gz|state-[0-9]{4}\.json)\Z"
    )
    if (not live_produced or not live_produced <= sealed
            or any(not retired.fullmatch(name) for name in deleted)):
        raise UnsafeFTPublication(
            "Unsealed FT output changes or unsafe deletions: "
            + repr(sorted((live_produced - sealed)
                          | {name for name in deleted if not retired.fullmatch(name)})[:8]))
    # The source payload is completely valid and immutable from this point on.
    publication_guard.verify(manifest)
    verify_files(baseline, root / "data/lab/ft-ledger.json")
    last_remote = None
    transport_failures = 0
    for attempt in range(1, max_attempts+1):
        git(root, "fetch", "--no-tags", "origin", "main")
        remote = sha(root, "FETCH_HEAD")
        context.update(attempt=attempt, remote=remote, transport_failures=transport_failures)
        if run(root, "merge-base", "--is-ancestor", base, remote, check=False).returncode:
            raise UnsafeFTPublication("Remote main no longer descends from the FT input base")
        # Idempotence: an earlier attempt (lost response, crash after push, or a
        # concurrent identical publisher) already put these exact FT bytes on main.
        if remote != base and outcome.same_paths(root, source, remote, produced):
            git(root, "reset", "--hard", remote)
            _receipt("ALREADY_PUBLISHED_EQUIVALENT", context, attempt=attempt, remote=remote,
                     source_commit=source, transport_failures=transport_failures)
            return remote
        allowed = allowed_remote_changes(root, base, remote, sealed, produced)
        if remote == base:
            candidate = source
        else:
            candidate = assemble(root, remote, source, produced)
        # Worktree reset is local only. A failing proof can NEVER be pushed.
        git(root, "reset", "--hard", candidate)
        publication_guard.verify(manifest)
        verify_files(baseline, root / "data/lab/ft-ledger.json")
        discovery_verify(["verify", "--root", str(root)])
        result = run(root, "push", "origin", "HEAD:refs/heads/main", check=False)
        if result.returncode == 0:
            print("FT_ATOMIC_PUBLISHED", json.dumps({
                "attempt": attempt, "remote_base": remote,
                "source_commit": source, "published_commit": candidate,
                "unrelated_paths": len(allowed), "sealed_files": len(sealed),
                "provider_requeries": 0}, sort_keys=True))
            _receipt("PUBLISHED", context, attempt=attempt, published_commit=candidate,
                     remote_base=remote, source_commit=source)
            return candidate
        last_remote = remote
        err = result.stderr.decode("utf-8", "replace")
        kind = outcome.classify_push_failure(err, "main")
        if kind == outcome.CAS_REJECTED:
            print("FT_REMOTE_RACE_RECHECK", attempt, "after", last_remote)
            continue
        if kind in (outcome.UNCERTAIN, outcome.TRANSIENT):
            transport_failures += 1
            context["transport_failures"] = transport_failures
            state, now = outcome.probe_remote(root, candidate, "main", sleep=sleep)
            print("FT_PUSH_OUTCOME_PROBE", json.dumps({
                "attempt": attempt, "kind": kind, "candidate": candidate,
                "remote_before_push": remote, "remote_after": now, "state": state},
                sort_keys=True))
            if state == outcome.PUBLISHED:
                _receipt("PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR", context, attempt=attempt,
                         published_commit=candidate, remote_after=now, source_commit=source)
                return candidate
            if state == outcome.UNRESOLVED:
                raise UnsafeFTPublication(
                    "FT push outcome unknown and remote unreadable; not retried: " + err[-200:])
            if transport_failures > max_transport_failures:
                raise UnsafeFTPublication(
                    "FT push transport failed %d times; commit not on remote: %s"
                    % (transport_failures, err[-200:]))
            sleep(outcome.transport_backoff(transport_failures))
            continue
        # Auth, protection, hooks and unknown errors are never silently hidden. An unknown
        # refusal is still checked against the remote once (read only) before it is reported.
        if kind != outcome.AUTH:
            state, now = outcome.probe_remote(root, candidate, "main", sleep=sleep)
            if state == outcome.PUBLISHED:
                _receipt("PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR", context, attempt=attempt,
                         published_commit=candidate, remote_after=now, source_commit=source)
                return candidate
        raise UnsafeFTPublication("Push failed for reason other than a Git race: " + err[-300:])
    raise UnsafeFTPublication("Remote advanced during all bounded FT publication attempts")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=6)
    parser.add_argument("--receipt", type=Path, help="also write the receipt JSON here")
    parser.add_argument("--bundle", type=Path,
                        help="on refusal, write a verified Git bundle of the unpublished FT commit")
    args = parser.parse_args(argv)
    context = {"base": args.base}
    try:
        publish(args.root, base=args.base, manifest=args.manifest,
                baseline=args.baseline, max_attempts=args.max_attempts, context=context)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        doc = refusal_receipt(exc, context, root=args.root, bundle=args.bundle)
        print("::error title=FT_PUBLISH_%s::%s %s" % (doc["status"], doc["reason_kind"],
                                                      doc["reason"].replace("\n", " ")[:300]))
        if args.receipt:
            args.receipt.write_text(json.dumps(doc, sort_keys=True) + "\n", encoding="utf-8")
        raise
    if args.receipt and context.get("receipt"):
        args.receipt.write_text(json.dumps(context["receipt"], sort_keys=True) + "\n",
                                encoding="utf-8")


if __name__ == "__main__":
    main()

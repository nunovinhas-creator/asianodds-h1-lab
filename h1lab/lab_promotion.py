"""Conservative LAB->H1 score transport. Does not change H1 signal or ticket rules.

Only independently recorded LAB FINAL scores for *identical* prospective H1
fixtures are eligible. Never considers unverified, changed, future, conflicting,
or provider-error results. Existing H1 results are strictly immutable.
"""
from __future__ import annotations

import json
import ipaddress
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .cli import ROOT, read_state
from .core import dump_json
from .lab_reviewed_aliases import reviewed_provider_pair
from .lab_sportscore import source_order_conflict
from .results import AUDIT, RESULTS, read_audit, read_rows, write_rows

LEDGER = ROOT / "data/lab/ft-ledger.json"
GRACE = timedelta(hours=3)
ALLOWED_EVIDENCE = {
    "bsd", "thesportsdb", "espn", "sportscore", "api_football",
    "goal", "openfoot", "fotmob", "reviewed_public",
}


def _utc(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.astimezone(timezone.utc) if date.tzinfo else None
    except ValueError:
        return None


def _safe_source(value):
    if not isinstance(value, str) or not 0 < len(value) <= 512:
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return False
        if host.lower() in {"localhost", "127.0.0.1"} or host.endswith(".local"):
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        return True
    except ValueError:
        return False


def candidate(signal, row, now):
    """Return (CSV row, explanation) without side effects."""
    if not isinstance(signal, dict) or not isinstance(row, dict):
        return None, "invalid_identity"
    key = signal.get("match_key")
    if not isinstance(key, str) or not key or row.get("status") != "FINAL":
        return None, "not_final"
    if any(not isinstance(signal.get(k), str) or
           row.get(k) != signal.get(k) for k in ("home", "away", "kickoff_utc")):
        return None, "identity_mismatch"
    kickoff = _utc(signal["kickoff_utc"])
    if kickoff is None or now < kickoff + GRACE:
        return None, "not_due"
    result = row.get("result")
    if not isinstance(result, dict):
        return None, "missing_lab_result"
    home, away, source = (result.get("home_goals"), result.get("away_goals"),
                          result.get("source"))
    if type(home) is not int or type(away) is not int or not (0 <= home <= 30 and 0 <= away <= 30):
        return None, "invalid_score"
    if not _safe_source(source):
        return None, "untrusted_result_url"
    evidence = result.get("evidence")
    if (not isinstance(evidence, str) or not evidence or
            any(name not in ALLOWED_EVIDENCE for name in evidence.split("_and_")
                if not name.endswith("_only"))):
        # Normal evidence formats: "bsd_only", "goal_and_openfoot",
        # "reviewed_public_only". Validate below with exact recognized names.
        return None, "unrecognized_evidence"
    providers = evidence[:-5].split("_and_") if evidence.endswith("_only") else evidence.split("_and_")
    if not providers or any(p not in ALLOWED_EVIDENCE for p in providers):
        return None, "unrecognized_evidence"
    if "reviewed_public" in providers:
        # Manual documentary evidence must retain its second corroborating URL.
        review = (row.get("reviewed_public_resolution") or
                  row.get("source_order_resolution") or {})
        refs = review.get("corroboration_urls")
        if (not isinstance(refs, list) or len(refs) != 2 or
                source not in refs or not all(_safe_source(v) for v in refs)):
            return None, "missing_independent_documentary_proof"
    if "sportscore" in providers:
        pair = reviewed_provider_pair(signal) or (signal["home"], signal["away"])
        if source_order_conflict(source, *pair):
            return None, "sportscore_source_order_conflict"
    return {"match_key": key, "status": "final", "home_goals": home,
            "away_goals": away, "source": source}, "verified_lab_final"


def propose(state, ledger, existing_rows, now):
    """Immutable planning: only H1 singles, no edits to picks or tickets."""
    if (not isinstance(state, dict) or not isinstance(state.get("signals"), list) or
            not isinstance(ledger, dict) or not isinstance(ledger.get("matches"), dict)):
        raise ValueError("Invalid H1 or LAB ledger")
    signals = state["signals"]
    keys = Counter(s.get("match_key") for s in signals if isinstance(s, dict))
    existing = {r.get("match_key"): r for r in existing_rows}
    proposed = []
    rejected = Counter()
    for s in signals:
        if not isinstance(s, dict) or not isinstance(s.get("match_key"), str):
            rejected["invalid_signal"] += 1
            continue
        key = s["match_key"]
        if keys[key] != 1:
            rejected["duplicate_signal_identity"] += 1
            continue
        lab_row = ledger["matches"].get(key)
        if key in existing:
            old = existing[key]
            if isinstance(lab_row, dict) and lab_row.get("status") == "FINAL":
                test, reason = candidate(s, lab_row, now)
                if test and (str(old.get("home_goals")), str(old.get("away_goals"))) != (
                        str(test["home_goals"]), str(test["away_goals"])):
                    rejected["existing_h1_ft_disagrees"] += 1
            continue
        if lab_row is None:
            rejected["missing_lab_row"] += 1
            continue
        item, reason = candidate(s, lab_row, now)
        if item is None:
            rejected[reason] += 1
        else:
            proposed.append((item, lab_row["result"]["evidence"]))
    return proposed, dict(sorted(rejected.items()))


def sync(now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = read_state()
    if not LEDGER.is_file():
        print("H1_LAB_BRIDGE_NO_LEDGER: no results imported")
        return 0
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    rows = read_rows()
    planned, rejected = propose(state, ledger, rows, now)
    if planned:
        audit = read_audit()
        rows.extend(item for item, _ in planned)
        for item, evidence in planned:
            audit[item["match_key"]] = {
                "checked_at": now.isoformat(timespec="seconds"),
                "status": "settled",
                "reason": "verified_lab_final",
                "lab_evidence": evidence,
                "source": item["source"],
                "lab_ledger_updated_at": ledger.get("last_updated_at"),
            }
        write_rows(rows)
        dump_json(AUDIT, audit)
    print("H1_LAB_BRIDGE", "imported", len(planned),
          "total_csv", len(rows), "rejected", rejected,
          "ledger_at", ledger.get("last_updated_at"))
    return len(planned)


if __name__ == "__main__":
    sync()

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
from .lab_ft_attestations import REQUIRED as ATTESTATION_FIELDS, seal as seal_attestation, _source_ok as attestation_source_ok
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



def dual_evidence_rejection(signal, row, now, journal):
    """None when dual-provider FT is proven by immutable attestations, else a specific reason.

    Diagnostic split of the former boolean check: every reason still means "reject".
    """
    if not isinstance(journal, dict) or journal.get("schema_version") != 1:
        return "attestation_journal_missing_or_unsupported"
    key = signal["match_key"]
    if key in (journal.get("conflicts") or {}):
        return "attestation_conflict_recorded"
    proof = row.get("dual_provider_corroboration")
    sources = row.get("verified_provider_sources")
    claims = (journal.get("records") or {}).get(key)
    if not all(isinstance(x, dict) for x in (proof, sources, claims)):
        return "proof_claims_or_sources_missing"
    providers = proof.get("providers")
    if (proof.get("method") != "TWO_STRONG_PROVIDER_IDS_SAME_REGULATION_FT"
            or proof.get("scores_agree") is not True
            or not isinstance(providers, list)
            or not 2 <= len(providers) <= 3
            or len(set(providers)) != len(providers)
            or providers != sorted(providers)
            or not set(providers).issubset({"api_football", "goal", "openfoot"})):
        return "proof_method_or_provider_set_invalid"
    digests = proof.get("attestation_sha256")
    times = proof.get("first_observed_at_utc")
    if not isinstance(digests, dict) or not isinstance(times, dict):
        return "proof_digests_or_times_missing"
    result = row["result"]
    kickoff = _utc(signal["kickoff_utc"])
    if kickoff is None:
        return "kickoff_invalid"
    proof_sources = set()
    for provider in providers:
        claim = claims.get(provider)
        attached = sources.get(provider)
        if not isinstance(claim, dict) or not isinstance(attached, dict):
            return "provider_claim_missing"
        if set(claim) != {*ATTESTATION_FIELDS, "sha256"}:
            return "claim_fields_invalid"
        try:
            if seal_attestation(claim) != claim:
                return "claim_seal_invalid"
        except (TypeError, ValueError, KeyError):
            return "claim_seal_invalid"
        if (claim["match_key"] != key or claim["provider"] != provider
                or claim["sha256"] != digests.get(provider)
                or claim["observed_at_utc"] != times.get(provider)
                or claim["source"] != attached.get("source")
                or attached.get("identity_match") != "DUAL_STRONG_CONSENSUS"
                or not attestation_source_ok(claim)
                or (claim["home_goals"], claim["away_goals"]) !=
                   (result["home_goals"], result["away_goals"])):
            return "claim_binding_mismatch"
        observed, provider_ko = _utc(claim["observed_at_utc"]), _utc(claim["kickoff_utc"])
        if observed is None or provider_ko is None:
            return "provider_time_invalid"
        if abs((provider_ko - kickoff).total_seconds()) > 300:
            return "provider_kickoff_differs_more_than_5min"
        if not kickoff + timedelta(minutes=90) <= observed <= now:
            return "observed_before_kickoff_plus_90min_or_in_the_future"
        if observed > kickoff + timedelta(hours=24):
            return "observed_after_24h_window"
        proof_sources.add(claim["source"])
    return None if result["source"] in proof_sources else "result_source_not_in_attested_sources"


def _confirmed_dual_evidence(signal, row, now, journal):
    """Prove legacy dual-provider FT from immutable attestations, not a label."""
    return dual_evidence_rejection(signal, row, now, journal) is None


def candidate(signal, row, now, attestations=None):
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
    if evidence == "dual_provider_only":
        why = dual_evidence_rejection(signal, row, now, attestations)
        if why is not None:
            # Same rejection as before; only the label is now diagnostic.
            return None, "dual_provider_evidence_rejected:" + why
        return {"match_key": key, "status": "final", "home_goals": home,
                "away_goals": away, "source": source}, "verified_lab_final"
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


def propose(state, ledger, existing_rows, now, attestations=None):
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
                test, reason = candidate(s, lab_row, now, attestations)
                if test and (str(old.get("home_goals")), str(old.get("away_goals"))) != (
                        str(test["home_goals"]), str(test["away_goals"])):
                    rejected["existing_h1_ft_disagrees"] += 1
            continue
        if lab_row is None:
            rejected["missing_lab_row"] += 1
            continue
        item, reason = candidate(s, lab_row, now, attestations)
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
    attestations_path = LEDGER.with_name('ft-provider-attestations.json')
    attestations = (json.loads(attestations_path.read_text(encoding='utf-8'))
                    if attestations_path.is_file() else None)
    planned, rejected = propose(state, ledger, rows, now, attestations)
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

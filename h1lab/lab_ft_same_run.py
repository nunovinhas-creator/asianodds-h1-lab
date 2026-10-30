"""One bounded offline replay of newly discovered same-run provider identities.

Run AFTER the normal LAB provider calls, BEFORE persisting FT attestations.
Never invokes a provider adapter, guesses aliases or promotes fuzzy evidence.
"""
from __future__ import annotations

from .lab_identity_review import build_queue
from .lab_ft_dual_consensus import TwoProviderConsensus
from .lab_results import reconcile

PROVIDERS = frozenset(("api_football", "goal", "openfoot"))
REPORT_FIELDS = ("status_counts", "timing_counts", "final_recorded",
                 "unverified", "last_updated_at", "games",
                 "displayed_matches", "matches_omitted_from_display",
                 "source_order_audit")


def settle_new_cached_pairs(state, v4rows, ledger, report, now, *,
                            previous_review, api_football, goal, openfoot,
                            bsd_cache=None, sportscore_cache=None,
                            prior_attestations=None, score_hold_keys=(),
                            source_version=11, priority_hints=None):
    """Return (ledger, report, secondary_consensus).

    Only newly discovered STRONG identities are replayed. Existing STRONG
    identities were already handled by the first pass, including its bounded
    postcheck. A replay uses max_checks=0 and cannot call a provider.
    """
    caches = {
        "api_football": api_football.days,
        "goal": goal.cache,
        "openfoot": openfoot.days,
        "bsd": bsd_cache or {},
        "sportscore": sportscore_cache or {},
    }
    fresh_review = build_queue(ledger, now, caches, previous=previous_review)
    old_strong = set()
    for item in (previous_review.get("games", [])
                 if isinstance(previous_review, dict) else []):
        if not isinstance(item, dict):
            continue
        sources = {c.get("provider") for c in item.get("candidates", [])
                   if isinstance(c, dict) and c.get("provider") in PROVIDERS
                   and c.get("match_strength") == "STRONG"
                   and c.get("orientation") == "SAME_ORDER"}
        if len(sources) >= 2:
            old_strong.add(item.get("match_key"))
    new_keys = []
    for item in fresh_review["games"]:
        key = item["match_key"]
        row = ledger["matches"].get(key)
        if (key in old_strong or not isinstance(row, dict)
                or row.get("status") not in ("PENDING", "PROVIDER_ERROR")
                or item.get("possible_duplicates")):
            continue
        sources = {c.get("provider") for c in item.get("candidates", [])
                   if isinstance(c, dict) and c.get("provider") in PROVIDERS
                   and c.get("match_strength") == "STRONG"
                   and c.get("orientation") == "SAME_ORDER"}
        if len(sources) >= 2:
            new_keys.append(key)
    secondary = TwoProviderConsensus(
        review=fresh_review, matches=ledger["matches"], goal=goal,
        api_football=api_football, openfoot=openfoot, now=now,
        prior_attestations=prior_attestations,
        score_hold_keys=score_hold_keys)
    if new_keys:
        # The only lookup supplied to the replay is the pure cached dual
        # verifier. max_checks=0 means neither adapter stub is invoked.
        def no_poll(_):
            raise AssertionError("offline postcheck attempted network-backed adapter")
        updated, refresh, attempts = reconcile(
            state, v4rows, ledger, now=now,
            bsd_lookup=no_poll, tsdb_lookup=no_poll, max_checks=0,
            dual_lookup=secondary.lookup, dual_postcheck_keys=new_keys,
            evidence_retry=True, lookup_source_version=source_version,
            priority_hints=priority_hints)
        if attempts:
            raise AssertionError("offline postcheck consumed provider budget")
        for field in REPORT_FIELDS:
            report[field] = refresh[field]
        ledger = updated
        for metric in ("dual_postcheck_scanned", "dual_postcheck_confirmed",
                       "dual_postcheck_conflicts"):
            report["ft_queue"][metric] = (
                report["ft_queue"].get(metric, 0)
                + refresh["ft_queue"].get(metric, 0))
    report["ft_queue"]["same_run_cached_postcheck"] = {
        "eligible_new_strong_pairs": len(new_keys),
        "verified": len(secondary.confirmations),
        "score_conflicts": sum(
            item.get("status") == "SCORE_CONFLICT"
            for item in secondary.outcomes.values()),
        "adapter_http_requests": 0,
        "scope": "new STRONG review pairs on COMPLETE already-fetched day lists",
    }
    return ledger, report, secondary

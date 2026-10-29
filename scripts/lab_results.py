"""Scheduled LAB-only result collector. No H1 mutations, no channel text."""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone
from pathlib import Path

from h1lab.lab_results import reconcile
from h1lab.lab_ft_backlog import audit as audit_ft_backlog
from h1lab.v6_ft_events import priority_hints as v6_priority_hints
from h1lab.lab_espn import ESPNResults
from h1lab.lab_sportscore import SportScoreResults
from h1lab.lab_monte_bsd import MonteBSDCrosswalk
from h1lab.lab_bsd_priority import lookup_bsd_monte_first
from h1lab.lab_bsd_search import BSDDateFallback, summary as bsd_date_summary
from h1lab.lab_ft_diagnostics import coverage_diagnostics
from h1lab.lab_identity_review import build_queue
from h1lab.lab_ft_rotation import choose_days, advance
from h1lab.lab_ft_evidence import day_fingerprint
from h1lab.lab_ft_day_identity import build_index
from h1lab.lab_ft_crosswalk import build_registry
from h1lab.lab_goal_id_probe import plan_goal_id
from h1lab.lab_goal_reviewed import plan_reviewed_goal_id
from h1lab.lab_ft_dual_consensus import TwoProviderConsensus
from h1lab.lab_ft_attestations import merge as merge_attestations, empty as empty_attestations
from h1lab.lab_fotmob import FotMobResults
from h1lab.lab_api_football import APIFootballResults
from h1lab.lab_api_football_reviewed import plan_reviewed_ids
from h1lab.lab_api_football_access import evolve_access, restriction_for_fixture_id
from h1lab.lab_goal import GoalResults
from h1lab.lab_openfoot import OpenFootResults

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data/lab/ft-ledger.json"
FT_PROVIDER_ATTESTATIONS = ROOT / "data/lab/ft-provider-attestations.json"
REPORT = ROOT / "docs/lab/ft-results.json"
API_AUDIT = ROOT / "data/lab/ft-api-audit.json"
BACKLOG = ROOT / "docs/lab/ft-backlog.json"
IDENTITY_REVIEW = ROOT / "docs/lab/ft-identity-review.json"
REVIEWED_API_IDS = ROOT / "data/lab/ft-api-football-reviewed.json"
REVIEWED_GOAL_IDS = ROOT / "data/lab/ft-goal-reviewed.json"
REVIEWED_API_ID_DECISIONS = ROOT / "docs/lab/ft-api-football-review-decisions.json"
API_FOOTBALL_DAY_INDEX = ROOT / "data/lab/ft-api-football-day-index.json"
DAY_ROTATION = ROOT / "data/lab/ft-provider-day-rotation.json"
PROVIDER_IDENTITY = ROOT / "data/lab/ft-provider-identity.json"
PROVIDER_IDENTITY_PUBLIC = ROOT / "docs/lab/ft-provider-identity.json"


def read_v4():
    rows = []
    for path in sorted((ROOT / "data/lab").glob("markets-*.jsonl")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("Invalid V4 row")
                rows.append(item)
    return rows


def lookup_bsd(signal):
    if not os.environ.get("BSD_API_KEY", "").strip():
        return None, "bsd_not_configured"
    from h1lab.bsd import find_result
    return find_result(signal)


class PacedTSDB:
    """Protect free-tier throughput (<30 requests/minute) and record 429s."""
    def __init__(self, interval=2.3):
        self.interval = interval
        self.last = None
        self.rate_limited = False
        self.counts = Counter()

    def lookup(self, signal):
        if self.rate_limited:
            self.counts["suppressed_after_429"] += 1
            return None, "tsdb_limited_this_run"
        if self.last is not None:
            gap = time.monotonic() - self.last
            if gap < self.interval:
                time.sleep(self.interval - gap)
        self.last = time.monotonic()
        self.counts["requested"] += 1
        from h1lab.results import api_events, choose_result
        try:
            found, reason = choose_result(signal, api_events(signal))
        except HTTPError as exc:
            if exc.code == 429:
                self.rate_limited = True
                self.counts["http_429"] += 1
                return None, "tsdb_http_429"
            self.counts["http_error"] += 1
            return None, "tsdb_http_error"
        except (OSError, ValueError, TimeoutError, URLError):
            self.counts["unavailable"] += 1
            return None, "tsdb_unavailable"
        self.counts[reason] += 1
        return found, reason


def competitions_by_key(alerts):
    observed = {}
    conflicted = set()
    for item in alerts:
        if not isinstance(item, dict):
            continue
        key, comp = item.get("match_key"), item.get("competition")
        if not isinstance(key, str) or not isinstance(comp, str) or not comp:
            continue
        if key in observed and observed[key] != comp:
            conflicted.add(key)
        observed[key] = comp
    return {key:comp for key,comp in observed.items() if key not in conflicted}


def write_if_changed(path, data):
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == payload:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    return True


def backlog_recovery_enabled(env):
    return (env.get("LAB_FT_BACKLOG_ONCE_20261028") == "true"
            and env.get("GITHUB_WORKFLOW") ==
            "Lab - Reconcile FT for all observed matches"
            and env.get("GITHUB_EVENT_NAME") == "push"
            and env.get("GITHUB_REF") == "refs/heads/main")


def main():
    state = json.loads((ROOT / "data/state.json").read_text(encoding="utf-8"))
    existing = (json.loads(LEDGER.read_text(encoding="utf-8"))
                if LEDGER.exists() else {"schema_version": 1, "matches": {}})
    checks = int(os.environ.get("LAB_RESULTS_MAX_CHECKS", "30"))
    now = datetime.now(timezone.utc)
    # Read only frozen, pre-kickoff V6 captures; never contact an API here.
    # If scientific memory is unavailable, revert to the original FT queue.
    try:
        research_hints = v6_priority_hints(ROOT)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        research_hints = {}
        print("V6_FT_PRIORITY_FALLBACK", type(exc).__name__)
    bsd_finder = BSDDateFallback(
        token=os.environ.get("BSD_API_KEY", ""),
        max_days=int(os.environ.get("LAB_BSD_DATE_MAX_DAYS", "3")),
        max_pages=int(os.environ.get("LAB_BSD_DATE_MAX_PAGES", "3")),
    )
    monte = MonteBSDCrosswalk(
        token=os.environ.get("BSD_API_KEY", ""), max_event_requests=12)
    def bsd_with_monte(signal):
        # DIRECT BSD IDs already archived by Monte-Carlos take precedence.
        # Search by team/date only when no safe archived BSD ID exists.
        # The archived score is NEVER trusted; the ID is revalidated with BSD.
        return lookup_bsd_monte_first(signal, monte, bsd_finder)

    tsdb = PacedTSDB()
    fotmob_enabled = os.environ.get('LAB_FOTMOB_LICENSED', '0') == '1'
    fotmob = FotMobResults(max_days=3 if fotmob_enabled else 0)
    # API-Football quota is enforced by persisted day rotation (90/day).
    # Do NOT gate by UTC hour: watchdog runs are not synchronized to cron.
    api_key = os.environ.get("API_FOOTBALL_KEY", "")
    # Explicitly scoped one-shot GH workflow for the secret activation check.
    # Never lets an ordinary push, H1 cron, or local run bypass the free quota.
    one_shot = (os.environ.get("LAB_API_FOOTBALL_ONE_SHOT") == "true"
                and os.environ.get("GITHUB_WORKFLOW") ==
                "LAB - API-Football one-time activation check")
    # Exactly one self-removing recovery workflow may bypass the normal FT
    # cooldown. Neither regular pushes nor manual local runs may do so.
    recovery_once = (os.environ.get("LAB_FT_RECOVERY_ONCE") == "true"
                     and os.environ.get("GITHUB_WORKFLOW") ==
                     "LAB - One-time FT recovery 2026-10-28"
                     and os.environ.get("GITHUB_EVENT_NAME") == "push")
    # A tagged main merge explicitly authorizes exactly one bounded
    # recovery run. Ordinary push/manual executions cannot bypass cooldown.
    backlog_once = backlog_recovery_enabled(os.environ)
    recovery_once = recovery_once or backlog_once
    live_context = (os.environ.get("GITHUB_WORKFLOW") ==
                    "Lab - Reconcile FT for all observed matches" and
                    os.environ.get("GITHUB_EVENT_NAME") in ("schedule", "workflow_dispatch"))
    is_scheduled = (os.environ.get("LAB_API_FOOTBALL_SCHEDULED") == "true"
                    or live_context or recovery_once)
    api_football_poll = bool(api_key.strip()) and (one_shot or is_scheduled)
    api_football = APIFootballResults(key=api_key,
                                      max_days=3 if api_football_poll else 0)
    one_shot_new = (os.environ.get("LAB_NEW_FT_ONE_SHOT") == "true"
                    and os.environ.get("GITHUB_WORKFLOW") ==
                    "LAB - GOAL and OpenFoot one-time FT activation")
    # 48 scheduled FT runs/day * 2 dates = at most 96 GOAL requests/day
    # and 96 OpenFoot requests/day (~2,976/month for 31 days).
    goal_key = os.environ.get("GOAL_API_KEY", "")
    openfoot_key = os.environ.get("OPENFOOT_API_KEY", "")
    goal_enabled = bool(goal_key.strip()) and (is_scheduled or one_shot_new)
    # Ordinary push merges must NEVER consume FT attempts, even BSD/TSDB.
    if os.environ.get("GITHUB_EVENT_NAME") == "push" and not recovery_once:
        checks = 0
    openfoot_enabled = bool(openfoot_key.strip()) and (is_scheduled or one_shot_new)
    goal = GoalResults(key=goal_key, max_days=2 if goal_enabled else 0)
    openfoot = OpenFootResults(key=openfoot_key, max_days=2 if openfoot_enabled else 0)

    # Dry-run the EXACT current FT selection, with zero HTTP calls and no writes.
    # Date budgets are then allocated by least-recently-served fixture day,
    # instead of being monopolised by whichever game was sorted first.
    historical_days = (json.loads(DAY_ROTATION.read_text(encoding="utf-8"))
                       if DAY_ROTATION.exists()
                       else {"schema_version": 1, "providers": {}})
    history_access = historical_days.get("api_football_history_access",
                                          {"schema_version": 1, "confirmed_restrictions": {}})
    catalog_v4 = read_v4()
    # An approved fixture receives one immediate priority slot only when
    # every persisted human-approval and full source-day identity gate has
    # ALREADY passed. No provider HTTP call is made for this dry run.
    approved = (json.loads(REVIEWED_API_IDS.read_text(encoding="utf-8"))
                if REVIEWED_API_IDS.exists()
                else {"schema_version": 1, "pairs": {}})
    previous_review = (json.loads(IDENTITY_REVIEW.read_text(encoding="utf-8"))
                       if IDENTITY_REVIEW.exists() else {})
    previous_day_index = (json.loads(API_FOOTBALL_DAY_INDEX.read_text(encoding="utf-8"))
                          if API_FOOTBALL_DAY_INDEX.exists()
                          else {"schema_version": 1, "days": {}})
    confirmed_ids = (json.loads(PROVIDER_IDENTITY.read_text(encoding="utf-8"))
                     if PROVIDER_IDENTITY.exists()
                     else {"schema_version": 1, "entries": {}})
    approved_due = set(plan_reviewed_ids(
        approved.get("pairs", {}), existing["matches"], previous_review,
        approved, now, day_index=previous_day_index,
        confirmed_registry=confirmed_ids)) if api_football_poll else set()
    # Date-list provider restrictions are NOT evidence that single fixture ID
    # lookups are blocked. Only endpoint-specific evidence could suspend ID
    # calls, while preserving every existing approval and cooldown.
    blocked_approved = {
        key: restriction_for_fixture_id(history_access, row.get("kickoff_utc", "")[:10], now)
        for key, row in approved.get("pairs", {}).items()
        if isinstance(row, dict)
    }
    approved_due -= {key for key, why in blocked_approved.items() if why}
    _preview_ledger, preview, _ = reconcile(
        state, catalog_v4, existing, now=now,
        bsd_lookup=lambda unused: (None, "preview_only"),
        tsdb_lookup=lambda unused: (None, "preview_only"),
        lookup_source_version=(11 if goal_enabled or openfoot_enabled else
                               10 if api_football_poll else None),
        max_checks=0, force_recheck=recovery_once,
        priority_hints=research_hints, evidence_retry=True,
        approved_rechecks=approved_due)
    preview_keys = preview["ft_queue"]["deferred_keys"][:checks]
    active = set()
    if goal_enabled: active.add("goal")
    if openfoot_enabled: active.add("openfoot")
    if api_football_poll: active.add("api_football")
    rotation = choose_days(preview_keys, _preview_ledger["matches"],
                           historical_days, now, active)
    # GOAL ID lookups are quota-neutral substitutions, never extra requests.
    # Identity-only human-reviewed GOAL IDs require independent API approval;
    # their score gate cannot produce FINAL while public sources disagree.
    goal_approved = (json.loads(REVIEWED_GOAL_IDS.read_text(encoding="utf-8"))
                     if REVIEWED_GOAL_IDS.exists()
                     else {"schema_version": 1, "pairs": {}})
    goal_today = (historical_days.get("usage", {}).get("goal", {})
                  .get(now.date().isoformat(), 0))
    # Endpoint budgets are independent. A fixture-ID probe may replace a
    # date request, but does NOT need a date request to be eligible.
    # This prevents a successful COMPLETE day list's adaptive cooldown from
    # indefinitely starving a reviewed ID once the game itself is due.
    # If 1 date is selected, reserve 2 daily slots (1 date + 1 ID);
    # if no date is eligible, reserve just 1 slot (ID only).
    goal_id_slot = goal_enabled and (
        goal_today <= (78 if rotation["goal"] else 79))
    goal_targets = (plan_goal_id(preview_keys, _preview_ledger["matches"],
                                 previous_review, now)
                    if goal_id_slot else {})
    goal_review_decisions = {}
    reviewed_goal_targets = (plan_reviewed_goal_id(
        preview_keys, _preview_ledger["matches"], previous_review,
        goal_approved, approved, now, decisions=goal_review_decisions)
        if goal_id_slot else {})
    if reviewed_goal_targets:
        # At most one target per run. It supersedes ordinary GOAL probes,
        # without consuming a third request or bypassing queue cooldowns.
        goal_targets = {key: row["provider_fixture_id"]
                        for key, row in reviewed_goal_targets.items()}
        goal.reviewed_targets = reviewed_goal_targets
    if goal_targets:
        goal.target_ids = goal_targets
        goal.max_days = 1
        rotation["goal"] = rotation["goal"][:1]
    # No IDs are invented or promoted from fuzzy suggestions. Only explicit
    # human-approved pairs, checked against the persisted review candidate,
    # can use a batched fixture ID request. Reserve one of the existing 3
    # API-Football calls for this request.
    api_today = historical_days.get("usage", {}).get("api_football", {}).get(
        now.date().isoformat(), 0)
    reviewed_id_decisions = {}
    approved_targets = (plan_reviewed_ids(
        preview_keys, _preview_ledger["matches"], previous_review, approved, now,
        day_index=previous_day_index, confirmed_registry=confirmed_ids,
        decisions=reviewed_id_decisions)
        if api_football_poll and api_today < 90 else {})
    for key, why in blocked_approved.items():
        if why:
            approved_targets.pop(key, None)
            reviewed_id_decisions[key] = {
                "status": "DEFERRED",
                "reason": why,
                "provider": "api_football",
                "provider_fixture_id": approved["pairs"][key].get("provider_fixture_id"),
                "evidence_source": "data/lab/ft-provider-day-rotation.json",
            }
    if approved.get("pairs") and not reviewed_id_decisions:
        reason = ("PUSH_NO_AUTHENTICATED_PROVIDER_CALLS"
                  if os.environ.get("GITHUB_EVENT_NAME") == "push" and not recovery_once
                  else "API_FOOTBALL_NOT_CONFIGURED_OR_DISABLED"
                  if not api_football_poll
                  else "API_FOOTBALL_DAILY_CAP_REACHED"
                  if api_today >= 90
                  else "NO_ELIGIBLE_APPROVED_ID_AT_THIS_RUN")
        reviewed_id_decisions = {key: {"status": "DEFERRED", "reason": reason}
                                 for key in approved["pairs"]}
    if approved_targets:
        api_football.reviewed_targets = approved_targets
        rotation["api_football"] = rotation["api_football"][:min(
            2, max(0, 89 - api_today))]
    goal.allowed_days = frozenset(rotation["goal"])
    openfoot.allowed_days = frozenset(rotation["openfoot"])
    api_football.allowed_days = frozenset(rotation["api_football"])
    # Only already-fetched COMPLETE day responses; no additional requests.
    prior_attestations = (json.loads(FT_PROVIDER_ATTESTATIONS.read_text(encoding="utf-8"))
                          if FT_PROVIDER_ATTESTATIONS.exists()
                          else empty_attestations())
    if (not isinstance(prior_attestations, dict)
            or prior_attestations.get("schema_version") != 1
            or not isinstance(prior_attestations.get("records"), dict)
            or not isinstance(prior_attestations.get("conflicts"), dict)):
        raise ValueError("Invalid durable FT provider attestations")
    dual = TwoProviderConsensus(
        review=previous_review, matches=_preview_ledger["matches"],
        goal=goal, api_football=api_football, openfoot=openfoot, now=now,
        prior_attestations=prior_attestations,
        score_hold_keys={key for key, row in goal_approved.get("pairs", {}).items()
                         if isinstance(row, dict) and
                         row.get("score_gate") == "HOLD_FOR_OFFICIAL"})
    # A full date snapshot can corroborate games OUTSIDE the 30-match
    # network queue as well. Only two-provider STRONG review keys enter
    # this bounded, zero-HTTP local postcheck.
    dual_postcheck_keys = sorted(
        key for key, game in dual.review.items()
        if not game.get("possible_duplicates")
        and len({cand.get("provider")
                 for cand in game.get("candidates", [])
                 if (isinstance(cand, dict)
                     and cand.get("match_strength") == "STRONG"
                     and cand.get("orientation") == "SAME_ORDER"
                     and cand.get("provider") in ("goal","api_football","openfoot"))}) >= 2
    )[:500]
    mapped_competitions = competitions_by_key(state.get("alerts", []))
    espn = ESPNResults(mapped_competitions, max_scoreboards=12)
    sportscore = SportScoreResults(mapped_competitions, max_requests=45,max_team_searches=20)
    next_ledger, report, queried = reconcile(
        state, catalog_v4, existing, now=now,
        bsd_lookup=bsd_with_monte, tsdb_lookup=tsdb.lookup,
        espn_lookup=espn.lookup, sportscore_lookup=sportscore.lookup,
        fotmob_lookup=fotmob.lookup if fotmob_enabled else None,
        api_football_lookup=api_football.lookup if api_football_poll else None,
        goal_lookup=goal.lookup if goal_enabled else None,
        openfoot_lookup=openfoot.lookup if openfoot_enabled else None,
        dual_lookup=dual.lookup if goal_enabled or api_football_poll or openfoot_enabled else None,
        dual_postcheck_keys=dual_postcheck_keys,
        lookup_source_version=(11 if goal_enabled or openfoot_enabled else
                               10 if api_football_poll else None),
        max_checks=checks, force_recheck=recovery_once,
        priority_hints=research_hints, evidence_retry=True,
        approved_rechecks=approved_due)


    # Fail closed if dry-run queue and real queue unexpectedly diverged.
    if report["ft_queue"]["selected_keys"] != preview_keys:
        raise ValueError("FT queue changed between date planning and reconciliation")
    # An ID request is counted as a real HTTP attempt (including failures).
    # Do not repeatedly consume the same free-tier slot on every eligible run.
    # Save validated SINGLE-provider claims even if the second provider
    # was not called in this run; never backdate observation timestamps.
    # A later source revision is a hard conflict, not a last-write-wins FT.
    attestation_journal, attestation_stats = merge_attestations(
        prior_attestations, dual.captured, now=now)
    for match_key in set(dual.revisions) | set(attestation_journal["conflicts"]):
        row = next_ledger["matches"].get(match_key)
        if isinstance(row, dict) and row.get("status") != "FINAL":
            row["status"] = "SCORE_CONFLICT"
            row["reason"] = "durable_provider_score_revision_quarantine"
            row.pop("result", None)
        elif isinstance(row, dict) and match_key in dual.confirmations:
            row["status"] = "SCORE_CONFLICT"
            row["reason"] = "durable_provider_score_revision_quarantine"
            row.pop("result", None)
            row.pop("verified_provider_sources", None)
            row.pop("dual_provider_corroboration", None)
    # A dual-provider FINAL must carry the first actually observed timestamp
    # and the sealed identity+score digest from BOTH providers.
    for match_key, sources in dual.confirmations.items():
        row = next_ledger["matches"].get(match_key)
        if isinstance(row, dict) and row.get("status") == "FINAL":
            proofs = attestation_journal["records"].get(match_key, {})
            if (match_key in attestation_journal["conflicts"]
                    or not all(provider in proofs for provider in sources)):
                row["status"] = "SCORE_CONFLICT"
                row["reason"] = "durable_attestation_incomplete_or_conflicted"
                row.pop("result", None)
                row.pop("verified_provider_sources", None)
                continue
            verified_sources = row.setdefault("verified_provider_sources", {})
            verified_sources.update(sources)
            row["dual_provider_corroboration"] = {
                "verified_at_utc": now.isoformat(timespec="seconds"),
                "method": "TWO_STRONG_PROVIDER_IDS_SAME_REGULATION_FT",
                "providers": sorted(sources),
                "scores_agree": True,
                "first_observed_at_utc": {
                    p: proofs[p]["observed_at_utc"] for p in sorted(sources)},
                "attestation_sha256": {
                    p: proofs[p]["sha256"] for p in sorted(sources)},
                "chronology_certified": False,
            }
    write_if_changed(FT_PROVIDER_ATTESTATIONS, attestation_journal)
    report["ft_queue"]["durable_provider_attestations"] = attestation_stats
    if goal.id_requests:
        for match_key in goal_targets:
            row = next_ledger["matches"][match_key]
            row["goal_id_last_attempt_at"] = now.isoformat(timespec="seconds")
            why = goal.id_outcomes.get(match_key)
            if why:
                # An ID attempt is not a complete date-list snapshot.
                # Preserve its REAL diagnostic even when reconciliation
                # otherwise retains an obsolete name-matching reason.
                row["goal_id_last_evidence"] = {
                    "checked_at_utc": now.isoformat(timespec="seconds"),
                    "provider": "goal",
                    "provider_fixture_id": str(goal_targets[match_key]),
                    "reason": why,
                    "id_requests_in_run": goal.id_requests,
                }
                row.setdefault("provider_reasons", {})["goal"] = why
        for match_key, proof in goal.reviewed_observations.items():
            if match_key in next_ledger["matches"]:
                next_ledger["matches"][match_key]["goal_reviewed_last_evidence"] = {
                    **proof, "observed_at_utc": now.isoformat(timespec="seconds")}
                # DO NOT mark FINAL; discrepancy remains for official review.
    if api_football.id_requests:
        for match_key in approved_targets:
            row = next_ledger["matches"][match_key]
            row["api_football_reviewed_id_last_attempt_at"] = (
                now.isoformat(timespec="seconds"))
            # A failed ID query does not produce a new complete provider-day
            # snapshot, so V7 normally preserves the old name-lookup reason.
            # Keep the actual ID response/rejection in its own durable field,
            # and expose it as the most recent API-Football reason. Never
            # invent a score or count a failed response as verified evidence.
            why = api_football.reviewed_outcomes.get(match_key)
            if why:
                row["api_football_reviewed_id_last_evidence"] = {
                    "checked_at_utc": now.isoformat(timespec="seconds"),
                    "provider": "api_football",
                    "provider_fixture_id": approved_targets[match_key]["provider_fixture_id"],
                    "reason": why,
                    "id_requests_in_run": api_football.id_requests,
                    "failure": api_football.reviewed_error_details.get(match_key),
                }
                row.setdefault("provider_reasons", {})["api_football"] = why
    used_days = {
        "goal": sorted(goal.cache),
        "openfoot": sorted(openfoot.days),
        "api_football": sorted(api_football.days),
    }
    # Provider-day hash throttles the shared list globally across all games.
    # No scores, access tokens or raw fixture lists are written to git.
    provider_day_rows = {"goal": goal.cache, "openfoot": openfoot.days,
                         "api_football": api_football.days}
    fingerprints = {
        provider: {day: digest for day, rows in provider_day_rows[provider].items()
                   if isinstance(rows, list)
                   if (digest := day_fingerprint(provider, rows)) is not None}
        for provider in provider_day_rows
    }
    next_day_index = build_index(previous_day_index, api_football.days, now)
    # No raw API payloads or scores are persisted: only complete fixture
    # identities for future collision checks and reviewed IDs.
    write_if_changed(API_FOOTBALL_DAY_INDEX, next_day_index)
    report["ft_queue"]["api_football_complete_index_days"] = sum(
        day.get("status") == "COMPLETE"
        for day in next_day_index["days"].values())
    next_rotation = advance(historical_days, rotation, used_days, now,
                            extra_requests={"goal":goal.id_requests,
                                            "api_football":api_football.id_requests},
                            fingerprints=fingerprints)
    next_history_access = evolve_access(history_access,
                                       api_football.date_error_details, now)
    next_rotation["api_football_history_access"] = next_history_access
    report["ft_queue"]["api_football_history_access"] = next_history_access
    report["ft_queue"]["date_rotation"] = {
        provider: {"selected_days": rotation[provider],
                   "requested_days": used_days[provider],
                   "date_budget": (goal.max_days if provider=="goal" else
                                   {"openfoot":2,"api_football":3}[provider]),
                   "id_requests": (goal.id_requests if provider=="goal" else
                                   api_football.id_requests if provider=="api_football" else 0)}
        for provider in ("goal","openfoot","api_football")
    }
    # ID registry is extracted ONLY from already reconciled confirmed scores;
    # fuzzy candidate queue is explicitly excluded.
    old_identity = (json.loads(PROVIDER_IDENTITY.read_text(encoding="utf-8"))
                    if PROVIDER_IDENTITY.exists()
                    else {"schema_version":1,"entries":{}})
    identity_registry = build_registry(next_ledger, old_identity)
    report["ft_queue"]["dual_provider_consensus"] = dual.summary()
    report["ft_queue"]["goal_reviewed_id_probe"] = {
        "approved_selected": len(reviewed_goal_targets),
        "decisions": goal_review_decisions,
        "observations": dict(sorted(goal.reviewed_observations.items())),
    }
    report["ft_queue"]["goal_id_probe"] = {
        "candidates_planned": len(goal_targets),
        "calls": goal.id_requests,
        "outcome": ([goal.id_outcomes.get(key)
                     for key in goal_targets] if goal_targets else []),
    }
    report["ft_queue"]["api_football_reviewed_id_probe"] = {
        "approved_selected": len(approved_targets),
        "id_requests": api_football.id_requests,
        "outcomes": {key: api_football.reviewed_outcomes.get(key)
                     for key in approved_targets},
        "decisions": reviewed_id_decisions,
        "error_details": dict(sorted(api_football.reviewed_error_details.items())),
    }
    report["ft_queue"]["api_football_date_errors"] = dict(
        sorted(api_football.date_error_details.items()))
    if approved.get("pairs") and checks:
        write_if_changed(REVIEWED_API_ID_DECISIONS, {
            "schema_version": 1, "checked_at_utc": now.isoformat(timespec="seconds"),
            "decisions": reviewed_id_decisions})

    report["ft_queue"]["confirmed_provider_ids"] = identity_registry["confirmed_ids"]
    report["ft_queue"]["provider_id_collisions"] = identity_registry["collision_ids"]
    write_if_changed(DAY_ROTATION, next_rotation)
    write_if_changed(PROVIDER_IDENTITY, identity_registry)
    write_if_changed(PROVIDER_IDENTITY_PUBLIC, identity_registry)

    # Distinguish new automatic confirmations from carried historical evidence.
    previous_matches = existing.get("matches", {})
    report["ft_queue"]["newly_confirmed"] = sum(
        row.get("status") == "FINAL" and
        previous_matches.get(key, {}).get("status") != "FINAL"
        for key, row in next_ledger["matches"].items()
    )
    report["ft_queue"]["documented_ft_total"] = sum(
        row.get("status") == "FINAL" and
        "reviewed_public" in (row.get("result") or {}).get("evidence", "")
        for row in next_ledger["matches"].values()
    )
    report["ft_queue"]["adapter_invocations"] = {
        name: {
            "invocations": sum(int((row.get("provider_attempts", {}).get(name) or {}).get("invocations", 0))
                               for row in next_ledger["matches"].values()),
            "confirmed": sum(int((row.get("provider_attempts", {}).get(name) or {}).get("confirmed", 0))
                             for row in next_ledger["matches"].values()),
        }
        for name in ("bsd", "thesportsdb", "espn", "sportscore",
                     "api_football", "goal", "openfoot", "fotmob", "reviewed_public")
    }
    report["bsd_date_search"] = bsd_date_summary(bsd_finder)
    report["monte_carlos_bsd"] = monte.summary()
    report["thesportsdb_search"] = dict(sorted(tsdb.counts.items()))
    report["espn_scoreboards"] = espn.summary()
    report["sportscore_search"] = sportscore.summary()
    report["fotmob_search"] = fotmob.summary()
    report["fotmob_search"]["licensed_automation_enabled"] = fotmob_enabled
    report["api_football_search"] = api_football.summary()
    report["goal_search"] = goal.summary()
    report["goal_search"]["poll_enabled"] = goal_enabled
    report["openfoot_search"] = openfoot.summary()
    report["openfoot_search"]["poll_enabled"] = openfoot_enabled
    report["api_football_search"]["scheduled_poll_enabled"] = api_football_poll
    report["api_football_search"]["one_shot_activation"] = one_shot
    report["coverage_diagnostics"] = coverage_diagnostics(next_ledger, report)
    backlog = audit_ft_backlog(next_ledger, now, queue_plan=report["ft_queue"], provider_summary={
        "api_football": report["api_football_search"],
        "goal": report["goal_search"],
        "openfoot": report["openfoot_search"],
        "bsd": report["bsd_date_search"],
        "sportscore": report["sportscore_search"],
        "thesportsdb": report["thesportsdb_search"],
    }, evidence_retry=True)
    # Persist bounded evidence of real scheduled provider calls. A subsequent
    # push run can overwrite the dashboard snapshot without erasing this audit.
    event = os.environ.get("GITHUB_EVENT_NAME", "local")
    watchdog_dispatch = (event == "workflow_dispatch"
                         and os.environ.get("LAB_FT_WATCHDOG_DISPATCH") == "true"
                         and os.environ.get("GITHUB_WORKFLOW") ==
                         "Lab - Reconcile FT for all observed matches")
    if event in ("schedule", "workflow_dispatch") or recovery_once:
        previous_audit = (json.loads(API_AUDIT.read_text(encoding="utf-8"))
                          if API_AUDIT.exists() else {"schema_version": 1, "runs": []})
        if (not isinstance(previous_audit, dict) or
                previous_audit.get("schema_version") != 1 or
                not isinstance(previous_audit.get("runs"), list)):
            raise ValueError("Invalid LAB FT API audit history")
        run_id = os.environ.get("GITHUB_RUN_ID", "")[:32]
        record = {
            "utc": now.isoformat(timespec="seconds"),
            "run_id": run_id,
            "trigger": ("one_time_backlog_recovery_v12" if backlog_once
                        else "one_time_recovery" if recovery_once
                        else "h1_ft_watchdog" if watchdog_dispatch
                        else "manual" if event == "workflow_dispatch" else "schedule"),
            "checked_games": queried,
            "authenticated_providers_ran": any((api_football.requests,
                                                goal.requests + goal.id_requests,
                                                openfoot.requests)),
            "effective_evidence_checks": sum(
                row.get("evidence_checked_at") == now.isoformat(timespec="seconds")
                for row in next_ledger["matches"].values()),
            "stable_confirmations_in_run": sum(
                row.get("last_stable_at") == now.isoformat(timespec="seconds")
                for row in next_ledger["matches"].values()),
            "ft_queue": {k: v for k, v in report["ft_queue"].items()
                         if k not in ("selected_keys", "deferred_keys", "adapter_invocations")},
            "final_recorded": report["final_recorded"],
            "past_unverified": report["coverage_diagnostics"]["past_unverified_eligible"],
            "source_order_audit": report["source_order_audit"],
            "providers": {
                "api_football": {"enabled": api_football_poll, "requests": report["api_football_search"]["requests"],
                                 "verified": report["api_football_search"]["verified_in_run"],
                                 "date_errors": dict(sorted(api_football.date_error_details.items())),
                                 "id_errors": dict(sorted(api_football.reviewed_error_details.items()))},
                "goal": {"enabled": goal_enabled, "requests": report["goal_search"]["requests"],
                         "verified": report["goal_search"]["verified_in_run"]},
                "openfoot": {"enabled": openfoot_enabled, "requests": report["openfoot_search"]["requests"],
                             "verified": report["openfoot_search"]["verified_in_run"]},
            },
        }
        history = [item for item in previous_audit["runs"]
                   if item.get("run_id") != run_id or not run_id]
        history.append(record)
        write_if_changed(API_AUDIT, {"schema_version": 1, "runs": history[-32:]})
        print("LAB_FT_API_AUDIT", record["trigger"], "checked", queried,
              "api_football", record["providers"]["api_football"]["requests"],
              "goal", record["providers"]["goal"]["requests"],
              "openfoot", record["providers"]["openfoot"]["requests"],
              "source_conflicts_remaining", report["source_order_audit"]["remaining_quarantined"],
              "queue_never_deferred", report["ft_queue"]["never_checked_deferred"],
              "new_ft", report["ft_queue"]["newly_confirmed"])
    # The review queue reads ONLY the provider date caches already populated
    # above. Its fuzzy diagnostics must never feed back into FT reconciliation.
    try:
        prior_review = (json.loads(IDENTITY_REVIEW.read_text(encoding="utf-8"))
                        if IDENTITY_REVIEW.exists() else None)
        review = build_queue(next_ledger, now, {
            "api_football": api_football.days,
            "goal": goal.cache,
            "openfoot": openfoot.days,
            "bsd": bsd_finder.days,
            "sportscore": sportscore.day_cache,
        }, previous=prior_review)
        write_if_changed(IDENTITY_REVIEW, review)
        print("LAB_FT_IDENTITY_REVIEW", "eligible", review["total_eligible"],
              "with_candidates", review["counts_by_review_flag"].get(
                  "PROVIDER_IDENTITY_CANDIDATES_TO_REVIEW", 0),
              "possible_duplicates", review["counts_by_review_flag"].get(
                  "POSSIBLE_DUPLICATE_OBSERVATION", 0),
              "omitted", review["omitted"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print("LAB_FT_IDENTITY_REVIEW_UNAVAILABLE", type(exc).__name__)
    changed_backlog = write_if_changed(BACKLOG, backlog)
    print("LAB_FT_BACKLOG", "overdue",
          backlog["classification"].get("past_due_unverified", 0),
          "never_checked", backlog["classification"].get("past_due_never_checked", 0),
          "date_groups", len(backlog["overdue_by_kickoff_utc_day"]),
          "report_changed", changed_backlog)
    changed_ledger = write_if_changed(LEDGER, next_ledger)
    changed_report = write_if_changed(REPORT, report)
    print("LAB_FT_RESULT_SYNC", "catalog", report["matches"],
          "final", report["final_recorded"], "unverified", report["unverified"],
          "queried", queried, "bsd_date_pages", report["bsd_date_search"]["date_list_requests"],
          "monte_bsd_resolved", report["monte_carlos_bsd"]["verified_in_run"],
          "monte_bsd_archive", report["monte_carlos_bsd"]["archive_status"],
          "monte_core_candidates", report["monte_carlos_bsd"]["core_name_event_id_candidates"],
          "monte_core_verified", report["monte_carlos_bsd"]["verified_core_name_in_run"],
          "espn_confirmed", report["espn_scoreboards"]["confirmed_in_run"],
          "espn_requests", report["espn_scoreboards"]["requests"],
          "goal_verified", report["goal_search"]["verified_in_run"],
          "goal_requests", report["goal_search"]["requests"],
          "openfoot_verified", report["openfoot_search"]["verified_in_run"],
          "openfoot_requests", report["openfoot_search"]["requests"],
          "api_football_verified", report["api_football_search"]["verified_in_run"],
          "api_football_requests", report["api_football_search"]["requests"],
          "fotmob_verified", report["fotmob_search"]["verified_in_run"],
          "fotmob_requests", report["fotmob_search"]["requests"],
          "sportscore_ft", report["sportscore_search"]["confirmed_in_run"],
          "sportscore_requests", report["sportscore_search"]["requests"],
          "tsdb_requests", report["thesportsdb_search"].get("requested", 0),
          "pending_due", report["pending_due_checks"],
          "ledger_written", changed_ledger, "report_written", changed_report)
    return report


if __name__ == "__main__":
    main()

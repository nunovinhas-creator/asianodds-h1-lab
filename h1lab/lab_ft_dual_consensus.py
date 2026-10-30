"""FT V8: zero-extra-request two-provider corroboration from COMPLETE day caches.

A STRONG identity candidate in the public review queue is NOT evidence of a
final score. It becomes a scoped locator only if two DISTINCT providers return
the expected immutable fixture IDs, team categories, kickoff and competition
and their strict regulation-time validators independently accept the SAME score.

No HTTP, no scraping, no global aliases, no automatic settlement for any
match under an explicit official-score HOLD. Source date adapters themselves
validate that the requested list is complete before populating these caches.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from .lab_identity import CORE, core_tokens
from .lab_identity_review import _qualifiers
from .lab_results import utc
from .lab_ft_crosswalk import providers_from_final, event_id
from .lab_ft_attestations import from_verified, valid

PROVIDERS = frozenset(("api_football", "goal", "openfoot"))
WINDOW = timedelta(minutes=5)
MAX_AGE = timedelta(days=30)


def _extract(provider, ev):
    if provider == "api_football":
        from .lab_api_football import _name, _time
        fixture, league = ev.get("fixture") or {}, ev.get("league") or {}
        if not isinstance(fixture, dict) or not isinstance(league, dict):
            return None
        ident = fixture.get("id")
        return (str(ident) if type(ident) is int and ident > 0 else None,
                _name(ev, "home"), _name(ev, "away"), _time(ev),
                league.get("name"), str(league.get("id")))
    if provider == "goal":
        from .lab_goal import _name, _when
        league = ev.get("league") or ev.get("competition") or {}
        return (str(ev.get("apiId")), _name(ev, "homeTeam"),
                _name(ev, "awayTeam"), _when(ev),
                league.get("name") if isinstance(league, dict) else league, None)
    if provider == "openfoot":
        from .lab_openfoot import names, utc as parse_utc
        home, away = names(ev)
        return (str(ev.get("id")), home, away,
                parse_utc(ev.get("kickoffAt")), ev.get("competitionId"), None)
    return None


def _score(provider, signal, event):
    if provider == "api_football":
        from .lab_api_football import _score
        return _score(signal, event, CORE)
    if provider == "goal":
        from .lab_goal import verify
        return verify(signal, event, CORE)
    if provider == "openfoot":
        from .lab_openfoot import verify
        return verify(signal, event, CORE)
    return None, "unsupported_provider"


class TwoProviderConsensus:
    """Only cache observations already fetched by normal FT reconciliations."""

    def __init__(self, *, review, matches, goal, api_football, openfoot,
                 score_hold_keys=(), now=None, prior_attestations=None):
        self.matches = matches
        self.adapters = {"goal": goal, "api_football": api_football,
                         "openfoot": openfoot}
        self.score_hold_keys = frozenset(score_hold_keys)
        self.review = {}
        self.claims = {}
        self.reasons = Counter()
        self.outcomes = {}
        self.confirmations = {}
        self.now = now
        self.prior = prior_attestations if isinstance(prior_attestations, dict) else {}
        self.captured = {}
        self.revisions = {}
        self.invalid_saved = Counter()
        if not isinstance(review, dict) or review.get("schema_version") != 1:
            return
        for g in review.get("games", []):
            if not isinstance(g, dict) or not isinstance(g.get("match_key"), str):
                continue
            self.review[g["match_key"]] = g
            for c in g.get("candidates", []):
                if (isinstance(c, dict) and c.get("match_strength") == "STRONG"
                        and c.get("provider") in PROVIDERS):
                    token = (c["provider"], str(c.get("provider_event_id")))
                    self.claims.setdefault(token, set()).add(g["match_key"])
        self.claimed_final = set()
        for key, row in matches.items():
            if isinstance(row, dict) and row.get("status") == "FINAL":
                for provider, url in providers_from_final(row).items():
                    self.claimed_final.add((provider, event_id(provider, url), key))

    def _rows(self, provider, day):
        adapter = self.adapters[provider]
        cache = (adapter.cache if provider == "goal" else adapter.days)
        rows = cache.get(day)
        return rows if isinstance(rows, list) else None

    def lookup(self, signal):
        key = signal.get("match_key")
        if key in (self.prior.get("conflicts") or {}):
            return self._fail(key, "persisted_source_revision_quarantine")
        g = self.review.get(key)
        row = self.matches.get(key)
        if (not isinstance(g, dict) or not isinstance(row, dict)
                or row.get("status") not in ("PENDING", "PROVIDER_ERROR")
                or g.get("possible_duplicates")
                or any(signal.get(f) != g.get(f) or signal.get(f) != row.get(f)
                       for f in ("home", "away", "kickoff_utc"))):
            return self._fail(key, "not_unique_or_identity_changed")
        ko = utc(signal.get("kickoff_utc"))
        if ko is None or (self.now is not None and
                          (ko > self.now or self.now-ko > MAX_AGE)):
            return self._fail(key, "invalid_eligibility")
        day = ko.date().isoformat()
        strong = [c for c in g.get("candidates", [])
                  if (isinstance(c, dict) and c.get("provider") in PROVIDERS
                      and c.get("match_strength") == "STRONG"
                      and c.get("orientation") == "SAME_ORDER"
                      and c.get("review_only") is True)]
        if len({c["provider"] for c in strong}) < 2:
            return self._fail(key, "fewer_than_two_strong_providers")
        verified = []
        for c in strong:
            provider = c["provider"]
            ident = str(c.get("provider_event_id") or "")
            if (self.claims.get((provider, ident)) != {key}
                    or any(p == provider and i == ident and k != key
                           for p,i,k in self.claimed_final)):
                return self._fail(key, "provider_id_collision")
            cko = utc(c.get("provider_kickoff_utc"))
            if cko is None or abs(ko - cko) > WINDOW:
                continue
            if any(_qualifiers(signal[s]) != _qualifiers(c.get("provider_"+s))
                   for s in ("home", "away")):
                continue
            rows = self._rows(provider, day)
            if rows is None:
                continue
            matches = []
            for ev in rows:
                if not isinstance(ev, dict):
                    continue
                details = _extract(provider, ev)
                if details is None:
                    continue
                rid, home, away, when, comp, competition_id = details
                if rid != ident:
                    continue
                if (when is None or abs(ko - when) > WINDOW
                        or abs(cko - when) > WINDOW
                        or not isinstance(comp, str)
                        or not isinstance(c.get("provider_competition"), str)
                        or core_tokens(comp) != core_tokens(c["provider_competition"])):
                    continue
                if (any(not core_tokens(name) or
                        core_tokens(name) != core_tokens(c["provider_"+s]) or
                        _qualifiers(name) != _qualifiers(signal[s])
                        for name,s in ((home,"home"),(away,"away")))):
                    continue
                matches.append(ev)
            if len(matches) != 1:
                continue
            # Validate each provider's actual 90-minute status and score using
            # its existing, battle-tested strict verifier.
            source_signal = dict(signal, home=c["provider_home"],
                                 away=c["provider_away"])
            result, reason = _score(provider, source_signal, matches[0])
            if result is not None:
                verified.append((provider, ident, result,
                                 (c["provider_home"], c["provider_away"])))
        # Each current claim has already passed the source's strict
        # regulation-time FT verifier and the locked STRONG review identity.
        # Persist it even when only one provider was available this run.
        if self.now is not None:
            for provider, ident, result, names in verified:
                c = next((item for item in strong
                          if item.get("provider") == provider
                          and str(item.get("provider_event_id")) == ident), None)
                if c is None:
                    continue
                proof = from_verified(key, c, result,
                    observed_at_utc=self.now.isoformat(timespec="seconds"))
                if valid(proof, key=key, candidate=c, now=self.now):
                    self.captured.setdefault(key, {})[provider] = proof
        # Rehydrate only properly sealed observations matching the CURRENT
        # human-reviewed fixture identity, the same provider ID, and the
        # true first-observed timestamp. No raw or synthetic past scores.
        prior = (self.prior.get("records") or {}).get(key) or {}
        if isinstance(prior, dict) and self.now is not None:
            for provider, proof in sorted(prior.items()):
                candidate = next((item for item in strong
                    if item.get("provider") == provider
                    and str(item.get("provider_event_id")) == (
                        proof.get("fixture_id") if isinstance(proof, dict) else None)
                    and self.claims.get((provider, str(item.get("provider_event_id")))) == {key}
                    and not any(p == provider and i == str(item.get("provider_event_id")) and k != key
                                for p,i,k in self.claimed_final)), None)
                if candidate is None or not valid(proof, key=key,
                                                  candidate=candidate,
                                                  now=self.now):
                    self.invalid_saved["identity_or_timestamp_invalid"] += 1
                    continue
                observed = next((x for x in verified if x[0] == provider), None)
                # A complete current listing takes precedence over an older
                # attestation. Missing/invalid/ambiguous current evidence must
                # not silently fall back to a formerly valid final score.
                # Cross-run recovery remains available when this provider was
                # not fetched (no complete cache), without additional HTTP.
                if observed is None and self._rows(provider, day) is not None:
                    self.invalid_saved["current_evidence_invalid"] += 1
                    return self._fail(key, "current_evidence_invalid")
                if observed is not None:
                    if (observed[1] != proof["fixture_id"] or
                        observed[2]["home_goals"] != proof["home_goals"] or
                        observed[2]["away_goals"] != proof["away_goals"]):
                        self.revisions[key] = sorted(set(self.revisions.get(key, []) + [provider]))
                        return self._fail(key, "persisted_source_score_revision")
                    continue
                verified.append((provider, proof["fixture_id"],
                    {"match_key":key, "status":"final",
                     "home_goals":proof["home_goals"],
                     "away_goals":proof["away_goals"],
                     "source":proof["source"]},
                    (proof["home"], proof["away"])))
        if len({p for p, _, _, _ in verified}) < 2:
            return self._fail(key, "two_verified_source_results_unavailable")
        # The two providers must also agree on home/away identity independently.
        # This gate rejects divergent transliterations or non-identical sides;
        # it is intentionally conservative.
        ordered = sorted(verified, key=lambda x: (
            {"api_football": 0, "goal": 1, "openfoot": 2}[x[0]]))
        first = ordered[0][3]
        same_pair = [x for x in ordered if all(
            core_tokens(x[3][i]) == core_tokens(first[i]) for i in (0, 1))]
        if len({x[0] for x in same_pair}) < 2:
            return self._fail(key, "cross_provider_team_identity_disagreement")
        scores = {(x[2]["home_goals"], x[2]["away_goals"])
                  for x in same_pair}
        if len(scores) != 1:
            self.outcomes[key] = {"status": "SCORE_CONFLICT",
                                  "reason": "two_providers_disagree",
                                  "providers": sorted(x[0] for x in same_pair)}
            self.reasons["two_providers_disagree"] += 1
            return None, "dual_provider_score_conflict"
        if key in self.score_hold_keys:
            return self._fail(key, "official_score_hold")
        record = {p: {"source": result["source"],
                      "identity_match": "DUAL_STRONG_CONSENSUS"}
                  for p, _, result, _ in same_pair}
        final = dict(same_pair[0][2], match_key=key,
                     identity_match="REVIEWED_PAIR")
        self.confirmations[key] = record
        self.reasons["verified_two_provider_regulation_ft"] += 1
        return final, "verified_two_provider_regulation_ft"

    def _fail(self, key, reason):
        self.reasons[reason] += 1
        return None, "dual_provider_" + reason

    def summary(self):
        return {"validated_source_claims": sum(len(rows) for rows in self.captured.values()),
                "source_revision_quarantines": len(self.revisions),
                "invalid_previous_claims": dict(sorted(self.invalid_saved.items())),
                "verified_in_run": len(self.confirmations),
                "conflicts_in_run": sum(
                    x.get("status") == "SCORE_CONFLICT"
                    for x in self.outcomes.values()),
                "reason_counts": dict(sorted(self.reasons.items()))}

"""V9: persist minimal, validated FT provider attestations across ordinary runs.

These are **source claims**, not independent proof of official FT or a
scientific acceptance. One record per fixture/provider is immutable: a later
different result is quarantined instead of overwriting the first observation.
All values originate in strict source result validators on COMPLETE day caches,
not from the fuzzy review list itself. No network calls are made here.
"""
from __future__ import annotations
import hashlib
import json
from datetime import timedelta
from .lab_results import utc
from .lab_identity import core_tokens
from .lab_identity_review import _qualifiers
from .lab_ft_crosswalk import event_id

SCHEMA = 1
PROVIDERS = frozenset(("api_football", "goal", "openfoot"))
MAX_RECORDS = 5000
MAX_STALE = timedelta(days=45)
MATCH_TOLERANCE = timedelta(minutes=5)
REQUIRED = ("match_key", "provider", "fixture_id", "home", "away",
            "kickoff_utc", "competition", "source", "home_goals",
            "away_goals", "observed_at_utc")


def _digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")).hexdigest()


def seal(row):
    content = {k: row[k] for k in REQUIRED}
    return {**content, "sha256": _digest(content)}


def empty():
    return {"schema_version": SCHEMA, "records": {}, "conflicts": {}}


def _compatible(previous, row):
    return (previous["fixture_id"] == row["fixture_id"] and
            previous["home_goals"] == row["home_goals"] and
            previous["away_goals"] == row["away_goals"] and
            previous["source"] == row["source"])


def _source_ok(row):
    provider = row["provider"]
    source = row["source"]
    if not isinstance(source, str):
        return False
    if provider in ("api_football", "goal"):
        return event_id(provider, source) == row["fixture_id"]
    if provider == "openfoot":
        return source.startswith("https://openfootapi.com/v1/matches?") and len(source) <= 512
    return False


def valid(row, *, key, candidate, now):
    """Verify stored claim matches its immutable STRONG scoped locator."""
    if not isinstance(row, dict) or not isinstance(candidate, dict):
        return False
    if any(field not in row for field in REQUIRED) or type(row.get("sha256")) is not str:
        return False
    if set(row) != {*REQUIRED, "sha256"}:
        return False
    if _digest({k: row[k] for k in REQUIRED}) != row["sha256"]:
        return False
    if row["match_key"] != key or row["provider"] not in PROVIDERS:
        return False
    if row["provider"] != candidate.get("provider"):
        return False
    if row["fixture_id"] != str(candidate.get("provider_event_id", "")):
        return False
    for side in ("home", "away"):
        name = row[side]
        if (not isinstance(name, str) or
            not core_tokens(name) or
            core_tokens(name) != core_tokens(candidate.get("provider_" + side)) or
            _qualifiers(name) != _qualifiers(candidate.get("provider_" + side))):
            return False
    if (not isinstance(row["competition"], str) or
        not core_tokens(row["competition"]) or
        core_tokens(row["competition"]) !=
            core_tokens(candidate.get("provider_competition"))):
        return False
    if not _source_ok(row):
        return False
    if (any(type(row[k]) is not int or not 0 <= row[k] <= 99
            for k in ("home_goals", "away_goals"))):
        return False
    ko, locked_ko, observed = (utc(row["kickoff_utc"]),
                              utc(candidate.get("provider_kickoff_utc")),
                              utc(row["observed_at_utc"]))
    if (ko is None or locked_ko is None or observed is None or
        abs(ko - locked_ko) > MATCH_TOLERANCE or
        observed < ko + timedelta(minutes=90) or
        observed > now or now - observed > MAX_STALE):
        return False
    return True


def from_verified(key, candidate, result, *, observed_at_utc):
    """Normalize only a result from a successful strict provider verifier."""
    return seal({
        "match_key": key,
        "provider": candidate["provider"],
        "fixture_id": str(candidate["provider_event_id"]),
        "home": candidate["provider_home"],
        "away": candidate["provider_away"],
        "kickoff_utc": candidate["provider_kickoff_utc"],
        "competition": candidate["provider_competition"],
        "source": result["source"],
        "home_goals": result["home_goals"],
        "away_goals": result["away_goals"],
        "observed_at_utc": observed_at_utc,
    })


def merge(previous, captured, *, now):
    """Immutable first claim; quarantine same-provider score revisions."""
    if (not isinstance(previous, dict) or previous.get("schema_version") != SCHEMA or
        not isinstance(previous.get("records"), dict) or
        not isinstance(previous.get("conflicts"), dict)):
        raise ValueError("Invalid FT provider attestation journal")
    data = {"schema_version": SCHEMA,
            "records": {k: dict(v) for k, v in previous["records"].items()},
            "conflicts": {k: dict(v) for k, v in previous["conflicts"].items()}}
    inserted = revised = repeated = 0
    for key, by_provider in sorted(captured.items()):
        if not isinstance(by_provider, dict):
            raise ValueError("Invalid captured attestation records")
        for provider, row in sorted(by_provider.items()):
            if not isinstance(row, dict) or row.get("provider") != provider or row.get("match_key") != key:
                raise ValueError("Invalid provider attestation entry")
            stamp = utc(row.get("observed_at_utc"))
            if stamp is None or stamp > now:
                raise ValueError("Invalid or future evidence timestamp")
            records = data["records"].setdefault(key, {})
            old = records.get(provider)
            if old is None:
                if sum(len(v) for v in data["records"].values()) >= MAX_RECORDS:
                    raise ValueError("Attestation journal capacity exceeded")
                records[provider] = dict(row)
                inserted += 1
            elif _compatible(old, row):
                repeated += 1
            else:
                # The same source changed its score/ID after a stored
                # observation. Neither version may settle the game alone.
                data["conflicts"].setdefault(key, {})[provider] = {
                    "status": "SOURCE_REVISION_QUARANTINE",
                    "original_sha256": old.get("sha256"),
                    "new_sha256": row.get("sha256"),
                    "detected_at_utc": now.isoformat(timespec="seconds"),
                }
                revised += 1
    return data, {"inserted": inserted, "repeated": repeated,
                  "revisions_quarantined": revised,
                  "total_claims": sum(len(r) for r in data["records"].values()),
                  "conflict_keys": len(data["conflicts"])}

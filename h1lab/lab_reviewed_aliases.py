"""Explicitly reviewed source-specific fixture names, NOT fuzzy runtime matching.

These candidate pairs came from a real SportScore date listing for 2026-10-27
and were checked against original alerts by exact match_key and kickoff. The
registry is deliberately fixture-scoped: no generic club aliases, transliteration
guesses, or transfer of identities between competitions.
All date/score/FT/single-identity checks still apply downstream.
"""
from __future__ import annotations

# match_key -> (observed_home, observed_away, observed_kickoff_utc,
#               sportscore_home, sportscore_away).
SPORTSCORE_REVIEWED = {
    "2026-10-27,10102013,10048381": (
        "Montevideo City Torque Reserve", "Albion FC Reserves", "2026-10-27T13:00:00+00:00",
        "Montevideo City Torque Reserves", "Albion fc Reserves"),
    "2026-10-27,95935,1688": (
        "AFC Progresul Spartac '44", "FC Petrolul Ploieşti", "2026-10-27T15:00:00+00:00",
        "Progresul Spartac", "Petrolul Ploiesti"),
    "2026-10-27,49822,49884": (
        "Bristol City U21", "Millwall FC U21", "2026-10-27T13:00:00+00:00",
        "Bristol City U21", "Millwall U21"),
    "2026-10-27,1302,1297": (
        "Panserraikos", "Niki Volou", "2026-10-27T14:00:00+00:00",
        "Panserraikos F.C.", "Niki Volou"),
    "2026-10-27,805,21611": (
        "FK Austria Wien", "TSV Hartberg", "2026-10-27T17:00:00+00:00",
        "Austria Vienna", "TSV Hartberg"),
    "2026-10-27,70933,35866": (
        "FK Ludogorets Razgrad B", "PFC Dobrudzha Dobrich", "2026-10-27T16:00:00+00:00",
        "Ludogorets Razgrad II", "FC Dobrudzha Dobrich"),
    "2026-10-27,1367,1652": (
        "FC Koper", "NK Maribor", "2026-10-27T18:00:00+00:00",
        "FC Koper", "Maribor"),
    "2026-10-27,32555,24870": (
        "Shabab Al Ahli Dubai FC", "Esteghlal Tehran FC", "2026-10-27T16:00:00+00:00",
        "Shabab Al Ahli", "Esteghlal Tehran"),
    "2026-10-27,1734,1137": (
        "Dinamo Zagreb", "HNK Rijeka", "2026-10-27T17:00:00+00:00",
        "Dinamo Zagreb", "Rijeka"),
    "2026-10-27,25158,84806": (
        "Mersin Idmanyurdu SK", "Mus Spor FC", "2026-10-27T16:00:00+00:00",
        "Yeni Mersin İdmanyurdu", "Musspor"),
    "2026-10-27,25153,62798": (
        "Alanyaspor", "12 Bingol spor", "2026-10-27T17:30:00+00:00",
        "Alanyaspor", "12 Bingol Bld"),
    "2026-10-27,39631,35417": (
        "NK Radomlje", "ND Mura 05", "2026-10-27T16:00:00+00:00",
        "NK Radomlje", "NS Mura"),
    "2026-10-27,26908,10047394": (
        "Al Wahda FC (KSA)", "Al-Saqer FC", "2026-10-27T15:25:00+00:00",
        "Al Wehda Mecca", "Al-Saqer"),
    "2026-10-27,34072,741": (
        "Krasnodar", "FK Dinamo Moskva", "2026-10-27T17:30:00+00:00",
        "FK Krasnodar", "Dynamo Moscow"),
    "2026-10-27,26011,26017": (
        "CA Porto (PE)", "SE Ypiranga FC (PE)", "2026-10-27T18:00:00+00:00",
        "Porto PE", "Ypiranga PE"),
    "2026-10-27,65565,23714": (
        "Milton Keynes Dons Reserves", "Watford Reserves", "2026-10-27T13:00:00+00:00",
        "Milton Keynes Dons (R)", "Watford (R)"),
}


def reviewed_provider_pair(signal):
    """Return exact source team pair only for an unchanged, reviewed fixture."""
    row = SPORTSCORE_REVIEWED.get(signal.get("match_key"))
    if not row:
        return None
    if (signal.get("home"), signal.get("away"), signal.get("kickoff_utc")) != row[:3]:
        return None
    return row[3], row[4]

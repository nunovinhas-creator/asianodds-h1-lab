"""Reviewed BSD event IDs from actual finished-event catalogue (2026-10-28).

These are *not* AsianOdds identifiers: they were observed on the BSD date
catalogue during the read-only forensic run #40656748110. All lookups also
revalidate ordered home/away, UTC kickoff and regulation FT on the event detail.
"""
from __future__ import annotations

# AsianOdds match_key -> (original home, original away, UTC kickoff,
#                         verified BSD candidate event ID, BSD home, BSD away)
REVIEWED_BSD_FIXTURES = {
    "2026-10-27,505,27518": (
        "AA Argentinos Juniors", "CS Independiente Rivadavia",
        "2026-10-27T22:00:00+00:00",
        223844, "Argentinos Juniors", "Independiente Rivadavia"),
    "2026-10-27,226,1739": (
        "1. FC Köln", "Union Berlin",
        "2026-10-27T19:45:00+00:00",
        602348, "1. FC Köln", "1. FC Union Berlin"),
    # 28/10: three independent provider date catalogs returned the same KO
    # and orientation for the German cup fixture (BSD, OpenFoot and GOAL).
    # This ID is a lookup lead only; BSD detail is revalidated before any FT.
    "2026-10-28,1069,200": (
        "Paderborn", "VfB Stuttgart 1893",
        "2026-10-28T17:00:00+00:00",
        602346, "SC Paderborn 07", "VfB Stuttgart"),
    # BSD and GOAL independently show same 18:00 UTC event and orientation;
    # Malmö -> Malmö FF is restricted to THIS fixture and THIS event ID.
    "2026-10-28,521,159": (
        "Halmstads BK", "Malmö",
        "2026-10-28T18:00:00+00:00",
        46506, "Halmstads BK", "Malmö FF"),
        "2026-10-27,240,227": (
        "Roma", "Cagliari",
        "2026-10-27T19:45:00+00:00",
        210138, "AS Roma", "Cagliari"),
}


def reviewed_bsd_fixture(signal):
    """Return BSD (numeric ID, source home, source away) for exact saved alert."""
    if not isinstance(signal, dict):
        return None
    row = REVIEWED_BSD_FIXTURES.get(signal.get("match_key"))
    if not row:
        return None
    if (signal.get("home"), signal.get("away"), signal.get("kickoff_utc")) != row[:3]:
        return None
    return row[3], row[4], row[5]

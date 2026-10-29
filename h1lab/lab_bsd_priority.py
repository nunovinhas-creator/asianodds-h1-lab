"""BSD-first FT reconciliation using the owner's working Monte-Carlos IDs.

Monte-Carlos already stores real BSD event IDs, so the LAB must attempt a
fresh validated BSD /events/{id}/ FIRST, not waste a fuzzy team query or
a possibly incomplete date search BEFORE consulting a known ID.

AsianOdds IDs are NOT BSD IDs. Every candidate from Monte-Carlos is matched
by original home/away + UTC kickoff, checked for collisions, and re-fetched
and validated by BSD. The Monte-Carlos database score NEVER becomes FT alone.

The date/name fallback is allowed only when the Monte archive did NOT cover
the event or could not be loaded. Provider failures and ambiguous matches
must not trigger extra BSD calls. No H1 code or state is modified.
"""
from __future__ import annotations

FALLBACK_REASONS = frozenset({
    "monte_no_exact_archive_match",
    "monte_archive_unavailable",
    "monte_core_invalid_identity",
})


def lookup_bsd_monte_first(signal, monte, date_fallback):
    """Try one *known actual BSD ID* before any fuzzy/list date query.

    Both adapters implement lookup(signal) -> (strict FT or None, reason).
    The fast path does one authenticated BSD detail request at most
    (unless the provider explicitly reports an event redirect).
    """
    result, reason = monte.lookup(signal)
    if result is not None:
        return result, reason
    if reason not in FALLBACK_REASONS:
        return None, reason
    return date_fallback.lookup(signal)

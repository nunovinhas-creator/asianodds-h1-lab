"""Fail-closed team-name identity for LAB FT reconciliation (never used by H1).

The H1 matcher (``results.norm_team``) only strips ``fc/fk/sv/afc`` from the
ends of a name. Real providers differ by *club designators* and city exonyms:

    AsianOdds "Roma"             ESPN/BSD "AS Roma"
    AsianOdds "Calcio Como"      ESPN     "Como"
    AsianOdds "Union Berlin"     BSD/ESPN "1. FC Union Berlin"
    AsianOdds "1. FC Köln"       ESPN     "FC Cologne"

This module defines one stricter-than-fuzzy rule, ``CORE_NAME``: two names
are the same club only if their token sets are *identical* after removing a
closed list of designators and mapping a closed list of exonyms. There is no
similarity score, no substring/containment and no edit distance.

A candidate event is accepted only when, inside the kickoff window:

* both sides match (``EXACT`` or ``CORE_NAME``) in the stated home/away order;
* the reversed orientation does not also match (would be a source-order issue);
* exactly one event matches the pair, and no *other* event shares either
  side's core name (a club cannot play twice in the window);
* age/reserve/women qualifiers are part of the core and must be equal.

Every acceptance records the method so results can be audited and filtered.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

IDENTITY_VERSION = 1
EXACT = "EXACT"
CORE = "CORE_NAME"
WINDOW_SECONDS = 90 * 60

# Club-form designators: legal form or generic "club" words. Removing them
# never merges two different clubs that play the same day in one window
# (enforced again by the uniqueness rule below).
DESIGNATORS = frozenset({
    "fc", "fk", "sv", "afc", "cf", "sc", "ac", "as", "ss", "ssd", "asd", "ssc",
    "cd", "ca", "cs", "aa", "club", "calcio", "sk", "nk", "ks", "sd", "ud",
    "if", "bk", "ik", "fsv", "vfl", "tsv", "spvgg", "ogc", "rc", "us", "the",
    "1", "de", "do", "da", "dos", "das", "football", "futbol", "clube",
})
# Exonyms: both sides are mapped, so the direction does not matter.
EXONYMS = {
    "koln": "cologne", "munchen": "munich", "milano": "milan", "praha": "prague",
    "beograd": "belgrade", "bucuresti": "bucharest", "kobenhavn": "copenhagen",
    "lisboa": "lisbon", "moskva": "moscow", "warszawa": "warsaw",
    "sevilla": "seville", "athina": "athens", "wien": "vienna",
    "napoli": "naples", "torino": "turin", "genova": "genoa", "firenze": "florence",
}
# Qualifiers stay in the core (so U21 != senior side) but are canonicalised.
QUALIFIERS = {
    "reserves": "reserves", "reserve": "reserves", "res": "reserves",
    "ii": "reserves", "b": "reserves",
    "women": "women", "w": "women", "ladies": "women", "femenino": "women",
    "feminino": "women", "frauen": "women", "dames": "women",
    "youth": "youth", "academy": "youth",
}
YEAR = re.compile(r"^(18|19|20)[0-9]{2}$")
AGE = re.compile(r"\bu[\s\-]?(1[5-9]|2[0-3])\b")


def _fold(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("ı", "i").replace("ø", "o").replace("æ", "ae").replace("ß", "ss")
    return value.casefold().replace("&", " and ")


def core_tokens(name):
    """Canonical token set of a team name, or empty frozenset if unusable."""
    text = AGE.sub(lambda m: " u" + m.group(1) + " ", _fold(name))
    out = []
    for tok in re.findall(r"[a-z0-9]+", text):
        if tok in DESIGNATORS or YEAR.match(tok):
            continue
        tok = QUALIFIERS.get(tok, tok)
        tok = EXONYMS.get(tok, tok)
        if tok in ("st", "saint"):
            tok = "st"
        out.append(tok)
    return frozenset(out)


def _exact(a, b):
    from .results import norm_team  # pure helper, read-only reuse
    return bool(norm_team(a)) and norm_team(a) == norm_team(b)


def side_level(signal_name, provider_name):
    """EXACT, CORE_NAME or None for one side."""
    if not isinstance(signal_name, str) or not isinstance(provider_name, str):
        return None
    if _exact(signal_name, provider_name):
        return EXACT
    a, b = core_tokens(signal_name), core_tokens(provider_name)
    # At least one informative token: never match on designators alone.
    if a and a == b and any(len(t) >= 3 and not t.isdigit() for t in a):
        return CORE
    return None


def pair_level(home, away, ev_home, ev_away):
    lh, la = side_level(home, ev_home), side_level(away, ev_away)
    if lh is None or la is None:
        return None
    return EXACT if lh == la == EXACT else CORE


def _utc(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


def select_event(signal, events, names, kickoff, window_seconds=WINDOW_SECONDS):
    """Return (event, level, reason). ``names(ev)->(home, away)``, ``kickoff(ev)->datetime``.

    Fail closed on any ambiguity; ``reason`` is a stable diagnostic string.
    """
    ko = _utc(signal.get("kickoff_utc"))
    home, away = signal.get("home"), signal.get("away")
    if ko is None or not isinstance(home, str) or not isinstance(away, str):
        return None, None, "identity_invalid_signal"
    in_window = []
    for ev in events or ():
        try:
            when = _utc(kickoff(ev))
            eh, ea = names(ev)
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
        if when is None or abs((when - ko).total_seconds()) > window_seconds:
            continue
        in_window.append((ev, eh, ea))
    exact = [x for x in in_window if pair_level(home, away, x[1], x[2]) == EXACT]
    if len(exact) == 1:
        return exact[0][0], EXACT, "identity_exact"
    if len(exact) > 1:
        return None, None, "identity_ambiguous_exact"
    core = [x for x in in_window if pair_level(home, away, x[1], x[2]) == CORE]
    reversed_ = [x for x in in_window if pair_level(home, away, x[2], x[1]) is not None]
    if reversed_:
        return None, None, "identity_reversed_order_candidate"
    if not core:
        return None, None, "identity_no_core_match"
    if len(core) > 1:
        return None, None, "identity_ambiguous_core"
    chosen = core[0][0]
    hc, ac = core_tokens(home), core_tokens(away)
    for ev, eh, ea in in_window:
        if ev is chosen:
            continue
        if {core_tokens(eh), core_tokens(ea)} & {hc, ac}:
            return None, None, "identity_side_collision"
    return chosen, CORE, "identity_core_name"

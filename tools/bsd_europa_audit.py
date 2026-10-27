"""Audit BSD coverage of the 30 European ORUSEYE competitions.

Read-only. Fail-closed: a league counts as covered only when its BSD league
is identified without ambiguity and sampled events pass id-based identity
checks (event id, league id, team ids) between list, detail and a team_id
query. No name-based or presumed matching is used to accept an event.

The token is read from BSD_API_KEY and is never printed. URLs and response
bodies are never printed either.
"""
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://sports.bzzoiro.com/api/v2/"
UTC = timezone.utc
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "..", "config", "oruseye_europe30.json")

FUTURE_DAYS = 21
RECENT_DAYS = 14
SAMPLE_EVENTS = 3
PAUSE = 0.35

COUNTRY_ALIASES = {
    "czech republic": {"czech republic", "czechia"},
    "turkey": {"turkey", "turkiye"},
    "netherlands": {"netherlands", "holland"},
}
GLOBAL_EXCLUDE = re.compile(
    r"wom[ae]n|femin|frauen|\bu ?1\d\b|\bu ?2[0-3]\b|youth|junior|reserve|"
    r"\bcup\b|copa|coupe|pokal|play-?offs?|super ?cup|federacion|amateur|"
    r"regional|\bwomen\b")
TIER1_EXCLUDE_TOKENS = {"2", "3", "ii", "iii", "b", "challenger"}


class BSDError(RuntimeError):
    pass


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return value.casefold().strip()


def tokens(value):
    return set(re.findall(r"[a-z0-9]+", norm(value)))


# ---------------------------------------------------------------- HTTP

def make_fetch(token, pause=PAUSE, sleep=time.sleep):
    calls = {"n": 0}

    def fetch(path, params=None):
        url = API + path + ("?" + urlencode(params) if params else "")
        if not url.startswith(API):
            raise BSDError("unexpected url")
        for attempt in range(4):
            sleep(pause)
            calls["n"] += 1
            req = Request(url, headers={
                "Authorization": "Token " + token,
                "Accept": "application/json",
                "User-Agent": "AsianOdds-H1-Lab/bsd-europa-audit",
            })
            try:
                with urlopen(req, timeout=20) as resp:
                    return json.loads(resp.read(5_000_000))
            except HTTPError as exc:
                if exc.code == 429 and attempt < 3:
                    sleep(5 * (attempt + 1))
                    continue
                raise BSDError("HTTP " + str(exc.code)) from None
            except (URLError, TimeoutError, OSError, ValueError):
                if attempt < 2:
                    sleep(2)
                    continue
                raise BSDError("unavailable or invalid response") from None
        raise BSDError("rate limited")

    fetch.calls = calls
    return fetch


def rows_of(payload):
    if isinstance(payload, list):
        return payload, None, None
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"], payload.get("next"), payload.get("count")
    raise BSDError("unexpected list shape")


def list_all(fetch, path, params, page=100, max_pages=40):
    out, offset = [], 0
    for _ in range(max_pages):
        rows, nxt, _ = rows_of(fetch(path, dict(params, limit=page, offset=offset)))
        out += rows
        if not nxt or not rows:
            return out, True
        offset += len(rows)
    return out, False


# ------------------------------------------------------------ fields

def _pos_int(val):
    return val if type(val) is int and val > 0 else None


def ref_id(obj, key):
    """Id of a related object; only explicit id fields are accepted.

    key is "league", "home_team" or "away_team". Looks at, in order:
    obj[key]["id"], obj[key+"_id"], and for teams obj[side]["id"],
    obj[side+"_id"], obj["teams"][side]["id"]. Never derives ids from names.
    """
    val = obj.get(key)
    if isinstance(val, dict) and _pos_int(val.get("id")):
        return val["id"]
    if _pos_int(obj.get(key + "_id")):
        return obj[key + "_id"]
    if key in ("home_team", "away_team"):
        side = key.split("_")[0]
        for cand in (obj.get(side), obj.get(side + "_team_obj"),
                     (obj.get("teams") or {}).get(side) if isinstance(obj.get("teams"), dict) else None):
            if isinstance(cand, dict) and _pos_int(cand.get("id")):
                return cand["id"]
        if _pos_int(obj.get(side + "_id")):
            return obj[side + "_id"]
    return None


def shape(obj, depth=1):
    """Field names and types only (no values) for schema evidence."""
    if isinstance(obj, dict):
        return {k: (shape(v, depth - 1) if depth > 0 and isinstance(v, (dict, list))
                    else type(v).__name__) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [shape(obj[0], depth)] if obj else []
    return type(obj).__name__


def ref_name(obj, key):
    val = obj.get(key)
    if isinstance(val, dict):
        return val.get("name") or ""
    if isinstance(val, str):
        return val
    return obj.get(key + "_name") or ""


def league_country(league):
    c = league.get("country")
    if isinstance(c, dict):
        c = c.get("name")
    return c or league.get("country_name") or ""


def kickoff(event):
    v = event.get("event_date") or event.get("start_time")
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else None


def int_score(v):
    return type(v) is int and v >= 0


# --------------------------------------------------------- mapping

def country_ok(oruseye_country, bsd_country):
    want = COUNTRY_ALIASES.get(norm(oruseye_country), {norm(oruseye_country)})
    return norm(bsd_country) in want


def candidates_for(comp, leagues):
    pat = re.compile(comp["pattern"])
    same_country, kept, dropped = [], [], []
    for lg in leagues:
        if not country_ok(comp["country"], league_country(lg)):
            continue
        same_country.append(lg)
        name = norm(lg.get("name"))
        if lg.get("is_women") is True or GLOBAL_EXCLUDE.search(name):
            continue
        if not pat.search(name):
            continue
        if comp["tier"] == 1 and tokens(name) & TIER1_EXCLUDE_TOKENS:
            dropped.append(lg)
            continue
        kept.append(lg)
    return kept, dropped, same_country


def brief(lg):
    return {"id": lg.get("id"), "name": lg.get("name"),
            "country": league_country(lg)}


# ------------------------------------------------------------ checks

def check_event(fetch, league_id, ev):
    """Id-based identity and 90-minute score checks for one finished event."""
    r = {"event_id": ev.get("id"), "problems": []}
    eid = ev.get("id")
    if type(eid) is not int or eid <= 0:
        r["problems"].append("list_event_id_invalid")
        return r
    detail = fetch("events/%d/" % eid)
    if not isinstance(detail, dict):
        r["problems"].append("detail_not_object")
        return r
    r["list_shape"] = shape(ev)
    r["detail_shape"] = shape(detail)
    if detail.get("id") != eid:
        r["problems"].append("detail_id_mismatch")
    lid = ref_id(detail, "league")
    r["league_id"] = lid
    if lid is not None and lid != league_id:
        r["problems"].append("detail_league_mismatch")
    if lid is None:
        r["problems"].append("detail_league_id_missing")
    for side in ("home_team", "away_team"):
        a, b = ref_id(ev, side), ref_id(detail, side)
        r[side + "_id"] = b
        if a is None or b is None:
            r["problems"].append(side + "_id_missing")
        elif a != b:
            r["problems"].append(side + "_id_changed")
        if norm(ref_name(ev, side)) != norm(ref_name(detail, side)):
            r["problems"].append(side + "_name_changed")
    if ref_id(detail, "home_team") and ref_id(detail, "home_team") == ref_id(detail, "away_team"):
        r["problems"].append("home_equals_away")
    r["status"] = detail.get("status")
    r["home_score"] = detail.get("home_score")
    r["away_score"] = detail.get("away_score")
    r["has_et_field"] = "extra_time_score" in detail
    r["has_pen_field"] = "penalty_shootout" in detail
    r["ft90_ok"] = (detail.get("status") == "finished"
                    and int_score(detail.get("home_score"))
                    and int_score(detail.get("away_score")))
    if not r["ft90_ok"]:
        r["problems"].append("ft90_not_valid")
    ko = kickoff(detail)
    r["kickoff_utc"] = ko.isoformat() if ko else None
    if ko is None:
        r["problems"].append("kickoff_missing")
    # Team identity via team_id query: the same event must come back once.
    hid = ref_id(detail, "home_team")
    if hid and ko:
        day = ko.date().isoformat()
        rows, _, _ = rows_of(fetch("events/", {"team_id": hid, "date_from": day,
                                               "date_to": day, "limit": 50}))
        hits = [x for x in rows if isinstance(x, dict) and x.get("id") == eid]
        r["team_query_hits"] = len(hits)
        if len(hits) != 1:
            r["problems"].append("team_id_query_mismatch")
    r["ok"] = not r["problems"]
    return r


def audit_league(fetch, comp, lg, today):
    lid = lg["id"]
    out = {"bsd_league": brief(lg)}
    try:
        season = fetch("leagues/%d/season/" % lid)
        out["current_season"] = ({k: season.get(k) for k in
                                  ("id", "name", "start_date", "end_date", "is_current")}
                                 if isinstance(season, dict) else None)
    except BSDError as exc:
        out["current_season"] = {"error": str(exc)}

    if isinstance(season, dict):
        out["current_season_shape"] = shape(season)
    fut = fetch("events/", {"league_id": lid, "status": "upcoming",
                            "date_from": today.isoformat(),
                            "date_to": (today + timedelta(days=FUTURE_DAYS)).isoformat(),
                            "limit": 200})
    frows, fnext, fcount = rows_of(fut)
    if frows and isinstance(frows[0], dict):
        out["future_event_shape"] = shape(frows[0])
    now = datetime.now(UTC)
    future_ok = [e for e in frows if isinstance(e, dict) and kickoff(e)
                 and kickoff(e) >= now - timedelta(hours=3)
                 and ref_id(e, "home_team") and ref_id(e, "away_team")]
    wrong_league = [e.get("id") for e in frows if isinstance(e, dict)
                    and ref_id(e, "league") not in (None, lid)]
    out["future"] = {"count": fcount if fcount is not None else len(frows),
                     "rows_seen": len(frows), "with_kickoff_and_team_ids": len(future_ok),
                     "truncated": bool(fnext), "wrong_league_ids": wrong_league[:5],
                     "next_kickoff": min((kickoff(e) for e in future_ok), default=None)}
    if out["future"]["next_kickoff"]:
        out["future"]["next_kickoff"] = out["future"]["next_kickoff"].isoformat()

    past = fetch("events/", {"league_id": lid, "status": "finished",
                             "date_from": (today - timedelta(days=RECENT_DAYS)).isoformat(),
                             "date_to": (today - timedelta(days=1)).isoformat(),
                             "limit": 200})
    prows, pnext, pcount = rows_of(past)
    with_goals = [e for e in prows if isinstance(e, dict)
                  and int_score(e.get("home_score")) and int_score(e.get("away_score"))]
    wrong_league_p = [e.get("id") for e in prows if isinstance(e, dict)
                      and ref_id(e, "league") not in (None, lid)]
    out["recent"] = {"count": pcount if pcount is not None else len(prows),
                     "rows_seen": len(prows), "with_int_scores": len(with_goals),
                     "truncated": bool(pnext), "wrong_league_ids": wrong_league_p[:5]}

    samples = sorted(with_goals, key=lambda e: kickoff(e) or now, reverse=True)[:SAMPLE_EVENTS]
    out["samples"] = []
    for ev in samples:
        try:
            out["samples"].append(check_event(fetch, lid, ev))
        except BSDError as exc:
            out["samples"].append({"event_id": ev.get("id"), "ok": False,
                                   "problems": ["provider_error: " + str(exc)]})

    s = out["samples"]
    out["flags"] = {
        "future_fixtures": len(future_ok) > 0 and not wrong_league,
        "recent_results": len(with_goals) > 0 and not wrong_league_p,
        "stable_ids": bool(s) and all(x.get("ok") for x in s),
        "ft90_goals": bool(s) and all(x.get("ft90_ok") for x in s),
    }
    return out


def run(fetch, comps, today=None, log=print):
    today = today or datetime.now(UTC).date()
    report = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "api_root": API, "window": {"future_days": FUTURE_DAYS,
                                          "recent_days": RECENT_DAYS,
                                          "samples_per_league": SAMPLE_EVENTS}}

    leagues, complete = list_all(fetch, "leagues/", {})
    leagues = [lg for lg in leagues if isinstance(lg, dict) and type(lg.get("id")) is int]
    report["leagues_total"] = len(leagues)
    report["leagues_list_complete"] = complete
    report["league_object_keys"] = sorted(leagues[0].keys()) if leagues else []
    report["countries"] = sorted({league_country(lg) for lg in leagues})
    report["all_leagues"] = [brief(lg) for lg in leagues]
    log("BSD_EU_LEAGUES_TOTAL:", len(leagues), "complete=" + str(complete))
    log("BSD_EU_LEAGUE_KEYS:", ",".join(report["league_object_keys"]))
    log("BSD_EU_COUNTRIES:", len(report["countries"]))

    try:
        feed = fetch("fixtures/changes/", {"limit": 5})
        report["change_feed"] = {"reachable": True,
                                 "count": feed.get("count") if isinstance(feed, dict) else None}
    except BSDError as exc:
        report["change_feed"] = {"reachable": False, "error": str(exc)}
    log("BSD_EU_CHANGE_FEED:", json.dumps(report["change_feed"]))

    results = []
    for comp in comps:
        row = {"code": comp["code"], "country": comp["country"], "tier": comp["tier"],
               "pattern": comp["pattern"]}
        kept, dropped, same_country = candidates_for(comp, leagues)
        row["candidates"] = [brief(x) for x in kept]
        row["dropped_lower_tier_like"] = [brief(x) for x in dropped]
        row["country_leagues"] = [brief(x) for x in same_country]
        if len(kept) == 1:
            row["mapping"] = "exact"
            try:
                row.update(audit_league(fetch, comp, kept[0], today))
            except BSDError as exc:
                row["mapping"] = "provider_error"
                row["error"] = str(exc)
        else:
            row["mapping"] = "ambiguous" if kept else "missing"
        if row.get("samples") and not report.get("event_schema"):
            sm = row["samples"][0]
            report["event_schema"] = {"list": sm.get("list_shape"),
                                      "detail": sm.get("detail_shape"),
                                      "season": row.get("current_season_shape"),
                                      "future": row.get("future_event_shape")}
            log("BSD_EU_EVENT_LIST_SHAPE:", json.dumps(sm.get("list_shape"), sort_keys=True))
            log("BSD_EU_EVENT_DETAIL_SHAPE:", json.dumps(sm.get("detail_shape"), sort_keys=True))
            log("BSD_EU_SEASON_SHAPE:", json.dumps(row.get("current_season_shape"), sort_keys=True))
        f = row.get("flags", {})
        row["covered"] = row["mapping"] == "exact" and all(f.values()) and bool(f)
        results.append(row)
        log("BSD_EU_MAP", comp["code"], row["mapping"],
            "bsd=" + ("|".join("%s:%s" % (x["id"], x["name"]) for x in row["candidates"]) or "-"),
            "country_leagues=" + str(len(same_country)))
        if row["mapping"] == "exact":
            log("BSD_EU_RESULT", comp["code"],
                "future=%s(%s)" % (f.get("future_fixtures"), row["future"]["with_kickoff_and_team_ids"]),
                "recent=%s(%s)" % (f.get("recent_results"), row["recent"]["with_int_scores"]),
                "stable_ids=%s" % f.get("stable_ids"),
                "ft90=%s" % f.get("ft90_goals"),
                "samples=" + ",".join("%s:%s" % (s.get("event_id"),
                                                 "ok" if s.get("ok") else "/".join(s.get("problems", [])))
                                      for s in row["samples"]))
    report["competitions"] = results
    report["summary"] = {
        "mapped_exact": sum(r["mapping"] == "exact" for r in results),
        "ambiguous": [r["code"] for r in results if r["mapping"] == "ambiguous"],
        "missing": [r["code"] for r in results if r["mapping"] == "missing"],
        "covered_all_flags": [r["code"] for r in results if r["covered"]],
        "requests": fetch.calls["n"] if hasattr(fetch, "calls") else None,
    }
    log("BSD_EU_SUMMARY:", json.dumps(report["summary"]))
    return report


def main(argv=None):
    token = os.environ.get("BSD_API_KEY", "").strip()
    if not token:
        raise SystemExit("BSD_SECRET_MISSING")
    out = (argv or sys.argv[1:] or ["bsd-europa-audit.json"])[0]
    comps = json.load(open(CONFIG, encoding="utf-8"))["competitions"]
    if len(comps) != 30:
        raise SystemExit("BSD_EU_CONFIG_NOT_30")
    try:
        report = run(make_fetch(token), comps)
    except BSDError as exc:
        raise SystemExit("BSD_EU_PROVIDER_ERROR: " + str(exc)) from None
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    print("BSD_EU_WRITTEN:", out)


if __name__ == "__main__":
    main()

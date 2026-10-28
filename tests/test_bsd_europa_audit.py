"""BSD Europe coverage audit tests: synthetic data only, no network."""
import json
import os
import unittest
from datetime import date, datetime, timedelta, timezone

from tools import bsd_europa_audit as audit

UTC = timezone.utc
NOW = datetime.now(UTC)
PAST = (NOW - timedelta(days=2)).replace(microsecond=0)
FUT = (NOW + timedelta(days=3)).replace(microsecond=0)

LEAGUES = [
    {"id": 1, "name": "Premier League", "country": "England"},
    {"id": 2, "name": "Premier League 2", "country": "England"},
    {"id": 3, "name": "Super Lig", "country": "Türkiye"},
    {"id": 4, "name": "Super League", "country": "Greece"},
    {"id": 5, "name": "Super League 2", "country": "Greece"},
    {"id": 6, "name": "Pro League", "country": "Belgium"},
    {"id": 7, "name": "Challenger Pro League", "country": "Belgium"},
    {"id": 8, "name": "Primera Federación", "country": "Spain"},
    {"id": 9, "name": "La Liga", "country": "Spain"},
    {"id": 10, "name": "Liga II", "country": "Romania"},
    {"id": 11, "name": "Superliga", "country": "Romania"},
    {"id": 12, "name": "Women's Super League", "country": "England"},
]


def ev(eid, league, home, away, when, status, hs=None, as_=None):
    return {"id": eid, "league": {"id": league, "name": "x"},
            "home_team": {"id": home, "name": "H%d" % home},
            "away_team": {"id": away, "name": "A%d" % away},
            "event_date": when.isoformat(), "status": status,
            "home_score": hs, "away_score": as_,
            "extra_time_score": None, "penalty_shootout": None}


class FakeAPI:
    def __init__(self, events, detail_override=None):
        self.events = events
        self.detail_override = detail_override or {}
        self.calls = {"n": 0}

    def __call__(self, path, params=None):
        self.calls["n"] += 1
        params = params or {}
        if path == "leagues/":
            off = params.get("offset", 0)
            rows = LEAGUES[off:off + 5]
            nxt = "more" if off + 5 < len(LEAGUES) else None
            return {"count": len(LEAGUES), "next": nxt, "results": rows}
        if path == "fixtures/changes/":
            return {"count": 0, "changes": []}
        if path.startswith("leagues/") and path.endswith("/season/"):
            return {"id": 99, "name": "2026/27", "is_current": True}
        if path == "events/":
            rows = list(self.events)
            if "league_id" in params:
                rows = [e for e in rows if e["league"]["id"] == params["league_id"]]
            if "team_id" in params:
                t = params["team_id"]
                rows = [e for e in rows if t in (e["home_team"]["id"], e["away_team"]["id"])]
            if "status" in params:
                rows = [e for e in rows if e["status"] == params["status"]]
            return {"count": len(rows), "next": None, "results": rows}
        if path.startswith("events/"):
            eid = int(path.split("/")[1])
            if eid in self.detail_override:
                return self.detail_override[eid]
            return next(e for e in self.events if e["id"] == eid)
        raise AssertionError(path)


def comp(code, country, tier, pattern):
    return {"code": code, "country": country, "tier": tier, "pattern": pattern}


class MappingTests(unittest.TestCase):
    def test_tier1_drops_second_divisions_and_women(self):
        kept, dropped, _ = audit.candidates_for(
            comp("ENG1", "England", 1, "premier league"), LEAGUES)
        self.assertEqual([x["id"] for x in kept], [1])
        self.assertEqual([x["id"] for x in dropped], [2])

    def test_country_alias_turkey(self):
        kept, _, _ = audit.candidates_for(comp("TUR1", "Turkey", 1, "super lig|süper lig"), LEAGUES)
        self.assertEqual([x["id"] for x in kept], [3])

    def test_belgium_challenger_and_greece_2_dropped(self):
        b, _, _ = audit.candidates_for(comp("BEL1", "Belgium", 1, "pro league|jupiler"), LEAGUES)
        g, _, _ = audit.candidates_for(comp("GRE1", "Greece", 1, "super league"), LEAGUES)
        self.assertEqual([x["id"] for x in b], [6])
        self.assertEqual([x["id"] for x in g], [4])

    def test_spain_federacion_excluded_and_romania_liga_ii_dropped(self):
        s, _, _ = audit.candidates_for(comp("ESP1", "Spain", 1, "la liga|primera"), LEAGUES)
        r, _, _ = audit.candidates_for(comp("ROU1", "Romania", 1, "liga i|superliga|liga 1"), LEAGUES)
        self.assertEqual([x["id"] for x in s], [9])
        self.assertEqual([x["id"] for x in r], [11])

    def test_missing_country(self):
        kept, _, same = audit.candidates_for(comp("SRB1", "Serbia", 1, "superliga"), LEAGUES)
        self.assertEqual(kept, [])
        self.assertEqual(same, [])


class AuditTests(unittest.TestCase):
    def run_audit(self, api, comps):
        return audit.run(api, comps, today=NOW.date(), log=lambda *a: None)

    def test_covered_league_passes_all_flags(self):
        api = FakeAPI([ev(100, 1, 10, 11, PAST, "finished", 2, 1),
                       ev(101, 1, 12, 13, FUT, "upcoming")])
        rep = self.run_audit(api, [comp("ENG1", "England", 1, "premier league")])
        row = rep["competitions"][0]
        self.assertEqual(row["mapping"], "exact")
        self.assertEqual(row["flags"], {"future_fixtures": True, "recent_results": True,
                                        "stable_ids": True, "ft90_goals": True})
        self.assertTrue(row["covered"])
        self.assertEqual(rep["leagues_total"], len(LEAGUES))
        self.assertTrue(rep["leagues_list_complete"])

    def test_team_id_change_between_list_and_detail_fails(self):
        bad = ev(100, 1, 10, 99, PAST, "finished", 2, 1)
        api = FakeAPI([ev(100, 1, 10, 11, PAST, "finished", 2, 1)], {100: bad})
        rep = self.run_audit(api, [comp("ENG1", "England", 1, "premier league")])
        row = rep["competitions"][0]
        self.assertFalse(row["flags"]["stable_ids"])
        self.assertIn("away_team_id_changed", row["samples"][0]["problems"])
        self.assertFalse(row["covered"])

    def test_detail_from_other_league_fails(self):
        other = ev(100, 4, 10, 11, PAST, "finished", 2, 1)
        api = FakeAPI([ev(100, 1, 10, 11, PAST, "finished", 2, 1)], {100: other})
        rep = self.run_audit(api, [comp("ENG1", "England", 1, "premier league")])
        self.assertIn("detail_league_mismatch", rep["competitions"][0]["samples"][0]["problems"])

    def test_missing_score_is_not_ft90(self):
        noscore = ev(100, 1, 10, 11, PAST, "finished", None, None)
        api = FakeAPI([ev(100, 1, 10, 11, PAST, "finished", 1, 0)], {100: noscore})
        rep = self.run_audit(api, [comp("ENG1", "England", 1, "premier league")])
        self.assertFalse(rep["competitions"][0]["flags"]["ft90_goals"])

    def test_no_future_fixtures_flag(self):
        api = FakeAPI([ev(100, 1, 10, 11, PAST, "finished", 0, 0)])
        rep = self.run_audit(api, [comp("ENG1", "England", 1, "premier league")])
        self.assertFalse(rep["competitions"][0]["flags"]["future_fixtures"])
        self.assertTrue(rep["competitions"][0]["flags"]["recent_results"])

    def test_ambiguous_mapping_is_not_audited(self):
        api = FakeAPI([])
        rep = self.run_audit(api, [comp("ENG1", "England", 2, "premier league")])
        row = rep["competitions"][0]
        self.assertEqual(row["mapping"], "ambiguous")
        self.assertFalse(row["covered"])
        self.assertNotIn("samples", row)

    def test_config_has_exactly_30_european_codes(self):
        data = json.load(open(audit.CONFIG, encoding="utf-8"))["competitions"]
        self.assertEqual(len(data), 30)
        self.assertEqual(len({c["code"] for c in data}), 30)

    def test_main_requires_secret(self):
        old = os.environ.pop("BSD_API_KEY", None)
        try:
            with self.assertRaises(SystemExit) as ctx:
                audit.main(["/dev/null"])
            self.assertEqual(str(ctx.exception), "BSD_SECRET_MISSING")
        finally:
            if old is not None:
                os.environ["BSD_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()


class SchemaTests(unittest.TestCase):
    def test_team_ids_from_flat_and_side_fields_only(self):
        self.assertEqual(audit.ref_id({"home_team": "X", "home_team_id": 7}, "home_team"), 7)
        self.assertEqual(audit.ref_id({"home": {"id": 8, "name": "X"}}, "home_team"), 8)
        self.assertEqual(audit.ref_id({"teams": {"away": {"id": 9}}}, "away_team"), 9)
        self.assertIsNone(audit.ref_id({"home_team": "X"}, "home_team"))
        self.assertIsNone(audit.ref_id({"home_team": {"id": "7"}}, "home_team"))

    def test_shape_has_no_values(self):
        sh = audit.shape({"id": 1, "home_team": {"id": 2, "name": "Secret FC"}})
        self.assertEqual(sh, {"home_team": {"id": "int", "name": "str"}, "id": "int"})
        self.assertNotIn("Secret", json.dumps(sh))

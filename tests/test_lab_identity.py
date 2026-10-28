"""Fail-closed CORE_NAME identity: real provider name pairs and ambiguity guards.

No network. Real pairs come from the 27/10/2026 unresolved FT backlog.
"""
import unittest
from datetime import datetime, timezone

from h1lab.bsd import ROOT
from h1lab.lab_bsd_search import BSDDateFallback, summary
from h1lab.lab_espn import ESPNResults
from h1lab.lab_identity import CORE, EXACT, core_tokens, select_event, side_level
from h1lab.lab_results import reconcile

REAL_PAIRS = [  # AsianOdds name, provider name
    ("Roma", "AS Roma"), ("Calcio Como", "Como"),
    ("Union Berlin", "1. FC Union Berlin"), ("1. FC Köln", "FC Cologne"),
    ("AA Argentinos Juniors", "Argentinos Juniors"),
    ("CS Independiente Rivadavia", "Independiente Rivadavia"),
    ("FK Austria Wien", "Austria Vienna"),
]


def names(ev):
    return ev["h"], ev["a"]


def ko(ev):
    return datetime.fromisoformat(ev["t"])


def ev(h, a, t="2026-10-27T19:45:00+00:00"):
    return {"h": h, "a": a, "t": t}


SIG = {"match_key": "2026-10-27,240,227", "home": "Roma", "away": "Cagliari",
       "kickoff_utc": "2026-10-27T19:45:00+00:00"}


class SideRules(unittest.TestCase):
    def test_real_backlog_pairs_match_by_core_name(self):
        for a, b in REAL_PAIRS:
            self.assertEqual(side_level(a, b), CORE, (a, b))

    def test_exact_stays_exact(self):
        self.assertEqual(side_level("Cagliari", "Cagliari"), EXACT)

    def test_never_subsets_or_qualifier_mismatch(self):
        for a, b in [("Aston Villa FC U21", "Aston Villa"), ("Real Madrid", "Real Madrid Castilla"),
                     ("Benfica", "Benfica B"), ("Chelsea", "Chelsea Women"),
                     ("Inter Milano U23", "Inter"), ("FC", "AC"),
                     ("Mersin Idmanyurdu SK", "Icel Idmanyurdu Spor")]:
            self.assertIsNone(side_level(a, b), (a, b))

    def test_qualifier_synonyms(self):
        self.assertEqual(core_tokens("Ludogorets Razgrad B"), core_tokens("Ludogorets Razgrad II"))
        self.assertEqual(core_tokens("Aston Villa U-21"), core_tokens("Aston Villa FC U21"))


class EventSelection(unittest.TestCase):
    def test_unique_core_match(self):
        chosen, level, why = select_event(SIG, [ev("AS Roma", "Cagliari"), ev("Torino", "Como")], names, ko)
        self.assertEqual((level, why), (CORE, "identity_core_name"))
        self.assertEqual(chosen["h"], "AS Roma")

    def test_outside_window_rejected(self):
        self.assertIsNone(select_event(SIG, [ev("AS Roma", "Cagliari", "2026-10-27T22:00:00+00:00")], names, ko)[0])

    def test_reversed_order_rejected(self):
        r = select_event(SIG, [ev("Cagliari", "AS Roma")], names, ko)
        self.assertEqual(r[2], "identity_reversed_order_candidate")

    def test_two_core_candidates_rejected(self):
        r = select_event(SIG, [ev("AS Roma", "Cagliari"), ev("Roma", "Cagliari Calcio")], names, ko)
        self.assertIn(r[2], ("identity_ambiguous_exact", "identity_ambiguous_core"))
        self.assertIsNone(r[0])

    def test_side_collision_rejected(self):
        # Same core club appears in another event of the window: refuse.
        r = select_event(SIG, [ev("AS Roma", "Cagliari"), ev("Lazio", "AS Roma")], names, ko)
        self.assertEqual(r[2], "identity_side_collision")


def espn_event(home, away, hs="3", aw="2", kickoff="2026-10-27T19:45:00Z", eid="401874780"):
    return {"id": eid, "date": kickoff,
            "status": {"period": 2, "type": {"name": "STATUS_FULL_TIME", "description": "Full Time",
                                            "detail": "FT", "completed": True}},
            "competitions": [{"competitors": [
                {"homeAway": "home", "score": hs, "team": {"displayName": home}},
                {"homeAway": "away", "score": aw, "team": {"displayName": away}}]}]}


class ESPNCoreName(unittest.TestCase):
    def test_roma_recovered_with_provenance(self):
        p = ESPNResults({SIG["match_key"]: "Italy Serie A"},
                        fetch=lambda url: [espn_event("AS Roma", "Cagliari"),
                                           espn_event("Torino", "Como", "1", "0", eid="401874786")])
        result, reason = p.lookup(SIG)
        self.assertEqual(reason, "verified_espn_ft_core_name")
        self.assertEqual((result["home_goals"], result["away_goals"], result["identity_match"]), (3, 2, CORE))
        self.assertTrue(result["source"].endswith("event=401874780"))
        self.assertEqual(p.summary()["confirmed_in_run"], 1)

    def test_early_utc_kickoff_also_reads_previous_us_day(self):
        sig = dict(SIG, kickoff_utc="2026-10-28T02:00:00+00:00", match_key="2026-10-28,1,2")
        urls = []

        def fetch(url):
            urls.append(url)
            return [espn_event("AS Roma", "Cagliari", kickoff="2026-10-28T02:00Z")] if "20261027" in url else []
        p = ESPNResults({sig["match_key"]: "Italy Serie A"}, fetch=fetch)
        self.assertEqual(p.lookup(sig)[1], "verified_espn_ft_core_name")
        self.assertEqual(len(urls), 2)

    def test_core_match_still_rejects_extra_time(self):
        e = espn_event("AS Roma", "Cagliari")
        e["status"]["type"]["description"] = "After Extra Time"
        p = ESPNResults({SIG["match_key"]: "Italy Serie A"}, fetch=lambda url: [e])
        self.assertIsNone(p.lookup(SIG)[0])


def bsd_event(eid, home, away, score=(5, 0)):
    return {"id": eid, "home_team": {"name": home}, "away_team": {"name": away},
            "event_date": "2026-10-27T19:45:00+00:00", "status": "finished",
            "home_score": score[0], "away_score": score[1]}


class BSDCoreName(unittest.TestCase):
    SIG = {"match_key": "2026-10-27,226,1739", "home": "1. FC Köln", "away": "Union Berlin",
           "kickoff_utc": "2026-10-27T19:45:00+00:00"}

    def test_same_list_no_extra_list_request(self):
        calls = []

        def fetch(url, token):
            calls.append(url)
            if url == ROOT + "602348/":
                return bsd_event(602348, "1. FC Köln", "1. FC Union Berlin")
            return {"results": [bsd_event(602348, "1. FC Köln", "1. FC Union Berlin"),
                                bsd_event(9, "Hamburg SV", "Eintracht Frankfurt")], "next": None}
        f = BSDDateFallback(token="t", fetch=fetch, primary=lambda *a, **k: (None, "bsd_no_exact_match"))
        result, reason = f.lookup(self.SIG)
        self.assertEqual(reason, "verified_bsd_ft_via_date_core_name")
        self.assertEqual((result["home_goals"], result["identity_match"]), (5, CORE))
        self.assertEqual(summary(f)["date_list_requests"], 1)
        self.assertEqual(summary(f)["core_name_results_recovered"], 1)

    def test_detail_with_different_names_rejected(self):
        def fetch(url, token):
            if url.endswith("/602348/"):
                return bsd_event(602348, "Köln II", "1. FC Union Berlin")
            return {"results": [bsd_event(602348, "1. FC Köln", "1. FC Union Berlin")], "next": None}
        f = BSDDateFallback(token="t", fetch=fetch, primary=lambda *a, **k: (None, "bsd_no_exact_match"))
        self.assertEqual(f.lookup(self.SIG)[1], "bsd_date_core_detail_name_changed")


class LedgerProvenance(unittest.TestCase):
    def test_core_name_recorded_in_ledger(self):
        st = {"alerts": [dict(SIG, competition="Italy Serie A")], "signals": []}
        found = {"match_key": SIG["match_key"], "status": "final", "home_goals": 3, "away_goals": 2,
                 "source": "https://site.api.espn.com/x", "identity_match": CORE}
        ledger, report, n = reconcile(st, [], {"schema_version": 1, "matches": {}},
                                      now=datetime(2026, 10, 28, 8, tzinfo=timezone.utc),
                                      bsd_lookup=lambda s: (None, "x"), tsdb_lookup=lambda s: (None, "x"),
                                      espn_lookup=lambda s: (found, "verified_espn_ft_core_name"))
        row = ledger["matches"][SIG["match_key"]]
        self.assertEqual(row["status"], "FINAL")
        self.assertEqual(row["result"]["identity_match"], CORE)


if __name__ == "__main__":
    unittest.main()

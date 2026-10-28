"""Historical FT date allocation and confirmed event crosswalk: no HTTP."""
import unittest
from datetime import datetime, timezone
from h1lab.lab_ft_rotation import choose_days, advance
from h1lab.lab_ft_crosswalk import build_registry, event_id
from h1lab.lab_results import reconcile

NOW = datetime(2026, 10, 28, 21, tzinfo=timezone.utc)


class RotationTests(unittest.TestCase):
    def test_historical_date_rotates_after_actual_attempt(self):
        matches = {
            "old": {"kickoff_utc": "2026-10-25T16:00:00+00:00"},
            "middle": {"kickoff_utc": "2026-10-26T16:00:00+00:00"},
            "recent": {"kickoff_utc": "2026-10-27T16:00:00+00:00"},
        }
        journal = {"schema_version":1,"providers":{}}
        keys = list(matches)
        first = choose_days(keys,matches,journal,NOW,{"goal","openfoot","api_football"})
        self.assertEqual(first["goal"],["2026-10-25","2026-10-26"])
        self.assertEqual(first["openfoot"],["2026-10-25","2026-10-26"])
        self.assertEqual(len(first["api_football"]),3)
        journal = advance(journal,first,{
            "goal":first["goal"],"openfoot":first["openfoot"],
            "api_football":first["api_football"]},NOW)
        later = choose_days(keys,matches,journal,NOW,{"goal"})
        self.assertEqual(later["goal"][0],"2026-10-27")
        self.assertEqual(journal["providers"]["goal"]["2026-10-25"]["requests"],1)

    def test_request_not_in_allocated_dates_is_rejected(self):
        plan={"goal":["2026-10-27"],"openfoot":[],"api_football":[]}
        with self.assertRaises(ValueError):
            advance({"schema_version":1,"providers":{}},plan,
                    {"goal":["2026-10-26"]},NOW)

    def test_disabled_provider_has_no_dates(self):
        x=choose_days(["a"],{"a":{"kickoff_utc":"2026-10-27T10:00:00+00:00"}},
                      {"schema_version":1,"providers":{}},NOW,set())
        self.assertEqual(x["goal"],[])
        self.assertEqual(x["api_football"],[])

    def test_global_free_tier_budget_stops_at_quota(self):
        matches={"day":{"kickoff_utc":"2026-10-27T10:00:00+00:00"}}
        journal={"schema_version":1,"providers":{},"usage":{
            "api_football":{"2026-10-28":90},
            "openfoot":{"2026-10-01":4499}}}
        result=choose_days(["day"],matches,journal,NOW,{"api_football","openfoot"})
        self.assertEqual(result["api_football"],[])
        self.assertEqual(result["openfoot"],["2026-10-27"])
        updated=advance(journal,result,{"openfoot":["2026-10-27"]},NOW)
        self.assertEqual(updated["usage"]["openfoot"]["2026-10-28"],1)
        self.assertEqual(choose_days(["day"],matches,updated,NOW,{"openfoot"})["openfoot"],[])

    def test_invalid_old_journal_fails_closed(self):
        with self.assertRaises(ValueError):
            choose_days([],{},{"schema_version":9},NOW,{"goal"})


class CrosswalkTests(unittest.TestCase):
    def test_confirmed_ids_across_providers_are_persisted(self):
        row={"status":"FINAL","home":"Home Women","away":"Away Women",
             "kickoff_utc":"2026-10-27T10:00:00+00:00",
             "result":{"evidence":"bsd_and_goal","source":"https://sports.bzzoiro.com/api/v2/events/123/","home_goals":1,"away_goals":0},
             "verified_provider_sources":{
                 "bsd":{"source":"https://sports.bzzoiro.com/api/v2/events/123/"},
                 "goal":{"source":"https://api.goal-api.com/v1/fixtures/4567"}}}
        registry=build_registry({"matches":{"k":row}})
        self.assertEqual(registry["confirmed_ids"],2)
        self.assertEqual(registry["collision_ids"],0)
        self.assertEqual(build_registry({"matches":{"k":row}},registry),registry)

    def test_generic_date_link_and_unconfirmed_match_never_become_ids(self):
        row={"status":"PENDING","home":"Home","away":"Away",
             "kickoff_utc":"2026-10-27T10:00:00+00:00",
             "result":{"evidence":"goal_only","source":"https://api.goal-api.com/v1/fixtures/1234"}}
        self.assertEqual(build_registry({"matches":{"p":row}})["confirmed_ids"],0)
        self.assertIsNone(event_id("openfoot","https://openfootapi.com/v1/matches?date=2026-10-27"))

    def test_duplicate_provider_id_is_quarantined_not_overwritten(self):
        source="https://api.goal-api.com/v1/fixtures/4567"
        base={"status":"FINAL","home":"Home A","away":"Away A",
              "kickoff_utc":"2026-10-27T10:00:00+00:00",
              "result":{"evidence":"goal_only","source":source}}
        both={"matches":{"a":base,"b":dict(base,home="Home B")}}
        reg=build_registry(both)
        self.assertEqual(reg["collision_ids"],1)
        self.assertEqual(reg["entries"]["goal:4567"]["status"],"COLLISION_REVIEW")

    def test_new_verified_score_cannot_reuse_other_game_event_id(self):
        def row(key,name):
            return {"match_key":key,"home":name,"away":"Away",
                    "kickoff_utc":"2026-10-27T10:00:00+00:00"}
        old=row("old","Old Home")
        new=row("new","New Home")
        link="https://api.goal-api.com/v1/fixtures/4567"
        previous={"schema_version":1,"matches":{"old":{
            **old, "status":"FINAL", "attempts":1,
            "result":{"evidence":"goal_only","source":link,"home_goals":1,"away_goals":0}}}}
        def ok(signal):
            return {"match_key":signal["match_key"],"status":"final",
                    "home_goals":1,"away_goals":0,"source":link},"verified_goal_ft"
        ledger, _, checked = reconcile(
            {"alerts":[old,new],"signals":[]}, [], previous, now=NOW,
            bsd_lookup=lambda s:(None,"no_match"),
            tsdb_lookup=lambda s:(None,"no_match"),
            goal_lookup=ok,lookup_source_version=11,max_checks=30)
        self.assertEqual(checked,1)
        self.assertEqual(ledger["matches"]["old"]["status"],"FINAL")
        self.assertEqual(ledger["matches"]["new"]["status"],"PENDING")
        self.assertEqual(ledger["matches"]["new"]["reason"],"provider_event_id_collision_review")
        self.assertNotIn("result",ledger["matches"]["new"])


if __name__ == "__main__":
    unittest.main()

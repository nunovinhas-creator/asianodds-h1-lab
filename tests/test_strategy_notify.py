"""Five pinned V5 Telegram strategies: exact market predicates, no silent fallback."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab.bot import BotDeliveryError
from h1lab.strategy_notify import (STRATEGIES, _validate_catalogue, candidate_matches,
                                   empty_ledger, message_for_game, process, run)
from h1lab.timeline import collect_timelines

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)
KO = NOW + timedelta(hours=8)
REPO = Path(__file__).resolve().parents[1]


def original(num=1, *, at=None, ko=None, match="2026-10-29,11,22", total_line=3.25):
    at = at or NOW
    ko = ko or KO
    return {"event_id": f"test:{num}", "message_id": num, "match_key": match,
            "home": "Porto", "away": "Benfica", "kickoff_utc": ko.isoformat(),
            "observed_at": at.isoformat(), "market": "total", "competition": "Test",
            "total_before": total_line, "total_after": total_line,
            "over_before": 1.9, "under_before": 1.9,
            "over_after": 1.9, "under_after": 1.9, "source_url": ""}


def v4(a, *, include_ah=True, include_total=True, ah_from=-1.0, ah_to=-0.75):
    markets = {}
    if include_total:
        markets["total"] = {
            "before": {"line": a["total_before"], "over_price": a["over_before"],
                       "under_price": a["under_before"]},
            "after": {"line": a["total_after"], "over_price": a["over_after"],
                      "under_price": a["under_after"]}}
    if include_ah:
        markets["asian_handicap"] = {
            "before": {"line": ah_from, "home_price": 1.9, "away_price": 1.9},
            "after": {"line": ah_to, "home_price": 1.9, "away_price": 1.9}}
    return {"event_id": a["event_id"], "observed_at": a["observed_at"],
            "match_key": a["match_key"], "kickoff_utc": a["kickoff_utc"],
            "trigger_market": "total", "markets": markets}


def research():
    return {"generated_at": NOW.isoformat(), "patterns": [
        {"id": s["id"], "definition": s["definition"],
         "outcomes": {s["market"]: {"hits": 13, "known": 16, "rate": 0.8125,
                                    "reference_known": 143, "reference_rate": 0.503}}}
        for s in STRATEGIES if s["number"] == 1],
        "combinations_top": [
            {"id": s["id"], "definition": s["definition"], "outcomes": {
                "OVER_2_5": {"hits": 10, "known": 13, "rate": 10/13,
                             "reference_known": 146, "reference_rate": 0.514},
                "BTTS_YES": {"hits": 10, "known": 13, "rate": 10/13,
                             "reference_known": 146, "reference_rate": 0.514}}}
            for s in STRATEGIES if s["number"] in (2, 4, 5)]}


def candidates(alerts, markets, now=NOW):
    timelines, issues, excluded = collect_timelines(alerts, markets)
    assert not excluded, excluded
    return candidate_matches(timelines, now, research())


class FiveStrategyTests(unittest.TestCase):
    def test_exact_five_pinned_market_rules(self):
        self.assertEqual([(s["number"], s["market"]) for s in STRATEGIES],
                         [(1, "OVER_2_5"), (2, "OVER_2_5"), (3, "BTTS_YES"),
                          (4, "OVER_2_5"), (5, "OVER_2_5")])
        self.assertEqual(len({(s["id"], s["market"]) for s in STRATEGIES}), 5)

    def test_single_future_match_can_match_all_five_without_duplicate_game_message(self):
        a = original()
        rows = candidates([a], [v4(a)])
        self.assertEqual(len(rows), 1)
        self.assertEqual([r["number"] for r in rows[0]["rules"]], [1, 2, 3, 4, 5])
        msg = message_for_game(rows[0], rows[0]["rules"])
        self.assertIn("Porto vs Benfica", msg)
        self.assertIn("🎯 E1 · OVER 2,5 GOLOS", msg)
        self.assertIn("🎯 E3 · AMBAS MARCAM", msg)
        self.assertIn("13/16 (81,3%)", msg)  # explicit half-up to match user-facing V5
        self.assertNotIn("Taxas históricas", msg)
        self.assertNotIn("🆔", msg)
        self.assertLess(len(msg), 950)
        sent = []
        ledger, stats = process(rows, empty_ledger(NOW), NOW,
                                lambda text: sent.append(text) or 437, True)
        self.assertEqual((stats["games_sent"], stats["strategy_receipts"]), (1, 5))
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(ledger["entries"]), 5)
        self.assertEqual({e["telegram_message_id"] for e in ledger["entries"].values()}, {437})
        ledger, stats = process(rows, ledger, NOW+timedelta(minutes=1),
                                lambda text: self.fail("duplicate sent"), True)
        self.assertEqual(stats["games_sent"], 0)
        self.assertEqual(stats["already_notified"], 5)

    def test_ah_requires_v4_explicit_not_legacy_guess(self):
        a = original()
        self.assertEqual([s["number"] for s in candidates([a], [v4(a, include_ah=False)])[0]["rules"]],
                         [2, 3, 4, 5])
        self.assertEqual([s["number"] for s in candidates([a], [v4(a, include_total=False)])[0]["rules"]],
                         [1])

    def test_first_lead_less_than_six_hours_excludes_2_3_5(self):
        a = original(at=KO-timedelta(hours=4))
        self.assertEqual([s["number"] for s in candidates([a], [v4(a)], now=NOW+timedelta(hours=5))[0]["rules"]],
                         [1, 4])

    def test_only_future_kickoffs_are_notified_never_past_games(self):
        a = original(ko=NOW-timedelta(minutes=1), at=NOW-timedelta(hours=8))
        self.assertEqual(candidates([a], [v4(a)]), [])
        b = original(at=NOW+timedelta(minutes=4))
        # A timestamp from the future must not be included as a live detection.
        self.assertEqual(candidates([b], [v4(b)]), [])
        c = original()
        self.assertEqual(len(candidates([c], [v4(c)])), 1)  # already detected, still upcoming

    def test_weakening_reverses_strategy_four_in_two_distinct_episodes(self):
        a = original(1, at=KO-timedelta(hours=9))
        b = original(2, at=KO-timedelta(hours=8))
        a.update(total_before=3.25, total_after=3.75)
        b.update(total_before=3.25, total_after=3.25)
        rows = candidates([a,b], [v4(a),v4(b)], now=NOW+timedelta(hours=1))
        self.assertEqual(len(rows), 1)
        self.assertNotIn(4, [r["number"] for r in rows[0]["rules"]])

    def test_all_eligible_games_are_notified_without_six_message_cap(self):
        a = original()
        base = candidates([a], [v4(a)])[0]
        rows = []
        for i in range(15):
            r = copy.deepcopy(base)
            r["match_key"] = "today-" + str(i)
            r["kickoff_utc"] = (KO + timedelta(minutes=i)).isoformat()
            rows.append(r)
        messages=[]
        ledger, first = process(rows, empty_ledger(NOW), NOW,
                                lambda msg: messages.append(msg) or (100 + len(messages)), True)
        self.assertEqual(first["games_sent"],15)
        self.assertEqual(len(ledger["entries"]),75)
        ledger, second = process(rows, ledger, NOW+timedelta(minutes=5),
                                 lambda msg: messages.append(msg) or (100 + len(messages)),True)
        self.assertEqual(second["games_sent"],0)
        self.assertEqual(len(messages),15)
        ledger, third = process(rows,ledger,NOW+timedelta(minutes=10),
                                lambda msg: self.fail("duplicate"),True)
        self.assertEqual(third["games_sent"],0)

    def test_future_beyond_12h_deferred_until_in_alert_window(self):
        a=original(ko=NOW+timedelta(hours=13))
        rows=candidates([a],[v4(a)])
        ledger,stats=process(rows,empty_ledger(NOW),NOW,
                             lambda msg:self.fail("premature"),True)
        self.assertEqual(stats["deferred_not_imminent"],1)
        self.assertEqual(len(ledger["entries"]),0)
        ledger,stats=process(rows,ledger,NOW+timedelta(hours=2),lambda _:987,True)
        self.assertEqual(stats["games_sent"],1)

    def test_no_bot_configuration_never_consumes_eligible_receipts(self):
        a=original(); rows=candidates([a], [v4(a)])
        ledger, stats=process(rows, empty_ledger(NOW), NOW,
                             lambda _: self.fail("should not send"), False)
        self.assertEqual(stats["unconfigured"],5)
        self.assertEqual(ledger["entries"],{})

    def test_uncertain_delivery_is_manual_review_and_not_retried(self):
        a=original(); rows=candidates([a], [v4(a)])
        calls=[]
        def uncertain(msg):
            calls.append(msg)
            raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN")
        ledger, stats=process(rows, empty_ledger(NOW), NOW, uncertain, True)
        self.assertEqual(stats["failed"],1)
        self.assertTrue(all(e["status"]=="delivery_uncertain_manual_review"
                            for e in ledger["entries"].values()))
        process(rows,ledger,NOW+timedelta(minutes=1),uncertain,True)
        self.assertEqual(len(calls),1)

    def test_later_new_strategy_same_match_notifies_only_new_rule(self):
        a=original(); first=candidates([a],[v4(a, include_ah=False)])
        ledger,_=process(first, empty_ledger(NOW), NOW, lambda _: 123, True)
        updated=candidates([a],[v4(a)])
        sent=[]
        ledger,stats=process(updated,ledger,NOW+timedelta(minutes=1),
                             lambda msg: sent.append(msg) or 124,True)
        self.assertEqual(stats["strategy_receipts"],1)
        self.assertIn("🎯 E1 ·", sent[0])
        self.assertNotIn("🎯 E2 ·", sent[0])

    def test_catalogue_drift_or_stale_report_fails_loudly(self):
        good=research()
        self.assertTrue(_validate_catalogue(good,NOW))
        bad=copy.deepcopy(good)
        bad["patterns"][0]["definition"]={"op":"HAS","a":"G_LAST_LINE_HIGH"}
        with self.assertRaisesRegex(ValueError,"definition changed"):
            _validate_catalogue(bad,NOW)
        with self.assertRaisesRegex(ValueError,"recent valid"):
            _validate_catalogue(good,NOW+timedelta(hours=25))

    def test_real_published_v5_definitions_match_fixed_selection(self):
        path=REPO/"docs/lab/pattern-research.json"
        if not path.exists():self.skipTest("no published report")
        real=json.loads(path.read_text(encoding="utf-8"))
        at=datetime.fromisoformat(real["generated_at"])
        _validate_catalogue(real,at+timedelta(minutes=1))

    def test_workflow_switch_disables_generic_sender(self):
        text=(REPO/".github/workflows/collect.yml").read_text(encoding="utf-8")
        self.assertIn("python -m h1lab.strategy_notify",text)
        self.assertNotIn("run: python -m h1lab.pattern_notify",text)
        self.assertIn("git add data/strategy-notifications.json",text)

    def test_real_root_runner_does_not_send_or_create_legacy_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            report=root/"docs/lab/pattern-research.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps(research()),encoding="utf-8")
            a=original()
            with patch("h1lab.strategy_notify.read_sources",return_value=([a],[v4(a)],[])):
                state=run(root=root,now=NOW,sender=lambda _: 24,bot_enabled=True)
            self.assertEqual(len(state["entries"]),5)
            self.assertFalse((root/"data/pattern-notifications.json").exists())
            with patch("h1lab.strategy_notify.read_sources",return_value=([a],[v4(a)],[])):
                again=run(root=root,now=NOW+timedelta(minutes=1),
                          sender=lambda _: self.fail("duplicate"),bot_enabled=True)
            self.assertEqual(len(again["entries"]),5)


if __name__=="__main__":
    unittest.main()

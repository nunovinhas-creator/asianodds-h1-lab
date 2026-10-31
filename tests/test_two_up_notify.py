"""Second independent Telegram rule, first 3-move rule stays unchanged."""
import copy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab.bot import BotDeliveryError
from h1lab import two_up_notify as watch
from h1lab import three_moves_notify as old
from h1lab.timeline import collect_timelines

NOW = datetime(2026, 10, 31, 19, 55, tzinfo=timezone.utc)
KO = NOW + timedelta(hours=34)


def alert(i, before, after, *, match="fixture-1", ko=KO, at=None):
    at = at or NOW - timedelta(minutes=60 - i * 10)
    return {
        "event_id": "telegram:" + str(i), "message_id": i, "match_key": match,
        "home": "Casa", "away": "Fora", "kickoff_utc": ko.isoformat(),
        "observed_at": at.isoformat(), "market": "total",
        "total_before": before, "total_after": after,
        "over_before": 1.8, "under_before": 2.0,
        "over_after": 1.9, "under_after": 1.9,
    }


def v4(a):
    return {"event_id": a["event_id"], "match_key": a["match_key"],
            "observed_at": a["observed_at"], "kickoff_utc": a["kickoff_utc"],
            "trigger_market": "total", "markets": {"total": {
                "before": {"line": a["total_before"], "over_price": a["over_before"],
                           "under_price": a["under_before"]},
                "after": {"line": a["total_after"], "over_price": a["over_after"],
                          "under_price": a["under_after"]},
            }}}


def lomza():
    return [alert(1, 3.25, 3.50), alert(2, 3.50, 3.75)]


def merlo():
    return [alert(1, 1.75, 2.00), alert(2, 2.00, 2.25),
            alert(3, 2.25, 2.25)]


def select(rows, markets=None, *, now=NOW):
    if markets is None:
        markets = [v4(x) for x in rows]
    timelines, issues, excluded = collect_timelines(rows, markets)
    assert not excluded, excluded
    return watch.candidates(timelines, now)


class TwoUpNotificationTests(unittest.TestCase):
    def test_lomza_two_distinct_up_moves_and_half_line(self):
        result = select(lomza())
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual((row["up_movements"],row["first_total"],row["last_total"],
                          row["net_line_rise"]),(2,3.25,3.75,0.5))
        msg = watch.message_for_game(row)
        self.assertIn("2+ SUBIDAS SEGUIDAS",msg)
        self.assertIn("Casa vs Fora",msg)
        self.assertIn("3,25 → 3,75",msg)
        self.assertIn("+0,50",msg)
        self.assertNotIn("3+ MOVIMENTOS CONFIRMADOS",msg)

    def test_merlo_third_flat_message_does_not_block_or_count(self):
        result = select(merlo())
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["up_movements"],2)
        self.assertEqual(result[0]["net_line_rise"],0.5)

    def test_past_match_future_alert_and_conflicting_kickoff_excluded(self):
        past = [alert(1,3.25,3.50,ko=NOW-timedelta(minutes=2)),
                alert(2,3.50,3.75,ko=NOW-timedelta(minutes=2))]
        self.assertEqual(select(past), [])
        future = lomza()
        future[1]["observed_at"]=(NOW+timedelta(minutes=1)).isoformat()
        self.assertEqual(select(future), [])
        mixed = lomza()
        mixed[1]["kickoff_utc"]=(KO+timedelta(hours=1)).isoformat()
        self.assertEqual(select(mixed), [])

    def test_one_up_not_enough_even_when_other_alerts_flat(self):
        self.assertEqual(select([alert(1,3.25,3.5),alert(2,3.5,3.5)]),[])

    def test_no_v4_proof_no_notification(self):
        rows=lomza()
        self.assertEqual(select(rows, [v4(rows[0])]), [])
        self.assertEqual(select(rows, []), [])

    def test_up_up_down_is_rejected_as_reversal(self):
        rows=lomza()+[alert(3,3.75,3.5)]
        self.assertEqual(select(rows), [])

    def test_up_down_up_is_rejected_even_when_net_rise_positive(self):
        rows=[alert(1,2.5,3.0),alert(2,3.0,2.75),alert(3,2.75,3.25)]
        self.assertEqual(select(rows), [])

    def test_weak_two_up_below_half_line_rejected(self):
        self.assertEqual(select([alert(1,3.0,3.1),alert(2,3.1,3.25)]), [])

    def test_close_duplicates_do_not_satisfy_two_independent(self):
        rows=lomza()
        rows[1]=alert(2,3.25,3.5,
                      at=NOW-timedelta(minutes=50)+timedelta(seconds=3))
        rows[0]["observed_at"]=(NOW-timedelta(minutes=50)).isoformat()
        self.assertEqual(select(rows), [])

    def test_far_identical_repeat_cannot_be_second_move(self):
        rows=[alert(1,3.0,3.25),alert(2,3.0,3.25)]
        self.assertEqual(select(rows), [])

    def test_unobserved_between_message_gap_does_not_count_as_second_rise(self):
        rows=[alert(1,3.0,3.25),alert(2,3.5,3.5)]
        self.assertEqual(select(rows), [])

    def test_works_for_tomorrow_beyond_twelve_hours(self):
        self.assertEqual(len(select(lomza())),1)
        self.assertGreater((KO-NOW).total_seconds(),12*3600)

    def test_separate_ledgers_keep_original_three_move_contract(self):
        self.assertNotEqual(watch.LEDGER, old.LEDGER)
        self.assertNotEqual(watch.RULE_VERSION,old.RULE_VERSION)
        self.assertEqual(old.MIN_MOVES,3)
        self.assertEqual(old.candidates(
            collect_timelines(lomza(),[v4(x) for x in lomza()])[0],NOW),[])
        self.assertEqual(len(select(lomza())),1)

    def test_many_games_send_once_each_with_separate_receipts(self):
        original=select(lomza())[0]
        rows=[]
        for i in range(12):
            row=copy.deepcopy(original)
            row["match_key"]="other-"+str(i)
            rows.append(row)
        sent=[]
        ledger,counts=watch.process(rows,watch.empty_ledger(NOW),NOW,
                                    lambda m:sent.append(m) or len(sent),True)
        self.assertEqual(counts["sent"],12)
        self.assertEqual(len(ledger["entries"]),12)
        self.assertTrue(all("rule_version" in item for item in ledger["entries"].values()))
        ledger,again=watch.process(rows,ledger,NOW+timedelta(minutes=1),
                                  lambda _:self.fail("duplicate two-up"),True)
        self.assertEqual(again["sent"],0)
        self.assertEqual(again["already_notified"],12)

    def test_unknown_delivery_never_retried(self):
        rows=select(lomza())
        messages=[]
        def sender(msg):
            messages.append(msg)
            raise BotDeliveryError("unknown")
        ledger,stats=watch.process(rows,watch.empty_ledger(NOW),NOW,sender,True)
        self.assertEqual(stats["uncertain"],1)
        watch.process(rows,ledger,NOW+timedelta(minutes=1),sender,True)
        self.assertEqual(len(messages),1)

    def test_unconfigured_and_started_do_not_consume_receipts(self):
        rows=select(lomza())
        ledger,stats=watch.process(rows,watch.empty_ledger(NOW),NOW,
                                   lambda _:self.fail("no config"),False)
        self.assertEqual(stats["unconfigured"],1)
        self.assertEqual(ledger["entries"],{})
        ledger,stats=watch.process(rows,ledger,NOW,
                                   lambda _:self.fail("already started"),True,
                                   clock=lambda:KO+timedelta(seconds=1))
        self.assertEqual(stats["expired"],1)

    def test_dry_run_does_not_change_notification_ledgers(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=lomza()
            with patch.object(watch,"read_sources",return_value=(rows,[v4(x) for x in rows],[])):
                watch.run(root=tmp,now=NOW,sender=lambda _:self.fail("dry run sends"),
                          bot_enabled=True,dry_run=True)
            self.assertFalse((Path(tmp)/watch.LEDGER).exists())
            self.assertFalse((Path(tmp)/old.LEDGER).exists())

    def test_production_workflow_preserves_first_sender_and_adds_second(self):
        root=Path(__file__).resolve().parents[1]
        wf=(root/".github/workflows/collect.yml").read_text(encoding="utf-8")
        self.assertEqual(wf.count("run: python -m h1lab.three_moves_notify"),1)
        self.assertEqual(wf.count("run: python -m h1lab.two_up_notify"),1)
        self.assertIn("git add data/three-total-moves-notifications.json",wf)
        self.assertIn("git add data/two-up-total-notifications.json",wf)
        self.assertNotIn("run: python -m h1lab.t05_notify",wf)
        self.assertNotIn("run: python -m h1lab.e4_notify",wf)


if __name__=="__main__":
    unittest.main()

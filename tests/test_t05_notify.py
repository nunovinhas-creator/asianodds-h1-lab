"""T05: prospective alert is independent of FT, E4 and result backfill."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from pathlib import Path

from h1lab.bot import BotDeliveryError
from h1lab import t05_notify as t05

NOW = datetime(2026, 10, 30, 13, 40, tzinfo=timezone.utc)


def game(key="g1", hours=3):
    return {"match_key":key, "match_label":"Porto vs Benfica",
            "kickoff_utc":(NOW+timedelta(hours=hours)).isoformat(),
            "observed_through":NOW.isoformat(), "candidate_id":t05.CANDIDATE_ID,
            "fingerprint":"f"}


class T05Tests(unittest.TestCase):
    def test_frozen_criterion_and_historical_message(self):
        self.assertEqual(t05.CODES,(
            "G_FIRST_LEAD_LT_6H","M_1X2_HOME_PROB_UP","M_TOTAL_LINE_UP"))
        self.assertEqual(len(t05.EXAMPLES),3)
        message=t05.historical_message()
        for name,score in t05.EXAMPLES:
            self.assertIn(name,message)
            self.assertIn(score,message)
        self.assertIn("NÃO É ALERTA PRÉ-JOGO",message)
        self.assertIn("NÃO validada",message)

    def test_entry_message_short_and_honest(self):
        msg=t05.message_for_game(game())
        self.assertIn("T05",msg)
        self.assertIn("OVER 2,5",msg)
        self.assertIn("Porto vs Benfica",msg)
        self.assertIn("não validado",msg)
        self.assertNotIn("100%",msg)

    def test_before_after_both_markets_must_be_explicit_v4(self):
        event={"observed_at":NOW.isoformat(),"snapshots":{
            "total":{"origin":"V4_EXPLICIT"},
            "one_x_two":{"origin":"V4_EXPLICIT"}}}
        ko=NOW+timedelta(hours=2)
        with patch.object(t05,"message_metrics",return_value={
                "patterns":["M_1X2_HOME_PROB_UP","M_TOTAL_LINE_UP"]}):
            self.assertTrue(t05._has_explicit_v4({"events":[event]},NOW,ko))
            event["snapshots"]["one_x_two"]["origin"]="H1_INFERRED"
            self.assertFalse(t05._has_explicit_v4({"events":[event]},NOW,ko))
            event["snapshots"]["one_x_two"]["origin"]="V4_EXPLICIT"
            event["observed_at"]=(NOW+timedelta(minutes=2)).isoformat()
            self.assertFalse(t05._has_explicit_v4({"events":[event]},NOW,ko))
            event["observed_at"]=(NOW+timedelta(hours=2)).isoformat()
            self.assertFalse(t05._has_explicit_v4({"events":[event]},NOW,ko))

    def test_future_candidates_are_12h_and_require_t05_without_ft(self):
        ko=(NOW+timedelta(hours=3)).isoformat()
        timeline={"identity":{"kickoff_utc":[ko]},"match_key":"g1","events":[]}
        row={"match_key":"g1","match_label":"Home vs Away","kickoff_utc":ko,
             "features":{"feature_version":1,"decision_at":NOW.isoformat(),
                         "fingerprint":"f","patterns":list(t05.CODES)},
             "quality_context":{"messages":[{"total":{"status":"USABLE"},
                                              "one_x_two":{"status":"USABLE"}}]}}
        with (patch.object(t05,"_has_explicit_v4",return_value=True),
              patch.object(t05,"make_row",return_value=(row,None)) as build):
            selected=t05.candidates([timeline],NOW)
            self.assertEqual(len(selected),1)
            self.assertEqual(selected[0]["match_key"],"g1")
            self.assertEqual(selected[0]["candidate_id"],t05.CANDIDATE_ID)
            self.assertEqual(build.call_args.kwargs["known_at"],NOW.isoformat())
            with self.assertRaisesRegex(ValueError,"T05_DUPLICATE_MATCH_KEY"):
                t05.candidates([timeline,timeline],NOW)
        with patch.object(t05,"_has_explicit_v4",return_value=True):
            past={**timeline,"identity":{"kickoff_utc":[(NOW-timedelta(hours=1)).isoformat()]}}
            distant={**timeline,"identity":{"kickoff_utc":[(NOW+timedelta(hours=13)).isoformat()]}}
            self.assertEqual(t05.candidates([past,distant],NOW),[])
        with (patch.object(t05,"_has_explicit_v4",return_value=True),
              patch.object(t05,"make_row",return_value=(row,None)),
              patch.object(t05,"hypothesis_value",return_value=None)):
            self.assertEqual(t05.candidates([timeline],NOW),[])

    def test_activation_sends_one_historical_recap_then_future_without_duplication(self):
        calls=[]
        def sender(message):
            calls.append(message)
            return len(calls)
        data=t05.empty_ledger(NOW)
        data,stats=t05.process([game("a"),game("b")],data,NOW,sender,True)
        self.assertEqual((stats["historical_sent"],stats["future_sent"]),(1,2))
        self.assertEqual(len(calls),3)
        self.assertEqual(len(data["entries"]),3)
        data,stats=t05.process([game("a"),game("b")],data,NOW+timedelta(minutes=5),
                               lambda _:self.fail("duplicate"),True)
        self.assertEqual(stats["future_sent"],0)
        self.assertEqual(stats["historical_sent"],0)

    def test_not_configured_keeps_recap_and_games_pending(self):
        d,stats=t05.process([game()],t05.empty_ledger(NOW),NOW,
                            lambda _:self.fail("not configured"),False)
        self.assertEqual(stats["unconfigured"],2)
        self.assertEqual(d["entries"],{})

    def test_time_window_and_now_clock_prevent_post_kickoff(self):
        data=t05.empty_ledger(NOW)
        data["entries"]["historical:2026-10-28-29"]={"status":"sent"}
        rows=[game("already",hours=-1),game("later",hours=14),game("soon",hours=1)]
        calls=[]
        data,stats=t05.process(rows,data,NOW,lambda m:calls.append(m) or 30,
                                True,clock=lambda: NOW+timedelta(hours=2))
        self.assertEqual(stats["expired"],1)
        self.assertEqual(stats["future_sent"],0)
        self.assertEqual(len(calls),0)

    def test_uncertain_telegram_send_never_retries(self):
        data=t05.empty_ledger(NOW)
        def fail(_):raise BotDeliveryError("uncertain")
        data,stats=t05.process([game()],data,NOW,fail,True)
        self.assertEqual(stats["uncertain"],2)
        data,stats=t05.process([game()],data,NOW+timedelta(minutes=5),
                  lambda _:self.fail("must never automatically retry"),True)
        self.assertEqual(stats["uncertain"],0)

    def test_workflow_preserves_existing_e4_and_persists_t05(self):
        wf=(Path(__file__).resolve().parents[1]/".github/workflows/collect.yml").read_text()
        self.assertIn("run: python -m h1lab.e4_notify",wf)
        self.assertIn("run: python -m h1lab.t05_notify",wf)
        self.assertIn("git add data/t05-notifications.json",wf)
        self.assertNotIn("run: python -m h1lab.strategy_notify",wf)


if __name__=="__main__":
    unittest.main()

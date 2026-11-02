"""E5 (P5-8bced1b27e) - Over 2,5: the only active MASTER BRAIN Telegram emitter."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import yaml

from h1lab import e5_notify as e5
from h1lab import telegram_delivery as delivery
from h1lab.bot import BotBlockedError, BotDeliveryError, BotRejectedError
from h1lab.telegram_block import BlockStore
from h1lab.timeline import collect_timelines

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)
KO = NOW + timedelta(hours=9)          # inside the 12-hour alert window


def setUpModule():
    global _TMP
    _TMP = tempfile.mkdtemp()
    os.environ["TG_DELIVERY_BLOCK_FILE"] = os.path.join(_TMP, "block.json")


def tearDownModule():
    os.environ.pop("TG_DELIVERY_BLOCK_FILE", None)
    shutil.rmtree(_TMP, ignore_errors=True)


def proxy_lambda(line, over, under):
    """Deterministic stand-in for the Poisson inversion: lambda == Over price.

    Only used to place the V5 net change EXACTLY on the 0.10 boundary; the V5 engine
    (message_metrics -> match_features -> net_dlam rounding) itself is unchanged.
    """
    return over


def message(i, over_before, over_after, *, at, ko=KO, match="2026-11-03,7", line=2.5,
            home="Casa", away="Fora"):
    return {"event_id": "telegram:%d" % i, "message_id": i, "match_key": match, "home": home,
            "away": away, "kickoff_utc": ko.isoformat(), "observed_at": at.isoformat(),
            "market": "total", "total_before": line, "total_after": line,
            "over_before": over_before, "under_before": 1.9,
            "over_after": over_after, "under_after": 1.9}


def v4(a, **override):
    row = {"event_id": a["event_id"], "match_key": a["match_key"], "observed_at": a["observed_at"],
           "kickoff_utc": a["kickoff_utc"], "trigger_market": "total",
           "markets": {"total": {
               "before": {"line": a["total_before"], "over_price": a["over_before"],
                          "under_price": a["under_before"]},
               "after": {"line": a["total_after"], "over_price": a["over_after"],
                         "under_price": a["under_after"]}}}}
    row.update(override)
    return row


def pair(net, *, lead=None, ko=KO, match="2026-11-03,7", second_at=None):
    """Two V4 messages; first at kickoff - lead (default NOW - 2h); net (proxy lambda) = first.before -> last.after."""
    first = message(1, 2.0, 2.0, at=(ko - lead) if lead else NOW - timedelta(hours=2), ko=ko,
                    match=match)
    second = message(2, 2.0, round(2.0 + net, 4), at=second_at or (NOW - timedelta(minutes=5)),
                     ko=ko, match=match)
    return [first, second]


def rows_for(alerts, markets=None, *, now=NOW, real_lambda=False):
    markets = [v4(a) for a in alerts] if markets is None else markets
    timelines, _, excluded = collect_timelines(alerts, markets)
    assert not excluded
    if real_lambda:
        return e5.evaluate_all(timelines, now)
    with patch("h1lab.pattern_features.implied_lambda", proxy_lambda):
        return e5.evaluate_all(timelines, now)


def research(now=NOW, hits=52, known=72):
    row = {"id": e5.PATTERN_ID, "definition": e5.DEFINITION,
           "outcomes": {"OVER_2_5": {"rate": hits / known, "known": known, "hits": hits}}}
    return {"generated_at": (now - timedelta(hours=1)).isoformat(), "patterns": [row],
            "combinations_top": []}


class Sender:
    def __init__(self, *results):
        self.results, self.messages = list(results), []

    def __call__(self, text):
        self.messages.append(text)
        result = self.results.pop(0) if self.results else 100 + len(self.messages)
        if isinstance(result, Exception):
            raise result
        return result


def process(rows, ledger=None, sender=None, now=NOW, persist=None, research_doc=None, **kw):
    sender = sender or Sender()
    ledger = ledger if ledger is not None else e5.empty_ledger(now)
    ledger, stats = e5.process(rows, ledger, now, sender, True, research=research_doc,
                               persist=persist, store=BlockStore(), **kw)
    return ledger, stats, sender


class E5RuleTests(unittest.TestCase):
    def setUp(self):
        BlockStore().clear()

    def one(self, alerts, **kw):
        rows = rows_for(alerts, **kw)
        self.assertEqual(len(rows), 1)
        return rows[0]

    # 1-3: net implied-goals change, strict boundary
    def test_net_plus_0_0999_is_eligible(self):
        row = self.one(pair(0.0999))
        self.assertEqual((row["state"], row["net_dlam"]), (e5.ELIGIBLE, 0.0999))

    def test_net_minus_0_0999_is_eligible(self):
        row = self.one(pair(-0.0999))
        self.assertEqual((row["state"], row["net_dlam"]), (e5.ELIGIBLE, -0.0999))

    def test_net_plus_0_1000_is_not_eligible(self):
        row = self.one(pair(0.1))
        self.assertEqual((row["state"], row["reason"], row["net_dlam"]),
                         (e5.NOT_E5, "VARIACAO_LIQUIDA_IGUAL_OU_SUPERIOR_A_0_10", 0.1))
        row = self.one(pair(-0.1))
        self.assertEqual(row["state"], e5.NOT_E5)

    def test_e5_is_not_e2_individual_moves_above_0_05_are_allowed(self):
        alerts = [message(1, 2.0, 2.3, at=NOW - timedelta(hours=3)),       # +0.30 in one message
                  message(2, 2.3, 2.05, at=NOW - timedelta(minutes=30))]   # -0.25: net +0.05
        row = self.one(alerts)
        self.assertEqual((row["state"], row["net_dlam"]), (e5.ELIGIBLE, 0.05))

    # 4-6: first-alert lead time, proven from the first message's own timestamp
    def test_first_alert_exactly_six_hours_before_is_eligible(self):
        ko = NOW + timedelta(hours=5)
        row = self.one(pair(0.02, lead=timedelta(hours=6), ko=ko))
        self.assertEqual((row["state"], row["lead_minutes"]), (e5.ELIGIBLE, 360.0))

    def test_first_alert_five_hours_59_minutes_before_is_not_eligible(self):
        ko = NOW + timedelta(hours=5)
        row = self.one(pair(0.02, lead=timedelta(hours=5, minutes=59), ko=ko))
        self.assertEqual((row["state"], row["reason"]), (e5.NOT_E5, "PRIMEIRO_ALERTA_A_MENOS_DE_6H"))
        # V5 rounds minutes_to_kickoff to 0.1 min (359.98 -> 360.0); the exact proof does not.
        row = self.one(pair(0.02, lead=timedelta(hours=5, minutes=59, seconds=59), ko=ko))
        self.assertEqual(row["state"], e5.NOT_E5)

    def test_first_alert_more_than_24_hours_before_is_eligible(self):
        row = self.one(pair(0.0, lead=timedelta(hours=50), ko=NOW + timedelta(hours=40)))
        self.assertEqual(row["state"], e5.ELIGIBLE)
        self.assertEqual(e5._hours(row["lead_minutes"]), "50,0")

    # 7-8: started/finished games out, far-future games in (no 12h window)
    def test_started_or_finished_game_is_never_eligible(self):
        for ko in (NOW, NOW - timedelta(minutes=1), NOW - timedelta(hours=3)):
            with self.subTest(ko=ko):
                alerts = pair(0.0, lead=timedelta(hours=10), ko=ko,
                              second_at=ko - timedelta(hours=1))
                row = self.one(alerts)
                self.assertEqual((row["state"], row["reason"]),
                                 (e5.EXCLUDED, "JOGO_INICIADO_OU_TERMINADO"))
                ledger, stats, sender = process([row])
                self.assertEqual((sender.messages, ledger["entries"]), ([], {}))

    def test_game_more_than_12_hours_ahead_is_eligible_but_deferred(self):
        # User decision 2026-11-02: new alerts only for kickoffs within the next 12 hours.
        ko = NOW + timedelta(days=4)
        row = self.one(pair(0.03, lead=timedelta(days=5), ko=ko))
        self.assertEqual(row["state"], e5.ELIGIBLE)
        ledger, stats, sender = process([row], research_doc=research())
        self.assertEqual((sender.messages, ledger["entries"], stats["deferred_beyond_12h"]), ([], {}, 1))
        # It is alerted once it enters the 12-hour window.
        later = ko - timedelta(hours=11)
        ledger, stats, sender = process([row], ledger, now=later, research_doc=research(now=later))
        self.assertEqual((stats["sent"], len(sender.messages)), (1, 1))
        text = sender.messages[0]
        for needle in ("🧠 MASTER BRAIN | E5 — OVER 2,5", "⚽ Casa vs Fora",
                       "🕒 06/11/2026 18:00 (Portugal)", "🎯 PADRÃO E5 CONFIRMADO",
                       "📊 Variação dos golos implícitos: +0,0300",
                       "⏱️ Primeiro alerta: 120,0 horas antes do jogo",
                       "📈 Histórico V5: 52/72 (72,2%) — exploratório", "🆔 P5-8bced1b27e"):
            self.assertIn(needle, text)
        entry = ledger["entries"]["2026-11-03,7"]
        self.assertEqual((entry["status"], entry["telegram_message_id"], entry["transition"]),
                         ("sent", 101, "ENTERED"))

    def test_window_boundary_exactly_12_hours_is_sent_and_one_second_more_is_not(self):
        rows = rows_for(pair(0.01, ko=NOW + timedelta(hours=12)) +
                        [dict(a, event_id=a["event_id"] + "b", match_key="2026-11-03,8")
                         for a in pair(0.01, ko=NOW + timedelta(hours=12, seconds=1))])
        ledger, stats, sender = process(rows)
        self.assertEqual((stats["sent"], stats["deferred_beyond_12h"]), (1, 1))
        self.assertIn("2026-11-03,7", ledger["entries"])

    def test_all_games_within_12h_sent_in_kickoff_order_without_a_quota(self):
        alerts, markets = [], []
        for n in range(9):
            ko = NOW + timedelta(hours=11, minutes=-n * 45)
            for a in pair(0.01, ko=ko, match="2026-11-0%d,%d" % (3 + n % 3, n)):
                a["event_id"] += ":%d" % n
                alerts.append(a)
        rows = rows_for(alerts)
        ledger, stats, sender = process(rows)
        self.assertEqual(stats["sent"], 9)
        kickoffs = [ledger["entries"][k]["kickoff_utc"] for k in
                    sorted(ledger["entries"], key=lambda k: ledger["entries"][k]["telegram_message_id"])]
        self.assertEqual(kickoffs, sorted(kickoffs))

    def test_history_unavailable_is_stated_not_invented(self):
        row = self.one(pair(0.01))
        for doc, reason in ((None, "relatório V5 indisponível"),
                            ({"generated_at": NOW.isoformat(), "patterns": [], "combinations_top": []},
                             "E5 não consta do relatório V5 atual"),
                            (research(now=NOW - timedelta(days=3)), "relatório V5 desatualizado")):
            with self.subTest(reason=reason):
                hist, why = e5.history(doc, NOW)
                self.assertIsNone(hist)
                text = e5.message_for_game(row, hist, why)
                self.assertIn("📈 Histórico V5: indisponível (" + reason + ")", text)
                self.assertNotIn("%", text)

    def test_changed_published_definition_blocks_everything(self):
        doc = research()
        doc["patterns"][0]["definition"] = {"op": "HAS", "a": "G_NET_IMPLIED_SMALL"}
        row = self.one(pair(0.01))
        sender = Sender()
        with self.assertRaises(ValueError):
            process([row], sender=sender, research_doc=doc)
        self.assertEqual(sender.messages, [])

    # 12: missing or invalid evidence: no notification
    def test_no_valid_v4_total_evidence_means_no_notification(self):
        alerts = pair(0.01)
        cases = {
            "SNAPSHOT_TOTAL_NAO_V4": (alerts, [v4(alerts[0])]),          # 2nd message H1-only
            "SEM_SNAPSHOT_TOTAL_V4": (alerts, [v4(a, markets={}) for a in alerts]),
        }
        for reason, (rows, markets) in cases.items():
            with self.subTest(reason=reason):
                legacy = [dict(a) for a in rows]
                if reason == "SEM_SNAPSHOT_TOTAL_V4":
                    for a in legacy:
                        for k in ("total_before", "total_after"):
                            a[k] = None
                row = self.one(legacy, markets=markets)
                self.assertEqual((row["state"], row["reason"]), (e5.EXCLUDED, reason))
                ledger, stats, sender = process([row])
                self.assertEqual(sender.messages, [])

    def test_invalid_implied_goals_are_excluded(self):
        with patch("h1lab.pattern_features.implied_lambda", lambda *a: None):
            timelines, _, _ = collect_timelines(pair(0.01), [v4(a) for a in pair(0.01)])
            row = e5.evaluate_all(timelines, NOW)[0]
        self.assertEqual((row["state"], row["reason"]), (e5.EXCLUDED, "GOLOS_IMPLICITOS_INVALIDOS"))

    def test_ambiguous_identity_and_inconsistent_kickoff_are_excluded(self):
        alerts = pair(0.01)
        alerts[1]["away"] = "Outra Equipa"
        self.assertEqual(self.one(alerts)["reason"], "IDENTIDADE_AMBIGUA")
        alerts = pair(0.01)
        markets = [v4(alerts[0]), v4(alerts[1], kickoff_utc=(KO + timedelta(hours=2)).isoformat())]
        self.assertEqual(self.one(alerts, markets=markets)["state"], e5.EXCLUDED)

    def test_no_future_information_is_used(self):
        alerts = pair(0.01)
        later = message(3, 2.01, 2.5, at=NOW + timedelta(minutes=10))   # after the decision instant
        timelines, _, _ = collect_timelines(alerts + [later], [v4(a) for a in alerts + [later]])
        with patch("h1lab.pattern_features.implied_lambda", proxy_lambda):
            row = e5.evaluate_all(timelines, NOW)[0]
        self.assertEqual((row["state"], row["reason"]), (e5.EXCLUDED, "MENSAGEM_POSTERIOR_A_DECISAO"))

    def test_real_poisson_engine_is_used_without_patching(self):
        alerts = [message(1, 1.9, 1.88, at=NOW - timedelta(hours=3)),
                  message(2, 1.88, 1.87, at=NOW - timedelta(minutes=10))]
        row = self.one(alerts, real_lambda=True)
        self.assertEqual(row["state"], e5.ELIGIBLE)
        self.assertLess(abs(row["net_dlam"]), 0.10)


class E5DeliveryTests(unittest.TestCase):
    def setUp(self):
        BlockStore().clear()

    # 9: repeated messages / repeated cycles never duplicate
    def test_repeated_messages_and_cycles_never_duplicate_the_alert(self):
        alerts = pair(0.02)
        repeat = dict(alerts[1], event_id="telegram:3", message_id=3,
                      observed_at=(NOW - timedelta(minutes=4, seconds=50)).isoformat())
        rows = rows_for(alerts + [repeat])
        self.assertEqual(len(rows), 1)
        ledger, stats, sender = process(rows)
        self.assertEqual(stats["sent"], 1)
        later = NOW + timedelta(minutes=5)
        ledger, stats, sender2 = process(rows_for(alerts + [repeat], now=later), ledger, now=later)
        self.assertEqual((sender2.messages, stats["already_notified"]), ([], 1))

    # 10: proven exit -> exactly one withdrawal, only with new valid evidence, never after kickoff
    def test_proven_exit_sends_a_single_withdrawal(self):
        ledger, stats, sender = process(rows_for(pair(0.02)))
        self.assertEqual(stats["sent"], 1)
        later = NOW + timedelta(minutes=30)
        moved = pair(0.02) + [message(3, 2.02, 2.15, at=later - timedelta(minutes=1))]
        rows = rows_for(moved, now=later)
        self.assertEqual(rows[0]["state"], e5.NOT_E5)
        ledger, stats, sender = process(rows, ledger, now=later)
        self.assertEqual((stats["withdrawals_sent"], stats["sent"]), (1, 0))
        self.assertIn("❌ MASTER BRAIN | E5 RETIRADA", sender.messages[0])
        self.assertIn("📊 Variação anterior: +0,0200", sender.messages[0])
        self.assertIn("📉 Nova variação: +0,1500", sender.messages[0])
        entry = ledger["entries"]["2026-11-03,7" + e5.WITHDRAWN]
        self.assertEqual((entry["status"], entry["transition"], entry["entry_message_id"]),
                         ("sent", "WITHDRAWN", 101))
        self.assertEqual(ledger["entries"]["2026-11-03,7"]["status"], "sent")   # receipt unchanged
        again = later + timedelta(minutes=5)
        ledger, stats, sender = process(rows_for(moved, now=again), ledger, now=again)
        self.assertEqual(sender.messages, [])

    def test_unavailable_information_never_withdraws(self):
        ledger, _, _ = process(rows_for(pair(0.02)))
        later = NOW + timedelta(minutes=30)
        third = message(3, 2.02, 2.15, at=later - timedelta(minutes=1))
        cases = {"legacy_only_new_message": (pair(0.02) + [third], [v4(a) for a in pair(0.02)]),
                 "no_new_message": (pair(0.02), None)}
        for name, (alerts, markets) in cases.items():
            with self.subTest(name=name):
                rows = rows_for(alerts, markets=markets, now=later)
                copy = json.loads(json.dumps(ledger))
                copy, stats, sender = process(rows, copy, now=later)
                self.assertEqual(sender.messages, [])
                self.assertNotIn("2026-11-03,7" + e5.WITHDRAWN, copy["entries"])

    def test_no_withdrawal_after_kickoff(self):
        ko = NOW + timedelta(hours=1)
        ledger, stats, _ = process(rows_for(pair(0.02, ko=ko, lead=timedelta(hours=8))))
        self.assertEqual(stats["sent"], 1)
        after = ko + timedelta(minutes=1)
        moved = pair(0.02, ko=ko, lead=timedelta(hours=8)) + [message(3, 2.02, 2.2, at=ko - timedelta(minutes=2), ko=ko)]
        ledger, stats, sender = process(rows_for(moved, now=after), ledger, now=after)
        self.assertEqual(sender.messages, [])

    # 11: Telegram / GitHub failures never cause an unsafe resend
    def test_uncertain_telegram_delivery_is_never_resent(self):
        rows = rows_for(pair(0.02))
        ledger, stats, _ = process(rows, sender=Sender(BotDeliveryError("timeout")))
        self.assertEqual(ledger["entries"]["2026-11-03,7"]["status"], delivery.UNCERTAIN)
        ledger, stats, sender = process(rows, ledger, now=NOW + timedelta(minutes=5))
        self.assertEqual(sender.messages, [])

    def test_rate_limit_waits_for_retry_after_and_stops_the_batch(self):
        alerts = pair(0.02) + [dict(a, event_id=a["event_id"] + "b", match_key="2026-11-03,8")
                               for a in pair(0.03)]
        rows = rows_for(alerts)
        ledger, stats, sender = process(rows, sender=Sender(BotRejectedError("429", 429, 60)))
        self.assertEqual(len(sender.messages), 1)                     # batch stopped
        entry = ledger["entries"]["2026-11-03,7"]
        self.assertEqual(entry["status"], delivery.REJECTED)
        ledger, stats, sender = process(rows, ledger, now=NOW + timedelta(seconds=30))
        self.assertEqual(sender.messages, [])                         # still paused
        BlockStore().clear()
        ledger, stats, sender = process(rows, ledger, now=NOW + timedelta(minutes=2))
        self.assertEqual(stats["sent"], 2)

    def test_blocked_before_http_is_not_uncertain(self):
        rows = rows_for(pair(0.02))
        ledger, stats, _ = process(rows, sender=Sender(BotBlockedError("blocked")))
        self.assertEqual((ledger["entries"], stats.get("blocked_before_http")), ({}, 1))

    def test_github_intent_failure_sends_nothing(self):
        def persist(_):
            raise delivery.IntentNotDurable("push rejected")
        rows = rows_for(pair(0.02))
        ledger, stats, sender = process(rows, persist=persist)
        self.assertEqual((sender.messages, ledger["entries"], stats.get("intent_not_durable")),
                         ([], {}, 1))

    def test_intent_is_persisted_before_the_request_and_outcome_after(self):
        seen = []

        def persist(value):
            seen.append({k: v["status"] for k, v in value["entries"].items()})
        sender = Sender()
        original = sender.__call__

        def checked(text):
            self.assertEqual(seen[-1], {"2026-11-03,7": delivery.IN_PROGRESS})
            return original(text)
        ledger, stats, _ = process(rows_for(pair(0.02)), sender=checked, persist=persist)
        self.assertEqual(seen, [{"2026-11-03,7": delivery.IN_PROGRESS}, {"2026-11-03,7": "sent"}])

    def test_crash_between_intent_and_outcome_is_never_resent(self):
        ledger = e5.empty_ledger(NOW)
        ledger["entries"]["2026-11-03,7"] = {"status": delivery.IN_PROGRESS, "match_key": "2026-11-03,7",
                                            "kickoff_utc": KO.isoformat()}
        ledger, stats, sender = process(rows_for(pair(0.02)), ledger)
        self.assertEqual((sender.messages, ledger["entries"]["2026-11-03,7"]["status"]),
                         ([], delivery.UNCERTAIN))

    def test_unconfigured_bot_sends_nothing_and_writes_nothing(self):
        sender = Sender()
        ledger, stats = e5.process(rows_for(pair(0.02)), e5.empty_ledger(NOW), NOW, sender, False,
                                   store=BlockStore())
        self.assertEqual((sender.messages, ledger["entries"], stats["unconfigured"]), ([], {}, 1))

    def test_game_starting_during_the_batch_is_skipped(self):
        ko = NOW + timedelta(minutes=10)
        rows = rows_for(pair(0.02, ko=ko, lead=timedelta(hours=8)))
        ticks = iter([NOW, NOW, NOW, ko, ko, ko, ko])
        ledger, stats, sender = process(rows, clock=lambda: next(ticks))
        self.assertEqual(sender.messages, [])

    def test_invalid_ledger_refuses_to_send(self):
        sender = Sender()
        with self.assertRaises(ValueError):
            e5.process(rows_for(pair(0.02)), {"schema_version": 1, "rule_version": "OTHER",
                                              "entries": {}}, NOW, sender, True)
        self.assertEqual(sender.messages, [])


class E5WindowAndWithdrawalTests(unittest.TestCase):
    """User checklist 2026-11-02: 12-hour window + automatic withdrawals."""

    def setUp(self):
        BlockStore().clear()

    def _sent_for(self, ko):
        rows = rows_for(pair(0.01, ko=ko))
        return process(rows)

    # 1, 2, 3
    def test_window_11h59_and_12h00_sent_12h00m01s_deferred(self):
        for delta, sent in ((timedelta(hours=11, minutes=59), 1), (timedelta(hours=12), 1),
                            (timedelta(hours=12, seconds=1), 0)):
            with self.subTest(delta=delta):
                ledger, stats, sender = self._sent_for(NOW + delta)
                self.assertEqual((stats["sent"], len(sender.messages)), (sent, sent))
                self.assertEqual(stats["deferred_beyond_12h"], 1 - sent)

    # 4
    def test_deferred_game_is_sent_automatically_when_it_enters_the_window(self):
        ko = NOW + timedelta(hours=20)
        ledger, stats, sender = self._sent_for(ko)
        self.assertEqual((sender.messages, stats["deferred_beyond_12h"]), ([], 1))
        later = ko - timedelta(hours=12)
        rows = rows_for(pair(0.01, ko=ko), now=later)
        ledger, stats, sender = process(rows, ledger, now=later)
        self.assertEqual((stats["sent"], ledger["entries"]["2026-11-03,7"]["status"]), (1, "sent"))

    def _withdraw(self, start, end, *, ko=KO, ledger=None, now=NOW):
        """Alert with net `start`, then a NEW V4 message moves the net to `end`."""
        alerts = pair(start, ko=ko)
        if ledger is None:
            ledger, stats, _ = process(rows_for(alerts, now=now), now=now)
            self.assertEqual(stats["sent"], 1)
        later = now + timedelta(minutes=30)
        moved = alerts + [message(3, round(2.0 + start, 4), round(2.0 + end, 4),
                                  at=later - timedelta(minutes=1), ko=ko)]
        rows = rows_for(moved, now=later)
        ledger, stats, sender = process(rows, ledger, now=later)
        return ledger, stats, sender, moved, later

    # 5
    def test_plus_0_04_to_plus_0_12_sends_withdrawal(self):
        ledger, stats, sender, _, _ = self._withdraw(0.04, 0.12)
        self.assertEqual(stats["withdrawals_sent"], 1)
        self.assertIn("📊 Variação anterior: +0,0400", sender.messages[0])
        self.assertIn("📉 Nova variação: +0,1200", sender.messages[0])

    # 6
    def test_minus_0_03_to_minus_0_11_sends_withdrawal(self):
        ledger, stats, sender, _, _ = self._withdraw(-0.03, -0.11)
        self.assertEqual(stats["withdrawals_sent"], 1)
        self.assertIn("📊 Variação anterior: -0,0300", sender.messages[0])
        self.assertIn("📉 Nova variação: -0,1100", sender.messages[0])

    # 7, 8
    def test_single_withdrawal_and_no_duplicate_on_unchanged_cycles(self):
        ledger, stats, sender, moved, later = self._withdraw(0.02, 0.15)
        self.assertEqual(len(sender.messages), 1)
        for minutes in (5, 10, 15):
            again = later + timedelta(minutes=minutes)
            ledger, stats, sender = process(rows_for(moved, now=again), ledger, now=again)
            self.assertEqual((sender.messages, stats["withdrawals_sent"]), ([], 0))
        self.assertEqual(sum(k.endswith(e5.WITHDRAWN) for k in ledger["entries"]), 1)

    # 9
    def test_incomplete_data_never_withdraws(self):
        ledger, _, _ = process(rows_for(pair(0.02)))
        later = NOW + timedelta(minutes=30)
        third = message(3, 2.02, 2.15, at=later - timedelta(minutes=1))
        broken = v4(third)
        broken["markets"]["total"]["after"]["over_price"] = None
        rows = rows_for(pair(0.02) + [third], markets=[v4(a) for a in pair(0.02)] + [broken],
                        now=later)
        self.assertEqual(rows[0]["state"], e5.EXCLUDED)
        ledger, stats, sender = process(rows, ledger, now=later)
        self.assertEqual(sender.messages, [])

    # 10
    def test_started_game_gets_no_message_of_any_kind(self):
        ko = NOW + timedelta(minutes=20)
        ledger, stats, _ = process(rows_for(pair(0.02, ko=ko, lead=timedelta(hours=8))))
        self.assertEqual(stats["sent"], 1)
        moved = pair(0.02, ko=ko, lead=timedelta(hours=8)) + [
            message(3, 2.02, 2.3, at=ko - timedelta(minutes=1), ko=ko)]
        for after in (ko, ko + timedelta(hours=2)):
            ledger, stats, sender = process(rows_for(moved, now=after), ledger, now=after)
            self.assertEqual(sender.messages, [])

    # 11 (Hull City U21 - Derby County U21 pattern)
    def test_game_never_alerted_gets_no_withdrawal(self):
        rows = rows_for(pair(0.9015))
        self.assertEqual((rows[0]["state"], rows[0]["reason"]),
                         (e5.NOT_E5, "VARIACAO_LIQUIDA_IGUAL_OU_SUPERIOR_A_0_10"))
        for ledger in (e5.empty_ledger(NOW), self._uncertain_ledger()):
            ledger, stats, sender = process(rows, ledger)
            self.assertEqual((sender.messages, stats["withdrawals_sent"]), ([], 0))
            self.assertNotIn("2026-11-03,7" + e5.WITHDRAWN, ledger["entries"])

    def _uncertain_ledger(self):
        ledger = e5.empty_ledger(NOW)
        ledger["entries"]["2026-11-03,7"] = {"status": delivery.UNCERTAIN, "kickoff_utc": KO.isoformat(),
                                            "observed_through": (NOW - timedelta(hours=3)).isoformat(),
                                            "net_dlam": 0.01, "transition": "ENTERED"}
        return ledger

    # 12
    def test_initial_batch_alert_outside_12h_can_still_be_withdrawn_before_kickoff(self):
        ko = NOW + timedelta(days=3)
        ledger = e5.empty_ledger(NOW)
        ledger["entries"]["2026-11-03,7"] = {
            "status": "sent", "telegram_message_id": 350, "transition": "ENTERED",
            "kickoff_utc": ko.isoformat(), "net_dlam": 0.03,
            "observed_through": (NOW - timedelta(minutes=5)).isoformat()}
        ledger, stats, sender, _, _ = self._withdraw(0.03, 0.14, ko=ko, ledger=ledger)
        self.assertEqual(stats["withdrawals_sent"], 1)
        entry = ledger["entries"]["2026-11-03,7" + e5.WITHDRAWN]
        self.assertEqual((entry["entry_message_id"], entry["previous_net_dlam"]), (350, 0.03))

    # 13
    def test_publication_failure_or_uncertain_withdrawal_is_never_duplicated(self):
        ledger, _, _ = process(rows_for(pair(0.02)))
        later = NOW + timedelta(minutes=30)
        moved = pair(0.02) + [message(3, 2.02, 2.15, at=later - timedelta(minutes=1))]
        rows = rows_for(moved, now=later)

        def fail(_):
            raise delivery.IntentNotDurable("push rejected")
        copy = json.loads(json.dumps(ledger))
        copy, stats, sender = process(rows, copy, now=later, persist=fail)
        self.assertEqual((sender.messages, stats.get("intent_not_durable")), ([], 1))
        self.assertNotIn("2026-11-03,7" + e5.WITHDRAWN, copy["entries"])
        ledger, stats, sender = process(rows, ledger, now=later,
                                        sender=Sender(BotDeliveryError("timeout")))
        self.assertEqual(ledger["entries"]["2026-11-03,7" + e5.WITHDRAWN]["status"], delivery.UNCERTAIN)
        again = later + timedelta(minutes=5)
        ledger, stats, sender = process(rows_for(moved, now=again), ledger, now=again)
        self.assertEqual(sender.messages, [])

    def test_reentry_after_withdrawal_is_audited_not_resent(self):
        ledger, stats, sender, moved, later = self._withdraw(0.02, 0.15)
        self.assertEqual(stats["withdrawals_sent"], 1)
        back = later + timedelta(minutes=30)
        again = moved + [message(4, 2.17, 2.05, at=back - timedelta(minutes=1))]
        rows = rows_for(again, now=back)
        self.assertEqual(rows[0]["state"], e5.ELIGIBLE)
        for tick in (back, back + timedelta(minutes=5)):
            ledger, stats, sender = process(rows_for(again, now=tick), ledger, now=tick)
            self.assertEqual(sender.messages, [])
        audit = list(ledger["audit"].values())
        self.assertEqual(len(audit), 1)
        self.assertEqual((audit[0]["transition"], audit[0]["action"]),
                         ("REENTERED_AFTER_WITHDRAWAL", "NOT_RESENT"))


class E5RealLedgerTests(unittest.TestCase):
    """14 + operational proof from the published ledger (Wycombe 369 -> 428, Hull none)."""

    def setUp(self):
        self.ledger = json.loads((REPO / e5.LEDGER).read_text(encoding="utf-8"))

    def test_historical_receipts_are_preserved(self):
        entries = self.ledger["entries"]
        self.assertEqual(self.ledger["rule_version"], e5.RULE_VERSION)
        self.assertGreaterEqual(len(entries), 64)
        ids = [e["telegram_message_id"] for e in entries.values() if e.get("status") == "sent"]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({369, 428} <= set(ids))

    def test_wycombe_withdrawal_regression(self):
        key = "2026-11-02,99,49903"
        entry, withdrawn = self.ledger["entries"][key], self.ledger["entries"][key + e5.WITHDRAWN]
        self.assertEqual((entry["telegram_message_id"], entry["transition"]), (369, "ENTERED"))
        self.assertEqual((withdrawn["telegram_message_id"], withdrawn["entry_message_id"],
                          withdrawn["net_dlam"]), (428, 369, -0.1947))
        row = {"state": e5.NOT_E5, "reason": "VARIACAO_LIQUIDA_IGUAL_OU_SUPERIOR_A_0_10",
               "match_key": key, "match_label": entry["match_label"],
               "kickoff_utc": entry["kickoff_utc"], "net_dlam": -0.1947,
               "last_total_observed_at": withdrawn["last_total_observed_at"]}
        self.assertTrue(e5.proven_withdrawal(row, entry))
        text = e5.withdrawal_message(row, entry)
        for needle in ("❌ MASTER BRAIN | E5 RETIRADA", "⚽ Wycombe Wanderers FC vs Brentford U21",
                       "🕒 02/11/2026 19:00 (Portugal)", "⚠️ ESTE JOGO DEIXOU DE CUMPRIR A E5",
                       "📊 Variação anterior: +0,0367", "📉 Nova variação: -0,1947",
                       "🕒 Movimento observado: 02/11/2026 18:36 (Portugal)", "🆔 P5-8bced1b27e"):
            self.assertIn(needle, text)
        # already withdrawn: a new cycle never sends a second withdrawal
        rows = [{**row, "first_observed_at": entry["first_observed_at"],
                 "lead_minutes": entry["lead_minutes"], "observed_through": withdrawn["observed_through"],
                 "feature_fingerprint": None, "event_ids": []}]
        now = datetime(2026, 11, 2, 18, 50, tzinfo=timezone.utc)
        copy = json.loads(json.dumps(self.ledger))
        BlockStore().clear()
        copy, stats, sender = process(rows, copy, now=now)
        self.assertEqual((sender.messages, copy["entries"]), ([], self.ledger["entries"]))

    def test_hull_city_u21_has_no_initial_alert_so_no_retroactive_withdrawal(self):
        hull = [k for k, v in self.ledger["entries"].items()
                if "Hull City" in (v.get("match_label") or "")]
        self.assertEqual(hull, [])


class E5RunTests(unittest.TestCase):
    """run() on a temporary checkout copy: real file reading, fake Telegram and fake GitHub."""

    def setUp(self):
        BlockStore().clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        (self.root / "docs/lab").mkdir(parents=True)
        alerts = pair(0.02)
        state = {"alerts": alerts, "last_id": 2, "signals": [], "tickets": [], "diagnostics": []}
        (self.root / "data/state.json").write_text(json.dumps(state))
        (self.root / "data/lab").mkdir()
        (self.root / "data/lab/markets-2026-11.jsonl").write_text(
            "\n".join(json.dumps(v4(a)) for a in alerts) + "\n")
        (self.root / e5.RESEARCH).write_text(json.dumps(research()))

    def tearDown(self):
        self.tmp.cleanup()

    def run_e5(self, publisher, sender=None, **kw):
        sender = sender or Sender()
        with patch("h1lab.pattern_features.implied_lambda", proxy_lambda), \
                patch("h1lab.e5_notify.time.sleep"):
            result = e5.run(self.root, now=NOW, sender=sender, bot_enabled=True,
                            publisher=publisher, **kw)
        return result, sender

    def test_publishes_intent_then_final_outcome(self):
        calls = []

        def publisher(final=False):
            calls.append((final, json.loads((self.root / e5.LEDGER).read_text())["entries"]
                          .get("2026-11-03,7", {}).get("status")))
        (ledger, stats), sender = self.run_e5(publisher)
        self.assertEqual(calls, [(False, delivery.IN_PROGRESS), (True, "sent")])
        self.assertEqual(stats["sent"], 1)

    def test_missing_durability_refuses_to_send(self):
        def publisher(final=False):
            raise delivery.IntentNotDurable("remote refused")
        with self.assertRaises(SystemExit):
            _, sender = self.run_e5(publisher)
        self.assertFalse((self.root / e5.LEDGER).exists() and json.loads(
            (self.root / e5.LEDGER).read_text())["entries"])

    def test_dry_run_writes_nothing(self):
        result, sender = self.run_e5(None, dry_run=True)
        self.assertEqual(sender.messages, [])
        self.assertFalse((self.root / e5.LEDGER).exists())


class E5ReceiptPublisherTests(unittest.TestCase):
    """The intent really reaches a bare 'GitHub' main through the selective collector policy."""

    def test_intent_reaches_main_and_concurrent_owner_write_fails_closed(self):
        from scripts import collect_publish_safe as c
        from tests.git_writers import BareGitFixture, git
        fx = BareGitFixture()
        self.addCleanup(fx.cleanup)
        root = fx.clone("collector")
        ledger = json.loads((root / e5.LEDGER).read_text())          # existing receipts are kept
        ledger["entries"]["k"] = {"status": delivery.IN_PROGRESS, "match_key": "k",
                                  "kickoff_utc": KO.isoformat()}
        (root / e5.LEDGER).write_text(json.dumps(ledger))
        # An unrelated FT writer advanced main meanwhile: kept byte-for-byte.
        fx.plain_commit("ft", {"data/lab/ft-ledger.json": {"schema_version": 1, "matches": {}}},
                        "data(lab): ft")
        publish = c.e5_receipt_publisher(root)
        published = publish()
        self.assertEqual(fx.main(), published)
        self.assertEqual(fx.json(str(e5.LEDGER))["entries"]["k"]["status"], delivery.IN_PROGRESS)
        self.assertEqual(fx.json("data/lab/ft-ledger.json")["matches"], {})
        self.assertIsNone(publish())                                   # unchanged: no commit
        changed_rule = dict(ledger, rule_version="OTHER_RULE")             # rule identity is frozen
        (root / e5.LEDGER).write_text(json.dumps(changed_rule))
        with self.assertRaises(delivery.IntentNotDurable):
            publish()
        git(root, "reset", "-q", "--hard", published)
        ledger["entries"]["k"].update(status="sent", telegram_message_id=5)
        (root / e5.LEDGER).write_text(json.dumps(ledger))
        self.assertEqual(publish(final=True), fx.main())
        # A terminal receipt can never be rewritten, and a foreign tracked change blocks the send.
        ledger["entries"]["k"]["telegram_message_id"] = 6
        (root / e5.LEDGER).write_text(json.dumps(ledger))
        with self.assertRaises(delivery.IntentNotDurable):
            publish()
        git(root, "reset", "-q", "--hard", "origin/main")
        (root / "data/state.json").write_text("{}")
        ledger["entries"]["k2"] = {"status": delivery.IN_PROGRESS, "match_key": "k2"}
        (root / e5.LEDGER).write_text(json.dumps(ledger))
        with self.assertRaises(delivery.IntentNotDurable):
            publish()


class OnlyE5IsActiveTests(unittest.TestCase):
    """13: no retired emitter can still send."""

    def test_collect_workflow_runs_only_the_e5_emitter(self):
        text = (REPO / ".github/workflows/collect.yml").read_text(encoding="utf-8")
        modules = re.findall(r"python -m (h1lab\.[a-z0-9_]+)", text)
        self.assertEqual(modules, ["h1lab.cli", "h1lab.e5_notify"])
        steps = yaml.safe_load(text)["jobs"]["collect"]["steps"]
        names = [s.get("name", "") for s in steps]
        self.assertLess(names.index("Store data for dashboard"),
                        names.index("Notify MASTER BRAIN E5 - Over 2,5 (exclusive)"))
        e5_step = steps[names.index("Notify MASTER BRAIN E5 - Over 2,5 (exclusive)")]
        self.assertEqual(set(e5_step["env"]), {"TG_BOT_TOKEN", "TG_CHAT_ID"})
        bot_steps = [s for s in steps if "TG_BOT_TOKEN" in json.dumps(s)]
        self.assertEqual(bot_steps, [e5_step])

    def test_no_workflow_invokes_a_retired_emitter_for_real(self):
        from h1lab.telegram_emitters import RETIRED
        for path in (REPO / ".github/workflows").glob("*.yml"):
            text = path.read_text(encoding="utf-8")
            for module in RETIRED:
                for match in re.finditer(r"python -m " + re.escape(module) + r"\b(.*)", text):
                    self.assertIn("--dry-run", match.group(1), "%s runs %s" % (path.name, module))
            if "TG_BOT_TOKEN" in text:
                self.assertIn(path.name, ("collect.yml", "bot-smoke.yml"))

    def test_retired_entry_points_refuse_without_any_request(self):
        from h1lab.telegram_emitters import RETIRED
        env = {**os.environ, "TG_BOT_TOKEN": "1:fake", "TG_CHAT_ID": "123",
               "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
        before = subprocess.run(["git", "status", "--porcelain", "--", "data"], cwd=REPO,
                                capture_output=True, text=True).stdout
        for module in RETIRED:
            with self.subTest(module=module):
                proc = subprocess.run([sys.executable, "-m", module], cwd=REPO, env=env,
                                      capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0, proc.stderr[-300:])
                self.assertIn("TELEGRAM_EMITTER_RETIRED", proc.stdout)
        after = subprocess.run(["git", "status", "--porcelain", "--", "data"], cwd=REPO,
                               capture_output=True, text=True).stdout
        self.assertEqual(before, after)

    def test_new_ledger_is_collector_owned_and_old_ledgers_are_frozen(self):
        from scripts import publication_ownership as own
        self.assertEqual(own.owner_of(str(e5.LEDGER)), own.COLLECTOR)
        self.assertEqual(own.TELEGRAM_LEDGERS, (str(e5.LEDGER),))
        for path in ("data/three-total-moves-notifications.json", "data/two-up-total-notifications.json",
                     "data/strategy-notifications.json", "data/e4-notifications.json",
                     "data/t05-notifications.json", "data/pattern-notifications.json"):
            self.assertEqual(own.owner_of(path), own.LEGACY, path)
            self.assertTrue((REPO / path).exists(), "historical proof must stay: " + path)


if __name__ == "__main__":
    unittest.main()

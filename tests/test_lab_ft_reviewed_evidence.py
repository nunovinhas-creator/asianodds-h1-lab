"""Historical, two-source manual FT registry: strict source/identity safety."""
import unittest
from datetime import datetime, timezone
from h1lab.lab_ft_reviewed_evidence import REVIEWED_PUBLIC_FT, verified_public_ft
from h1lab.lab_results import reconcile

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


def signal(key, fixture):
    return {"match_key": key, "home": fixture[0], "away": fixture[1],
            "kickoff_utc": fixture[2]}


class ReviewedPublicEvidenceTests(unittest.TestCase):
    def test_all_three_have_two_sources_and_exact_90m_scores(self):
        expected = {
            "2026-10-27,10102013,10048381": (4, 0),
            "2026-10-27,58630,10024258": (3, 1),
            "2026-10-27,70933,35866": (5, 1),
        }
        self.assertEqual(set(REVIEWED_PUBLIC_FT), set(expected))
        for key, fixture in REVIEWED_PUBLIC_FT.items():
            with self.subTest(key=key):
                result, reason = verified_public_ft(signal(key, fixture))
                self.assertEqual((result["home_goals"], result["away_goals"]),
                                 expected[key])
                self.assertEqual(reason, "reviewed_two_independent_public_ft")
                self.assertEqual(result["status"], "final")

    def test_changed_identity_or_kickoff_never_inherits_public_score(self):
        for key, fixture in REVIEWED_PUBLIC_FT.items():
            for field, altered in (("home", "Other Team"),
                                   ("away", "Other Team"),
                                   ("kickoff_utc", "2026-10-27T21:30:00+00:00"),
                                   ("match_key", "2026-10-27,999,999")):
                with self.subTest(key=key, field=field):
                    sig = signal(key, fixture)
                    sig[field] = altered
                    self.assertIsNone(verified_public_ft(sig)[0])

    def test_corroborated_quarantines_settle_without_sportscore(self):
        previous = {"schema_version": 1, "matches": {}}
        alerts = []
        for key, f in REVIEWED_PUBLIC_FT.items():
            sig = signal(key, f)
            alerts.append(sig)
            previous["matches"][key] = {
                **sig, "status": "SOURCE_ORDER_CONFLICT",
                "reason": "sportscore_source_url_reverses_home_away",
                "checked_at": "2026-10-28T11:01:55+00:00",
                "lookup_source_version": 11,
                "attempts": 4,
            }
        def no(_):
            return None, "no_match"
        def no_sportscore(_):
            raise AssertionError("Never consult reversed SportScore source")
        ledger, report, attempts = reconcile(
            {"alerts": alerts, "signals": []}, [], previous, now=NOW,
            bsd_lookup=no, tsdb_lookup=no,
            sportscore_lookup=no_sportscore, max_checks=30)
        self.assertEqual(attempts, 3)
        self.assertEqual(report["final_recorded"], 3)
        self.assertEqual(report["source_order_audit"]["recovered_with_independent_ft"], 3)
        for key, f in REVIEWED_PUBLIC_FT.items():
            row = ledger["matches"][key]
            self.assertEqual(row["status"], "FINAL")
            self.assertEqual((row["result"]["home_goals"],row["result"]["away_goals"]), f[3:5])
            self.assertEqual(row["result"]["evidence"], "reviewed_public_only")
            proof=row["source_order_resolution"]
            self.assertEqual(proof["method"], "reviewed_two_independent_public_ft")
            self.assertEqual(len(proof["corroboration_urls"]),2)

    def test_preexisting_final_never_rewritten_even_if_registry_entry_exists(self):
        key, f = next(iter(REVIEWED_PUBLIC_FT.items()))
        sig = signal(key,f)
        confirmed = {"home_goals": 0, "away_goals": 0,
                     "source":"https://example.org/original", "evidence":"bsd_only"}
        previous={"schema_version":1,"matches":{key:{
            **sig,"status":"FINAL","result":confirmed}}}
        ledger, report, calls = reconcile(
            {"alerts":[sig],"signals":[]}, [], previous,
            now=NOW, bsd_lookup=lambda x:(_ for _ in ()).throw(
                AssertionError("Previously confirmed FT must be immutable")),
            tsdb_lookup=lambda x:(None,"no_match"), max_checks=30)
        self.assertEqual(calls, 0)
        self.assertEqual(report["final_recorded"], 1)
        self.assertEqual(ledger["matches"][key]["result"], confirmed)


if __name__ == "__main__":
    unittest.main()

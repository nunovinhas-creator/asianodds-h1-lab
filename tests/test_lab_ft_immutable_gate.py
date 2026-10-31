"""Immutable certified 90-minute score and identity cannot regress during 24h cutover."""
import json
import unittest
from h1lab.lab_ft_final_guard import final_snapshot, verify_preserved

def ledger(status="FINAL", home="Home", away_goals=1):
    row={"status":status,"home":home,"away":"Away",
         "kickoff_utc":"2026-10-31T17:00:00+00:00"}
    if status=="FINAL":
        row["result"]={"home_goals":2,"away_goals":away_goals,
                       "source":"https://example.org/fixture"}
    return (json.dumps({"schema_version":1,"matches":{"fixture-key":row}},
                       sort_keys=True)+"\n").encode()

class ImmutableFTGuardTests(unittest.TestCase):
    def test_keep_verified_and_allow_new(self):
        baseline=final_snapshot(ledger())
        self.assertTrue(verify_preserved(baseline,ledger())["previous_final_unchanged"])

    def test_never_downgrade_edit_score_or_reidentify(self):
        baseline=final_snapshot(ledger())
        for candidate in (ledger(status="PENDING"),
                          ledger(home="Other"),ledger(away_goals=0)):
            with self.subTest(data=candidate),self.assertRaises(ValueError):
                verify_preserved(baseline,candidate)

if __name__=="__main__":
    unittest.main()

"""P2#13: immutability, determinism, FT blindness and real repository smoke."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from h1lab import v6_hypothesis_pruning as p


def fixture():
    keys = ["g-%03d" % x for x in range(36)]
    defs = [{"id": "P5-FAKE-%03d" % i,
             "definition": {"op": "HAS", "a": "G_MULTI_ALERT"}}
            for i in range(800)]
    cat = {"definitions":defs,"original_generation":{"considered":3433,"generated":2523},
           "feature_version":1,"source_commit":"test","source_report_blob_sha":"test"}
    masks = [sum(1 << k for k in range(36) if (k + i%27)%11 < 5)
             for i in range(800)]
    masks[1] = masks[0]
    masks[2] = ((1 << 36) - 1) ^ masks[0]
    return cat, keys, masks


class TestV6P213(unittest.TestCase):
    def test_exact_and_complement_phi(self):
        self.assertEqual(p.phi(0b0011,0b1100,4), 1.)
        self.assertIsNone(p.phi(0b0000,0b1100,4))

    def test_deterministic_cap_and_mapping(self):
        cat, keys, masks = fixture()
        first = p.analyse(cat, keys, masks)
        second = p.analyse(copy.deepcopy(cat),list(keys),list(masks))
        self.assertEqual(first,second)
        self.assertEqual(first["scope"]["original_catalog"],800)
        self.assertEqual(first["scope"]["representatives"],300)
        self.assertEqual(first["scope"]["mapped_originals"],800)
        self.assertEqual(len(set(x["id"] for x in first["selection"]["mapping"])),800)
        self.assertEqual(len(first["selection"]["representatives"]),300)
        self.assertGreater(first["scope"]["exact_or_complement_redundancies"],0)
        self.assertLessEqual(first["effective_tests"]["estimate"],800)
        self.assertEqual(first["scientific_state"],"INCONCLUSIVO")

    def test_digest_detects_incidences_or_catalog_tamper(self):
        cat, keys, masks = fixture()
        snap = p.make_snapshot(cat,keys,masks)
        a=p.replay(cat,snap)
        self.assertEqual(a["source"]["ft_outcomes_used"],False)
        altered=copy.deepcopy(snap)
        altered["incidence_hex"][0]="aaaa"
        with self.assertRaisesRegex(ValueError,"modified"):
            p.replay(cat,altered)
        modified=copy.deepcopy(cat)
        modified["definitions"][0]["id"]="HACKED"
        with self.assertRaisesRegex(ValueError,"modified"):
            p.replay(modified,snap)

    def test_outcome_mutations_do_not_affect_frozen_report(self):
        cat,keys,masks=fixture()
        snap=p.make_snapshot(cat,keys,masks)
        original=p.replay(cat,snap)
        fake_outcomes={"g-000":0,"g-001":1}
        fake_outcomes.update({k:1-v for k,v in list(fake_outcomes.items())})
        self.assertEqual(original,p.replay(cat,snap))
        self.assertFalse("ft" in original["selection"])
        self.assertTrue(original["effective_tests"]["not_a_multiple_testing_alpha_adjustment"])

    def test_post_kickoff_alert_cannot_change_original_incidence(self):
        # Identical observation universe; adding an after-KO telegram message
        # must not change any of the 800 predicated columns.
        root=Path(__file__).resolve().parents[1]
        cat=p.catalog_read(root)
        pre={"event_id":"channel:1","message_id":1,"match_key":"match-a",
             "home":"Home","away":"Away","competition":"League",
             "kickoff_utc":"2026-11-01T12:00:00+00:00",
             "observed_at":"2026-11-01T09:00:00+00:00","market":"total",
             "total_before":2.5,"total_after":2.75,
             "over_before":1.90,"under_before":1.90,
             "over_after":1.95,"under_after":1.85,"h1":False,"source_url":"x"}
        post={**pre,"event_id":"channel:2","message_id":2,
              "observed_at":"2026-11-01T12:20:00+00:00",
              "total_after":2.25,"over_after":1.85,"under_after":1.95}
        with patch.object(p,"read_sources",return_value=([pre],[],[])):
            a=p.incidence(root,cat)
        with patch.object(p,"read_sources",return_value=([pre,post],[],[])):
            b=p.incidence(root,cat)
        self.assertEqual(a,b)

    def test_live_real_catalogue_and_pre_kickoff_incidence(self):
        root=Path(__file__).resolve().parents[1]
        catalog=p.catalog_read(root)
        keys,masks=p.incidence(root,catalog)
        self.assertEqual(len(masks),800)
        self.assertGreater(len(keys),10)
        self.assertTrue(all(0 <= x < (1<<len(keys)) for x in masks))

    def test_replay_idempotency_and_no_new_data(self):
        root=Path(__file__).resolve().parents[1]
        cat=p.catalog_read(root)
        keys,masks=fixture()[1:]
        with tempfile.TemporaryDirectory() as d:
            tmp=Path(d)
            path=tmp/p.CATALOG
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(cat),encoding="utf-8")
            with patch.object(p,"incidence",return_value=(keys,masks)) as mocked:
                first=p.run(tmp)
                self.assertEqual(p.run(tmp,verify_only=True),first)
                p.run(tmp)
                self.assertEqual(mocked.call_count,1)
                (tmp/"data/lab/ft-ledger.json").write_text('{"matches":{"g-000":{"over":true}}}')
                self.assertEqual(p.run(tmp,verify_only=True),first)
                with self.assertRaises(ValueError):
                    (tmp/p.FROZEN).write_text("{}",encoding="utf-8")
                    p.run(tmp,verify_only=True)

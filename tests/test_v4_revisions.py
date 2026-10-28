"""V4 Telegram revisions must be observable, replayable and never backdated."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab.market_v4 import parse, store
from h1lab.v4_revisions import (read_events, verify_projection, report, fingerprint)

WHEN=datetime(2026,10,28,14,tzinfo=timezone.utc)
TEXT="Line O U\nWas 2.25 1.90 1.90\nNow 2.50 1.95 1.85"


def observation(msg=1, text=TEXT):
    e=parse(text,WHEN,msg,3571094759)
    if e is None:
        raise ValueError("fixture failed to parse")
    return e


def path(root):
    return Path(root)/"data/lab/markets-2026-10.jsonl"


class V4RevisionTests(unittest.TestCase):
    def test_first_message_once_and_parser_commit_noise_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=observation()
            first["parser_commit"]="a"*40
            store(tmp,[first])
            original=path(tmp).read_bytes()
            later=dict(first,parser_commit="b"*40)
            store(tmp,[later])
            self.assertEqual(len(read_events(tmp)),1)
            self.assertEqual(read_events(tmp)[0]["kind"],"FIRST_SEEN_BY_COLLECTOR")
            self.assertEqual(path(tmp).read_bytes(),original)
            self.assertTrue(verify_projection(tmp))

    def test_edit_date_and_changed_quotations_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            initial=observation()
            store(tmp,[initial])
            old=read_events(tmp)[0]
            edited=observation(text=TEXT.replace("1.95 1.85","1.88 1.93"))
            edited["telegram_edit_at"]="2026-10-28T14:07:00+00:00"
            store(tmp,[edited])
            events=read_events(tmp)
            self.assertEqual(len(events),2)
            self.assertEqual(events[0],old)
            self.assertEqual(events[1]["kind"],"EDIT_DATE_CHANGED")
            self.assertEqual(events[1]["telegram_original_at"],WHEN.isoformat(timespec="seconds"))
            self.assertEqual(events[1]["telegram_edit_at"],edited["telegram_edit_at"])
            self.assertEqual(events[1]["previous_event_revision_id"],old["revision_id"])
            self.assertEqual(json.loads(path(tmp).read_text())["markets"],
                             edited["markets"])
            self.assertTrue(verify_projection(tmp))
            self.assertEqual(report(tmp)["telegram_edited_messages"],1)

    def test_same_edit_date_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=observation()
            e["telegram_edit_at"]="2026-10-28T14:07:00+00:00"
            store(tmp,[e]);store(tmp,[e])
            self.assertEqual(len(read_events(tmp)),1)

    def test_unproven_change_is_not_called_telegram_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=observation()
            store(tmp,[e])
            e2=observation(text=TEXT.replace("1.95 1.85","1.88 1.93"))
            store(tmp,[e2])
            self.assertEqual(read_events(tmp)[-1]["kind"],"CONTENT_CHANGED_EDIT_UNPROVEN")
            self.assertEqual(report(tmp)["changed_without_edit_proof"],1)

    def test_reversion_is_new_event_and_versions_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=observation()
            b=observation(text=TEXT.replace("1.95 1.85","1.88 1.93"))
            store(tmp,[a]);store(tmp,[b]);store(tmp,[a])
            e=read_events(tmp)
            self.assertEqual(len(e),3)
            self.assertEqual(e[0]["snapshot_sha256"],e[2]["snapshot_sha256"])
            self.assertNotEqual(e[0]["revision_id"],e[2]["revision_id"])

    def test_historical_migration_does_not_invent_first_receipt_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=observation()
            p=path(tmp)
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps(old)+"\n")
            with patch("h1lab.market_v4.datetime") as clock:
                clock.now.return_value=datetime(2026,11,2,12,tzinfo=timezone.utc)
                store(tmp,[])
            events=read_events(tmp)
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]["kind"],"HISTORICAL_BASELINE_IMPORT")
            self.assertEqual(events[0]["known_at"],"2026-11-02T12:00:00+00:00")
            self.assertEqual(events[0]["telegram_original_at"],WHEN.isoformat(timespec="seconds"))
            self.assertEqual(events[0]["edit_date_verified_from_telegram"],False)

    def test_edit_metadata_only_is_still_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=observation()
            store(tmp,[e])
            e2=dict(e,telegram_edit_at="2026-10-28T14:05:00+00:00")
            store(tmp,[e2])
            self.assertEqual(len(read_events(tmp)),2)
            self.assertEqual(read_events(tmp)[1]["kind"],"EDIT_DATE_CHANGED")

    def test_replay_refuses_mutated_old_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp,[observation()])
            f=next((Path(tmp)/"data/lab").glob("v4-revisions-*.jsonl"))
            f.write_text(f.read_text().replace("1.95", "1.96", 1))
            with self.assertRaises(ValueError):
                read_events(tmp)

    def test_projection_mutation_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp,[observation()])
            f=path(tmp)
            f.write_text(f.read_text().replace("1.95","1.96",1))
            with self.assertRaises(ValueError):
                verify_projection(tmp)


if __name__=="__main__":
    unittest.main()

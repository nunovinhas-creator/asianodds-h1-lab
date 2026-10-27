"""Integration-oriented fail-open tests for the shadow capture hooks."""
import contextlib
import io
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from h1lab import cli
from h1lab.core import empty_state, incorporate

NOW=datetime(2026,10,27,14,0,tzinfo=timezone.utc)
MESSAGE=("Dropping Odds: Home vs Away\n🕒 27 Oct 19:00 UTC\n"
         "🏆 Test League\nTotal: 2.5 ↑ 2.75\n"
         "Was 2.5 1.80 2.03\nNow 2.75 1.91 1.90\n")

class ShadowIntegrationTests(unittest.TestCase):
    def test_shadow_inspect_failure_does_not_block_h1(self):
        rows=[]
        with patch("h1lab.shadow_formats.inspect",side_effect=RuntimeError("broken parser")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                cli.observe_shadow(MESSAGE,NOW,7,11,True,rows)
        self.assertEqual(rows,[])
        self.assertIn("LAB_SHADOW_INSPECT_FAILED: RuntimeError",output.getvalue())
        from h1lab.core import parse_alert
        event=parse_alert(MESSAGE,NOW,7,11)
        self.assertIsNotNone(event)
        state=empty_state()
        self.assertEqual(incorporate(state,[event],NOW),1)
        self.assertEqual(len(state["signals"]),1)
        self.assertEqual(len(state["alerts"]),1)

    def test_shadow_storage_failure_is_nonfatal(self):
        with patch("h1lab.shadow_formats.store",side_effect=OSError("disk full")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                cli.persist_shadow([{"event_id":"1:2"}])
        self.assertIn("LAB_SHADOW_STORE_FAILED: OSError",output.getvalue())

    def test_monthly_file_survives_repeated_polling(self):
        from h1lab.shadow_formats import inspect,store
        first=inspect(MESSAGE,NOW,7,11,True)
        second=inspect(MESSAGE,datetime(2026,11,1,tzinfo=timezone.utc),8,11,True)
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp,[first])
            store(tmp,[first,second])
            store(tmp,[first,second])
            october=Path(tmp)/"data/lab/formats-2026-10.jsonl"
            november=Path(tmp)/"data/lab/formats-2026-11.jsonl"
            self.assertEqual(len(october.read_text().splitlines()),1)
            self.assertEqual(len(november.read_text().splitlines()),1)
            self.assertNotIn("Home vs Away",october.read_text())

if __name__=="__main__":
    unittest.main()

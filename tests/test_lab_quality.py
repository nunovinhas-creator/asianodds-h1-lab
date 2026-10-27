import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import lab_quality

class LabQualityTests(unittest.TestCase):
    def test_report_without_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"data").mkdir()
            (root/"data/state.json").write_text(json.dumps({"alerts":[{"market":"total","match_key":"g1"}]}))
            with patch.object(lab_quality,"ROOT",root):
                lab_quality.main()
            d=json.loads((root/"docs/lab/quality.json").read_text())
            self.assertEqual(d["alerts"],1)
            self.assertEqual(d["format_observations"],0)
            self.assertEqual(d["unique_games"],1)
    def test_invalid_utf8_jsonl_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"data/lab").mkdir(parents=True)
            (root/"data/state.json").write_text('{"alerts":[]}')
            (root/"data/lab/formats-2026-10.jsonl").write_bytes(b'\xff\xfe\n{"event_id":"1","format_id":"x"}\n')
            with patch.object(lab_quality,"ROOT",root):
                lab_quality.main()
            d=json.loads((root/"docs/lab/quality.json").read_text())
            self.assertEqual(d["invalid_jsonl_lines"],1)
            self.assertEqual(d["format_observations"],1)
            self.assertIn("generated_at",d)
            self.assertIn("source_commit",d)

    def test_blank_line_not_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"data/lab").mkdir(parents=True)
            (root/"data/state.json").write_text('{"alerts":[]}')
            (root/"data/lab/formats-2026-10.jsonl").write_text('\\n \\n{"event_id":"x","format_id":"f"}\\n')
            with patch.object(lab_quality,"ROOT",root):
                lab_quality.main()
            d=json.loads((root/"docs/lab/quality.json").read_text())
            self.assertEqual(d["invalid_jsonl_lines"],0)
            self.assertEqual(d["format_observations"],1)

    def test_report_monthly_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"data/lab").mkdir(parents=True)
            (root/"data/state.json").write_text('{"alerts":[]}')
            item={"event_id":"x:1","format_id":"f","legacy_parsed":True}
            (root/"data/lab/formats-2026-10.jsonl").write_text(json.dumps(item)+"\n"+json.dumps(item)+"\n")
            with patch.object(lab_quality,"ROOT",root):
                lab_quality.main()
            d=json.loads((root/"docs/lab/quality.json").read_text())
            self.assertEqual(d["format_observations"],1)

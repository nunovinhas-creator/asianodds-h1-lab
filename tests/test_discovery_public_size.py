import copy
import json
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path
from scripts.lab_discoveries import bounded_public, serialize, put, MAX_PUBLIC_BYTES, PUBLIC


class DiscoveryPublicSizeTests(unittest.TestCase):
    def test_repeated_growth_remains_bounded_and_durable_input_is_unchanged(self):
        value = {'patterns': {str(i): {'latest': {'known': i},
                 'points': [{'at': 0, 'payload': 'x'*100}]} for i in range(15)}}
        for cycle in range(100):
            for row in value['patterns'].values():
                row['points'].append({'at':cycle+1, 'payload':'x'*100})
                row['points'] = row['points'][-24:]
            original = copy.deepcopy(value)
            out = bounded_public(value, 12000)
            serialize(out, 12000, PUBLIC)
            self.assertEqual(value, original)
            self.assertTrue(all(row['points'][-1]['at']==cycle+1
                                for row in out['patterns'].values()))

    def test_interrupted_atomic_replace_preserves_published_bytes_then_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'discoveries.json'
            put(path, {'generation':1}, 1000)
            previous=path.read_bytes()
            with patch.object(Path, 'replace', side_effect=OSError('injected disk failure')):
                with self.assertRaises(OSError):
                    put(path, {'generation':2}, 1000)
            self.assertEqual(path.read_bytes(), previous)
            self.assertTrue(put(path, {'generation':2}, 1000))
            self.assertEqual(json.loads(path.read_text()), {'generation':2})

    def test_growing_real_snapshot_fits_without_mutating_history_or_latest(self):
        root = Path(__file__).resolve().parents[1]
        public = json.loads((root / PUBLIC).read_text())
        # Simulate continued growth of the point cache, preserving the real
        # metadata/FT payload. The pre-fix serializer rejects this payload.
        for row in public['patterns'].values():
            row['points'] = (row['points'] * 24)[-24:]
        original = copy.deepcopy(public)
        with self.assertRaises(ValueError):
            serialize(public, MAX_PUBLIC_BYTES, PUBLIC)
        result = bounded_public(public)
        serialize(result, MAX_PUBLIC_BYTES, PUBLIC)
        self.assertEqual(public, original)
        self.assertEqual(set(result['patterns']), set(public['patterns']))
        for key, row in result['patterns'].items():
            self.assertEqual(row['latest'], public['patterns'][key]['latest'])
            self.assertGreaterEqual(len(row['points']), 1)
            self.assertEqual(row['points'][-1], public['patterns'][key]['points'][-1])
        self.assertEqual(result['prospective'], public['prospective'])
        self.assertEqual(result['timeline'], public['timeline'])
        self.assertGreater(result['public_cache']['older_points_omitted'], 0)
        self.assertEqual(bounded_public(public), result)

    def test_unshrinkable_mandatory_evidence_still_fails_closed(self):
        value = {'patterns': {'p': {'latest': 'x'*1000, 'points':[{'at':'now'}]}}}
        with self.assertRaises(ValueError):
            bounded_public(value, 100)

    def test_small_payload_is_not_changed(self):
        value = {'patterns': {'p': {'latest': {}, 'points':[{}]}}}
        self.assertEqual(bounded_public(value), value)

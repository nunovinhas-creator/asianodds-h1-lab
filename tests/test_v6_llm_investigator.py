"""No provider requests or production writes in default/validation paths."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from h1lab import v6_llm_investigator as mod
from scripts import lab_v6_llm_investigator as cli


class InvestigatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        sources = {
            mod.SOURCES[0]: {'schema_version': 1, 'scientific_state': 'INCONCLUSIVO',
                'gates': {k: {'status': 'WARMUP', 'scientific_acceptance': 'BLOCKED',
                              'ratio': 0.95, 'source_eligible': 20, 'frozen_pre_kickoff': 19,
                              'missing_count': 1} for k in ('7_days', '14_days')},
                'ft_knowledge_timeline': {'counts': {
                    'confirmed_event_chronology_consistent_not_independently_proven': 10,
                    'confirmed_event_chronology_invalid': 2, 'eligible_match_without_confirmed_ft': 8}}},
            mod.SOURCES[1]: {'schema_version': 1, 'overall': 'INCONCLUSIVO',
                              'check_result_counts': {'PASS': 1, 'INSUFFICIENT_N': 9}},
            mod.SOURCES[2]: {'schema_version': 1, 'status': 'WARMUP'},
            mod.SOURCES[3]: {'schema_version': 1, 'latest': {'overall': 'INSUFFICIENT_HISTORY'}},
            mod.SOURCES[4]: {'schema_version': 1, 'pattern_catalogue': {
                'G_FIRST_LEAD_LT_6H': {'family': 'TIME', 'description': 'Primeiro alerta a menos de 6h'},
                'M_TOTAL_UP': {'family': '1X2', 'description': 'Movimento de Total para cima'}}},
        }
        for name, body in sources.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(body), encoding='utf-8')
        self.before = self.snapshot()

    def snapshot(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def proposal(self, **kw):
        p = {'status': 'DRAFT', 'topic_id': 'T01',
             'hypothesis': 'Co-observation could have incremental information beyond baseline.',
             'null_hypothesis': 'No incremental information compared with baseline.',
             'test_design': 'Predefine a future cohort and compare matched controls.',
             'falsification': 'Reject if out-of-sample comparison fails.',
             'confounders': ['Competition mix'], 'source_refs': [mod.SOURCES[0]]}
        p.update(kw)
        return p

    def test_dossier_never_writes_or_uses_telegrams_or_betting(self):
        packet = mod.build_packet(self.root)
        self.assertEqual(packet['status'], 'SHADOW_RESEARCH_DOSSIER_NOT_VALIDATION')
        self.assertEqual(packet['facts']['missing_capture'], 1)
        self.assertEqual(packet['facts']['scientific_state'], 'INCONCLUSIVO')
        self.assertEqual(len(packet['topics']), 4)
        self.assertEqual(len(packet['feature_catalogue']), 2)
        self.assertIn('M_TOTAL_UP', json.dumps(packet))
        self.assertEqual(self.snapshot(), self.before)
        self.assertNotIn('games', json.dumps(packet))
        self.assertNotIn('api_key', json.dumps(packet).lower())

    def test_invalid_gates_or_missing_and_corrupt_sources_fail_closed(self):
        target = self.root / mod.SOURCES[0]
        body = json.loads(target.read_text())
        body['gates']['7_days']['scientific_acceptance'] = 'PASS'
        target.write_text(json.dumps(body))
        with self.assertRaises(ValueError): mod.build_packet(self.root)
        body['gates']['7_days']['scientific_acceptance'] = 'BLOCKED'
        body['gates']['7_days']['missing_count'] = 2
        target.write_text(json.dumps(body))
        with self.assertRaises(ValueError): mod.build_packet(self.root)
        target.write_text('{"schema_version":1,"x":1e999}')
        with self.assertRaises(ValueError): mod.build_packet(self.root)
        target.unlink()
        with self.assertRaises(ValueError): mod.build_packet(self.root)

    def test_draft_review_rejects_invalid_fields_and_unsupported_references(self):
        packet = mod.build_packet(self.root)
        p = self.proposal()
        out = mod.validate_proposals(packet, {'schema_version': 1, 'proposals': [p]})
        self.assertEqual(out['status'], 'DRAFT_UNVALIDATED_HUMAN_REVIEW_REQUIRED')
        for bad in ({**p, 'status': 'VALIDATED'}, {**p, 'source_refs': ['data/results.csv']},
                    {**p, 'recommend_bet': 'Yes'}, {**p, 'hypothesis': ''}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    mod.validate_proposals(packet, {'schema_version': 1, 'proposals': [bad]})
        with self.assertRaises(ValueError):
            mod.validate_proposals(packet, {'schema_version': 1, 'proposals': [p, p]})
        with self.assertRaises(ValueError):
            mod.validate_proposals(packet, {'schema_version': 1, 'proposals': [p] * 5})
        self.assertEqual(self.snapshot(), self.before)

    def test_network_is_explicit_and_https_only(self):
        packet = mod.build_packet(self.root)
        with self.assertRaises(ValueError):
            mod.invoke(packet, endpoint='http://example.test/v1/chat/completions', model='test')
        with self.assertRaises(SystemExit):
            cli.main(['--root', str(self.root), '--mode', 'invoke', '--endpoint', 'https://example.test/v1/chat/completions', '--model', 'test'])
        self.assertEqual(self.snapshot(), self.before)

    def test_mock_provider_only_gets_aggregates_and_returns_unvalidated_drafts(self):
        packet = mod.build_packet(self.root)
        good = json.dumps({'schema_version': 1, 'proposals': [self.proposal()]})
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                return json.dumps({'choices': [{'message': {'content': good}}]}).encode()
        calls = []
        def opener(request, timeout):
            calls.append((request, timeout))
            return Response()
        out = mod.invoke(packet, endpoint='https://example.test/v1/chat/completions',
                         model='test', api_key='secret-DO-NOT-PRINT', opener=opener)
        self.assertEqual(out['status'], 'DRAFT_UNVALIDATED_HUMAN_REVIEW_REQUIRED')
        self.assertEqual(len(calls), 1)
        request, timeout = calls[0]
        payload = json.loads(request.data)
        self.assertEqual(timeout, 30)
        self.assertNotIn('secret-DO-NOT-PRINT', request.data.decode())
        self.assertEqual(payload['temperature'], 0)
        self.assertEqual(payload['max_tokens'], 1600)
        self.assertEqual(self.snapshot(), self.before)

    def test_workflow_only_manual_no_provider_credentials(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/v6-llm-investigator.yml').read_text()
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('schedule:', workflow)
        self.assertNotIn('push:', workflow)
        self.assertNotIn('MASTER_BRAIN_LLM_API_KEY', workflow)
        self.assertNotIn('--mode invoke', workflow)
        self.assertIn('--mode dossier', workflow)
        self.assertIn('contents: read', workflow)

    def test_cli_dossier_stdout_only(self):
        from contextlib import redirect_stdout
        from io import StringIO
        stdout = StringIO()
        with redirect_stdout(stdout):
            cli.main(['--root', str(self.root)])
        self.assertEqual(json.loads(stdout.getvalue())['schema_version'], 1)
        self.assertEqual(self.snapshot(), self.before)


if __name__ == '__main__':
    unittest.main()

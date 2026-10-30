"""No provider requests or production writes in default/validation paths."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

from h1lab import v6_llm_investigator as mod
from scripts import lab_v6_llm_investigator as cli
from scripts import lab_v6_llm_publish as publication


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
                'M_TOTAL_LINE_UP': {'family': 'TOTAL', 'description': 'Movimento de Total para cima'},
                'G_MULTI_ALERT': {'family': 'SEQUENCE', 'description': 'Varios alertas antes do KO'},
                'G_SINGLE_ALERT': {'family': 'SEQUENCE', 'description': 'Um alerta antes do KO'},
                'M_IMPLIED_GOALS_FLAT': {'family': 'IMPLIED', 'description': 'Golos implicitos estaveis'}}},
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
        p = {'status': 'DRAFT', 'topic_id': 'T02',
             'feature_codes': ['G_MULTI_ALERT', 'M_IMPLIED_GOALS_FLAT'],
             'outcome': 'OVER_2_5', 'baseline': 'MARKET_MODEL_OVER25', 'metric': 'BRIER_SCORE',
             'hypothesis': 'Two V5 features can add information to the market baseline.',
             'null_hypothesis': 'There is no improvement over the market reference.',
             'control_group': 'Future games with matched initial probabilities and kickoff lead time.',
             'test_design': 'Freeze G_MULTI_ALERT and M_IMPLIED_GOALS_FLAT before kickoff, compare Brier OOS.',
             'falsification': 'Reject unless out-of-sample improvement is replicated.',
             'data_needed': ['Verified future pre-kickoff snapshots', 'Independently verified 90-minute FT'],
             'confounders': ['Competition mix'], 'source_refs': [mod.SOURCES[4]]}
        p.update(kw)
        return p

    def test_dossier_never_writes_or_uses_telegrams_or_betting(self):
        packet = mod.build_packet(self.root)
        self.assertEqual(packet['status'], 'SHADOW_RESEARCH_DOSSIER_NOT_VALIDATION')
        self.assertEqual(packet['facts']['missing_capture'], 1)
        self.assertEqual(packet['facts']['scientific_state'], 'INCONCLUSIVO')
        self.assertEqual(len(packet['topics']), 4)
        self.assertEqual(len(packet['feature_catalogue']), 5)
        self.assertIn('M_TOTAL_LINE_UP', json.dumps(packet))
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
        for bad in (
            {**p, 'status': 'VALIDATED'},
            {**p, 'source_refs': ['data/results.csv']},
            {**p, 'source_refs': [mod.SOURCES[0]]},
            {**p, 'recommend_bet': 'Yes'},
            {**p, 'hypothesis': ''},
            {**p, 'feature_codes': ['G_MULTI_ALERT', 'NOT_EXIST']},
            {**p, 'feature_codes': ['G_MULTI_ALERT', 'G_MULTI_ALERT']},
            {**p, 'feature_codes': ['G_MULTI_ALERT', 'G_SINGLE_ALERT']},
            {**p, 'feature_codes': ['G_MULTI_ALERT', 'M_TOTAL_LINE_UP']},
            {**p, 'outcome': 'BTTS_YES'},
            {**p, 'baseline': 'BOOKMAKER_EV'},
            {**p, 'metric': 'ROI'},
            {**p, 'control_group': ''},
            {**p, 'data_needed': []},
        ):
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
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        self.assertEqual(len(payload['messages']), 2)
        user = json.loads(payload['messages'][1]['content'])
        self.assertEqual(user['exact_output_example']['schema_version'], 1)
        self.assertEqual(len(user['exact_output_example']['proposals']), 1)
        self.assertEqual(user['exact_output_example']['proposals'][0]['status'], 'DRAFT')
        self.assertEqual(user['exact_output_example']['proposals'][0]['feature_codes'], ['G_MULTI_ALERT', 'M_IMPLIED_GOALS_FLAT'])
        self.assertEqual(user['exact_output_example']['proposals'][0]['metric'], 'BRIER_SCORE')
        self.assertEqual(user['exact_output_example'], packet['response_schema'])
        self.assertIn('proposals', payload['messages'][0]['content'])
        self.assertEqual(self.snapshot(), self.before)

    def test_model_contract_mismatch_is_fail_closed_with_safe_diagnostics(self):
        packet = mod.build_packet(self.root)
        class Response:
            status = 200
            def __init__(self, content, finish_reason):
                self.payload = json.dumps({
                    'choices': [{'message': {'content': content}, 'finish_reason': finish_reason}]
                }).encode('utf-8')
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return self.payload
        for invalid, reason, expect in [
            ({'response': 'TOP_SECRET_MODEL_TEXT'}, 'stop', 'unexpected_keys=True'),
            ({'proposals': [self.proposal()]}, 'length', 'version_1=False'),
            ({'schema_version': 1, 'proposals': 'TOP_SECRET_MODEL_TEXT'}, 'stop', 'Unbounded or empty'),
        ]:
            with self.subTest(invalid=invalid):
                response = Response(json.dumps(invalid), reason)
                with self.assertRaises(ValueError) as caught:
                    mod.invoke(packet, endpoint='https://example.test/v1/chat/completions',
                               model='test', opener=lambda req, timeout: response)
                error = str(caught.exception)
                self.assertIn('LLM_RESPONSE_REJECTED', error)
                self.assertIn(expect, error)
                self.assertNotIn('TOP_SECRET_MODEL_TEXT', error)
        self.assertEqual(self.snapshot(), self.before)

    def test_malformed_proposal_fields_fail_as_validation_errors(self):
        packet = mod.build_packet(self.root)
        for malformed in [
            self.proposal(topic_id={'unexpected': 'object'}),
            self.proposal(source_refs=[{'unexpected': 'object'}]),
            self.proposal(source_refs=[['unexpected']]),
            self.proposal(feature_codes=[{'bad': True}, 'M_TOTAL_LINE_UP']),
            self.proposal(feature_codes='G_MULTI_ALERT'),
            self.proposal(feature_codes=['G_MULTI_ALERT', 123]),
        ]:
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    mod.validate_proposals(packet, {'schema_version': 1, 'proposals': [malformed]})

    def test_workflow_only_manual_no_provider_credentials(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/v6-llm-investigator.yml').read_text()
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('schedule:', workflow)
        self.assertNotIn('push:', workflow)
        self.assertIn('secrets.MASTER_BRAIN_LLM_API_KEY', workflow)
        self.assertIn('secrets.CLOUDFLARE_ACCOUNT_ID', workflow)
        self.assertIn("inputs.mode == 'cloudflare_once'", workflow)
        self.assertIn('CONSUMIR_IA_UMA_VEZ', workflow)
        self.assertNotIn('--mode invoke', workflow)
        self.assertIn('--mode dossier', workflow)
        self.assertIn('contents: read', workflow)

    def test_cloudflare_single_shot_requires_opt_in_and_secrets(self):
        args = ['--root', str(self.root), '--mode', 'cloudflare']
        with self.assertRaises(SystemExit):
            cli.main(args)
        with patch.dict(os.environ, {'CLOUDFLARE_ACCOUNT_ID': 'a' * 32}, clear=True):
            with self.assertRaises(SystemExit):
                cli.main(args + ['--allow-network'])
        with patch.dict(os.environ, {
            'CLOUDFLARE_ACCOUNT_ID': 'a' * 32,
            'MASTER_BRAIN_LLM_API_KEY': 'fake-private-test-token',
        }, clear=True):
            with patch.object(cli, 'invoke', return_value={'status': 'DRAFT_UNVALIDATED_HUMAN_REVIEW_REQUIRED'}) as invoke_mock:
                with redirect_stdout(StringIO()):
                    cli.main(args + ['--allow-network'])
                invoke_mock.assert_called_once()
                kw = invoke_mock.call_args.kwargs
                self.assertEqual(kw['model'], '@cf/meta/llama-3.1-8b-instruct-fast')
                self.assertEqual(kw['endpoint'], 'https://api.cloudflare.com/client/v4/accounts/' + 'a' * 32 + '/ai/v1/chat/completions')
                self.assertEqual(kw['api_key'], 'fake-private-test-token')
        self.assertEqual(self.snapshot(), self.before)


    def test_manual_publication_provenance_and_immutable_archive(self):
        packet = mod.build_packet(self.root)
        output = mod.validate_proposals(packet, {
            'schema_version': 1, 'proposals': [self.proposal()]
        })
        commit = 'a' * 40
        first = publication.publish(self.root, output, run_id='41039239732',
                    commit_sha=commit, when='2026-10-30T10:15:00Z')
        self.assertEqual(first['state'], publication.STATUS)
        self.assertEqual(first['empirically_validated_strategies'], 0)
        self.assertIsNone(first['latest']['neurons_consumed'])
        self.assertEqual(first['latest']['llm_calls'], 1)
        self.assertEqual(first['latest']['summary']['feature_codes'],
                         ['G_MULTI_ALERT', 'M_IMPLIED_GOALS_FLAT'])
        self.assertGreater(first['search_space']['possible_pairs_distinct_families'], 0)
        self.assertEqual(len(first['history']), 1)
        self.assertEqual(json.loads((self.root / publication.INDEX).read_text()), first)
        archived = json.loads((self.root / publication.ARCHIVE / '41039239732.json').read_text())
        self.assertEqual(archived, first['latest'])
        second = publication.publish(self.root, output, run_id='41039239733',
                    commit_sha=commit, when='2026-10-30T10:16:00Z')
        self.assertEqual([x['run_id'] for x in second['history']], [41039239733, 41039239732])
        self.assertEqual(json.loads((self.root / publication.ARCHIVE / '41039239732.json').read_text()), archived)
        with self.assertRaises(ValueError):
            publication.publish(self.root, output, run_id='41039239732',
                                commit_sha=commit, when='2026-10-30T10:17:00Z')

    def test_publication_rejects_forgery_and_invalid_identifiers(self):
        packet = mod.build_packet(self.root)
        valid = mod.validate_proposals(packet, {
            'schema_version': 1, 'proposals': [self.proposal()]
        })
        bad = json.loads(json.dumps(valid))
        bad['source_sha256'][mod.SOURCES[0]] = '0' * 64
        with self.assertRaises(ValueError):
            publication.publish(self.root, bad, run_id='41039239735',
                                commit_sha='a' * 40, when='2026-10-30T10:00:00Z')
        with self.assertRaises(ValueError):
            publication.publish(self.root, valid, run_id='../oops',
                                commit_sha='a' * 40, when='2026-10-30T10:00:00Z')
        with self.assertRaises(ValueError):
            publication.publish(self.root, valid, run_id='41039239735',
                                commit_sha='not-a-sha', when='2026-10-30T10:00:00Z')
        with self.assertRaises(ValueError):
            publication.publish(self.root, {'status': 'VALIDATED', 'proposals': []},
                                run_id='41039239735', commit_sha='a' * 40,
                                when='2026-10-30T10:00:00Z')
        self.assertEqual(self.snapshot(), self.before)

    def test_web_view_read_only_and_escapes_generated_text(self):
        base = Path(__file__).resolve().parents[1]
        page = (base / 'docs/llm-investigator.html').read_text()
        js = (base / 'docs/llm-investigator.js').read_text()
        home = (base / 'docs/index.html').read_text()
        workflow = (base / '.github/workflows/v6-llm-investigator.yml').read_text()
        self.assertIn('llm-investigator.html', home)
        self.assertIn('llm-investigator-index.json', page)
        self.assertIn('textContent', js)
        self.assertNotIn('innerHTML', js)
        self.assertIn('needs: investigator', workflow)
        self.assertIn('contents: write', workflow)
        self.assertIn('github.ref ==', workflow)
        self.assertIn('actions/download-artifact@v4', workflow)
        self.assertIn('llm-investigator-runs/', workflow)
        self.assertNotIn('schedule:', workflow)

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

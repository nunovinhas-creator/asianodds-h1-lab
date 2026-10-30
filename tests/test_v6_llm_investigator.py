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
        self.assertEqual(len(packet['topics']), 5)
        self.assertIn('T05', {t['id'] for t in packet['topics']})
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
        q = json.loads((self.root / publication.QUEUE).read_text())
        self.assertEqual(q['previously_proposed_unique'], 1)
        self.assertEqual(q['remaining'], 15)
        self.assertEqual(q['distinct_family_space'], {'2': 9, '3': 7})
        self.assertEqual(first['search_space']['possible_pairs_distinct_families'], 9)
        self.assertEqual(first['search_space']['possible_triples_distinct_families'], 7)
        self.assertNotIn('possible_triples_two_or_more_families', first['search_space'])
        self.assertEqual(q['archive_sha256'].keys(), {'41039239732.json'})
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
        q2 = json.loads((self.root / publication.QUEUE).read_text())
        self.assertEqual(q2['previously_proposed_unique'], 1)
        self.assertEqual(len(q2['archive_sha256']), 2)
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
        # Every incompatible schema change must refresh the static-script URL.
        self.assertIn('llm-investigator.js?v=20261030-autonomous-v1', page)
        self.assertIn('llm-discovery-plan.js?v=20261030-autonomous-v1', page)
        self.assertNotIn('llm-investigator.js?v=20261030-initial-state', page)
        self.assertIn('possible_triples_distinct_families', js)
        self.assertNotIn('possible_triples_two_or_more_families', js)
        self.assertIn('textContent', js)
        self.assertNotIn('innerHTML', js)
        self.assertIn('needs: investigator', workflow)
        self.assertIn('contents: write', workflow)
        self.assertIn('github.ref ==', workflow)
        self.assertIn('actions/download-artifact@v4', workflow)
        self.assertIn('llm-investigator-runs/', workflow)
        self.assertIn('docs/lab/llm-discovery-plan.json', workflow)
        self.assertNotIn('schedule:', workflow)



    def test_public_index_accepts_bootstrap_and_future_real_publications(self):
        from collections import Counter
        base = Path(__file__).resolve().parents[1]
        snapshot = json.loads((base / 'docs/lab/llm-investigator-index.json').read_text())
        actual = json.loads((base / 'docs/lab/pattern-research.json').read_text())
        catalogue = actual['pattern_catalogue']
        counts = Counter(item['family'] for item in catalogue.values())
        n = len(catalogue)
        pairs = n * (n - 1) // 2 - sum(k * (k - 1) // 2 for k in counts.values())
        triples = n * (n - 1) * (n - 2) // 6 - sum(
            k * (k - 1) * (k - 2) // 6 for k in counts.values()
        )
        self.assertEqual(snapshot['state'], publication.STATUS)
        self.assertEqual(snapshot['schema_version'], 1)
        self.assertEqual(snapshot['empirically_validated_strategies'], 0)
        space = snapshot['search_space']
        self.assertNotIn('possible_triples_two_or_more_families', space)
        self.assertEqual(space['features_in_catalogue'], 49)
        self.assertEqual(space['possible_pairs_distinct_families'], 1056)
        self.assertEqual(space['possible_triples_distinct_families'], 13134)
        queue = json.loads((base / 'docs/lab/llm-discovery-plan.json').read_text())
        self.assertEqual(queue['remaining'] + queue['previously_proposed_unique'], 14190)
        self.assertEqual(queue['distinct_family_space'], {'2': 1056, '3': 13134})
        self.assertGreaterEqual(space['features_in_catalogue'], 2)
        self.assertGreaterEqual(space['possible_pairs_distinct_families'], 0)
        self.assertGreaterEqual(space['possible_triples_distinct_families'], 0)
        self.assertEqual(space['meaning'],
                         'SEARCH_SPACE_ONLY_NO_LLM_CALLS_OR_EMPIRICAL_TESTS')
        self.assertNotIn('api_key', json.dumps(snapshot).lower())
        if snapshot.get('latest') is None:
            self.assertEqual(snapshot['history'], [])
            self.assertEqual(snapshot['llm_executions_recorded'], 0)
            self.assertEqual(snapshot['legacy_successful_manual_run']['run_id'], 41039239732)
            self.assertEqual(snapshot['legacy_successful_manual_run']['status'],
                             'LEGACY_DRAFT_NOT_SCIENTIFICALLY_VALIDATED')
            raw = (base / 'docs/lab/pattern-research.json').read_bytes()
            source_blob = hashlib.sha1(
                b'blob ' + str(len(raw)).encode('ascii') + bytes([0]) + raw
            ).hexdigest()
            self.assertRegex(snapshot['catalogue_provenance']['github_blob_sha'],
                             r'^[0-9a-f]{40}$')
            # Index is a frozen observation. Live V5 data can change after
            # publication; only assert exact counts for matching source blobs.
            if snapshot['catalogue_provenance']['github_blob_sha'] == source_blob:
                self.assertEqual(space['features_in_catalogue'], n)
                self.assertEqual(space['possible_pairs_distinct_families'], pairs)
                self.assertEqual(space['possible_triples_two_or_more_families'], triples)
        else:
            # After a real manually approved AI run the index is overwritten
            # by the publisher. Never demand the bootstrap to remain forever.
            latest = snapshot['latest']
            self.assertEqual(latest['state'], publication.STATUS)
            self.assertEqual(snapshot['history'][0]['run_id'], latest['run_id'])
            self.assertGreaterEqual(snapshot['llm_executions_recorded'], 1)
            self.assertEqual(latest['scientific_acceptance'], 'INCONCLUSIVO')
            self.assertTrue((base / publication.ARCHIVE /
                             (str(latest['run_id']) + '.json')).is_file())
        js = (base / 'docs/llm-investigator.js').read_text()
        self.assertIn('renderLegacy', js)
        self.assertIn('v.latest === null', js)
        self.assertIn('history.replaceChildren', js)
        self.assertNotIn('innerHTML', js)

    def test_first_real_new_run_replaces_bootstrap_without_forging_history(self):
        base = Path(__file__).resolve().parents[1]
        # Real repository state is now nonempty. Construct a true initial
        # snapshot explicitly so this test remains valid after new AI runs.
        bootstrap = json.loads((base / 'docs/lab/llm-investigator-index.json').read_text())
        bootstrap['latest'] = None
        bootstrap['history'] = []
        bootstrap['llm_executions_recorded'] = 0
        initial = self.root / publication.INDEX
        initial.parent.mkdir(parents=True, exist_ok=True)
        initial.write_text(json.dumps(bootstrap))
        packet = mod.build_packet(self.root)
        output = mod.validate_proposals(packet, {
            'schema_version': 1, 'proposals': [self.proposal()]
        })
        result = publication.publish(self.root, output,
                   run_id='41039239734', commit_sha='b' * 40,
                   when='2026-10-30T10:30:00Z')
        self.assertEqual(result['latest']['run_id'], 41039239734)
        self.assertEqual(result['llm_executions_recorded'], 1)
        plan_result = json.loads((self.root / publication.QUEUE).read_text())
        self.assertEqual(plan_result['previously_proposed_unique'], 1)
        self.assertEqual(plan_result['remaining'] + plan_result['previously_proposed_unique'], 16)
        self.assertEqual([x['run_id'] for x in result['history']], [41039239734])
        self.assertEqual(result['empirically_validated_strategies'], 0)
        self.assertIsNotNone(result['latest']['proposals'][0]['feature_codes'])

    def test_usage_is_allowlisted_and_unknown_is_not_free(self):
        usage = mod.provider_usage({'usage': {'prompt_tokens': 100,
            'completion_tokens': 20, 'total_tokens': 120,
            'secret': 'NEVER_EXPORT'}}, '@cf/meta/llama-3.1-8b-instruct-fast')
        self.assertEqual(usage['tokens']['total_tokens'], 120)
        self.assertIsNone(usage['neurons_consumed'])
        self.assertFalse(usage['account_quota_verified'])
        self.assertNotIn('NEVER_EXPORT', json.dumps(usage))
        self.assertEqual(mod.provider_usage({}, 'x')['tokens'], {})
        output = mod.validate_proposals(mod.build_packet(self.root),
            {'schema_version': 1, 'proposals': [self.proposal()]})
        output['provider_usage'] = usage
        result = publication.publish(self.root, output, run_id='41039239739',
            commit_sha='c' * 40, when='2026-10-30T11:00:00Z')
        self.assertEqual(result['latest']['provider_usage'], usage)

    def test_three_features_require_three_families(self):
        p = self.proposal(feature_codes=['G_MULTI_ALERT', 'G_SINGLE_ALERT', 'M_IMPLIED_GOALS_FLAT'],
            test_design='Freeze G_MULTI_ALERT G_SINGLE_ALERT M_IMPLIED_GOALS_FLAT before kickoff.')
        with self.assertRaises(ValueError):
            mod.validate_proposals(mod.build_packet(self.root), {'schema_version': 1, 'proposals': [p]})

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

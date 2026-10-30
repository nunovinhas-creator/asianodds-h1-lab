"""Autonomous V6 discovery contract tests: wholly synthetic, never network."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from tests import test_v6_llm_investigator as fixtures
from h1lab import v6_llm_investigator as investigator
from scripts import lab_v6_llm_autonomous as autonomy
from scripts import lab_v6_llm_publish as publisher


class AutonomousResearchTests(TestCase):
    def setUp(self):
        self.fixtures = fixtures.InvestigatorTests()
        self.fixtures.setUp()
        self.addCleanup(self.fixtures.doCleanups)
        self.root = self.fixtures.root
        self.packet = investigator.build_packet(self.root)
        self.now = datetime(2026, 10, 30, 13, 44, tzinfo=timezone.utc)
        self.env = {
            'GITHUB_REF': 'refs/heads/main',
            'GITHUB_EVENT_NAME': 'schedule',
            'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_EVENT_SCHEDULE': autonomy.SCHEDULE,
            'CLOUDFLARE_ACCOUNT_ID': 'a' * 32,
            'MASTER_BRAIN_LLM_API_KEY': 'FAKE_TOKEN_NEVER_LOG',
        }

    def good_for(self, codes):
        return investigator.validate_proposals(self.packet, {
            'schema_version': 1,
            'proposals': [self.fixtures.proposal(
                topic_id='T05', feature_codes=list(codes),
                test_design='Freeze ' + ', '.join(codes) + ' before KO; compare OOS Brier score by match.'
            )]
        })

    def test_preview_is_offline_deterministic_and_novel(self):
        before = self.fixtures.snapshot()
        one = autonomy.run(self.root, mode='preview', now=self.now)
        two = autonomy.run(self.root, mode='preview', now=self.now)
        self.assertEqual(one, two)
        self.assertEqual(one['status'], 'PREVIEW_ONLY_NO_LLM_CALLS')
        self.assertTrue(1 <= len(one['candidate_pool']) <= 3)
        self.assertEqual(self.fixtures.snapshot(), before)
        for candidate in one['candidate_pool']:
            self.assertRegex(candidate['candidate_id'], r'^[0-9a-f]{64}$')

    def test_scheduled_call_is_single_and_publisher_verifies(self):
        chosen = autonomy.choose_candidates(self.root)['choices']
        codes = chosen[0]['feature_codes']
        output = self.good_for(codes)
        with patch.object(autonomy, 'invoke', return_value=output) as ai:
            result = autonomy.run(self.root, mode='live', allow_network=True,
                                  env=self.env, now=self.now)
        ai.assert_called_once()
        self.assertEqual(ai.call_args.kwargs['candidate_options'],
                         [x['feature_codes'] for x in chosen])
        self.assertEqual(result['autonomy']['trigger'], 'schedule')
        self.assertEqual(result['autonomy']['candidate_id'],
                         autonomy.candidate_id(codes))
        self.assertNotIn('FAKE_TOKEN_NEVER_LOG', json.dumps(result))
        rec = publisher.publish(self.root, result, run_id='41046486111',
                    commit_sha='b' * 40, when='2026-10-30T13:44:00Z')
        self.assertEqual(rec['latest']['scientific_acceptance'], 'INCONCLUSIVO')
        self.assertEqual(rec['latest']['autonomy']['trigger'], 'schedule')
        self.assertEqual(rec['empirically_validated_strategies'], 0)
        q = json.loads((self.root / publisher.QUEUE).read_text())
        self.assertEqual(q['previously_proposed_unique'], 1)
        self.assertNotIn(result['autonomy']['candidate_id'],
                         [x['candidate_id'] for x in q['queue']])

    def test_fails_closed_before_network_for_unapproved_or_replayed_run(self):
        for update in [
            {'GITHUB_REF': 'refs/heads/feature'},
            {'GITHUB_EVENT_NAME': 'push'},
            {'GITHUB_EVENT_SCHEDULE': '*/5 * * * *'},
            {'GITHUB_RUN_ATTEMPT': '2'},
            {'MASTER_BRAIN_LLM_API_KEY': ''},
            {'CLOUDFLARE_ACCOUNT_ID': 'BAD'},
        ]:
            with self.subTest(update=update):
                env = dict(self.env, **update)
                with patch.object(autonomy, 'invoke') as ai:
                    with self.assertRaises(ValueError):
                        autonomy.run(self.root, mode='live', allow_network=True,
                                     env=env, now=self.now)
                    ai.assert_not_called()
        with patch.object(autonomy, 'invoke') as ai:
            with self.assertRaises(ValueError):
                autonomy.run(self.root, mode='live', env=self.env, now=self.now)
            ai.assert_not_called()

    def test_manual_live_requires_explicit_confirmation(self):
        env = dict(self.env, GITHUB_EVENT_NAME='workflow_dispatch')
        with patch.object(autonomy, 'invoke') as ai:
            with self.assertRaises(ValueError):
                autonomy.run(self.root, mode='live', allow_network=True,
                             env=env, now=self.now)
            ai.assert_not_called()
        codes = autonomy.choose_candidates(self.root)['choices'][0]['feature_codes']
        with patch.object(autonomy, 'invoke', return_value=self.good_for(codes)) as ai:
            result = autonomy.run(self.root, mode='live', allow_network=True,
                     env=env, confirm=autonomy.AUTONOMY_CONFIRM, now=self.now)
        ai.assert_called_once()
        self.assertEqual(result['autonomy']['trigger'], 'workflow_dispatch')

    def test_auto_model_supplies_text_not_candidate_identity(self):
        pool = autonomy.choose_candidates(self.root)['choices']
        codes = pool[0]['feature_codes']
        complete = self.good_for(codes)['proposals'][0]
        fields = ('hypothesis', 'null_hypothesis', 'control_group',
                  'falsification', 'data_needed', 'confounders')
        model_reply = {'schema_version': 1,
                       'analysis': {k: complete[k] for k in fields}}

        class Response:
            status = 200
            def __init__(self, obj):
                self.body = json.dumps({'choices': [{
                    'message': {'content': json.dumps(obj)},
                    'finish_reason': 'stop'}]}).encode()
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return self.body

        requests = []
        def opener(req, timeout):
            requests.append(req)
            return Response(model_reply)

        result = investigator.invoke(self.packet,
            endpoint='https://example.test/v1/chat/completions',
            model='fake', opener=opener,
            candidate_options=[p['feature_codes'] for p in pool])
        self.assertEqual(result['status'], 'DRAFT_UNVALIDATED_HUMAN_REVIEW_REQUIRED')
        self.assertEqual(result['proposals'][0]['feature_codes'], codes)
        self.assertEqual(result['proposals'][0]['topic_id'], 'T05')
        self.assertEqual(result['proposals'][0]['metric'], 'LOG_LOSS')
        self.assertEqual(len(requests), 1)
        user = json.loads(json.loads(requests[0].data)['messages'][1]['content'])
        self.assertEqual(user['fixed_codes'], codes)
        self.assertEqual(set(user['response_schema']['analysis']), set(fields))
        self.assertIn('Log Loss', user['response_schema']['analysis']['falsification'])
        self.assertNotIn('candidate_options', user)
        self.assertTrue(all(f['code'] in codes for f in user['feature_catalogue']))

        # Even a valid-looking response cannot smuggle a different code into
        # free-text analysis. The output remains unpublishable.
        foreign = next(f['code'] for f in self.packet['feature_catalogue']
                       if f['code'] not in codes and f['code'].startswith(('G_', 'M_')))
        bad = json.loads(json.dumps(model_reply))
        bad['analysis']['hypothesis'] += ' E tambem ' + foreign + '.'
        with self.assertRaisesRegex(ValueError, 'AUTO_LLM_TEXT_REFERENCES_UNAPPROVED_FEATURE') as rejected:
            investigator.invoke(self.packet,
                endpoint='https://example.test/v1/chat/completions',
                model='fake', opener=lambda req, timeout: Response(bad),
                candidate_options=[p['feature_codes'] for p in pool])
        self.assertEqual(rejected.exception.audit['llm_calls'], 1)
        self.assertEqual(rejected.exception.audit['status'], 'REJECTED_NOT_PUBLISHED')

        # Legacy whole-proposal response must not be silently reinterpreted.
        with self.assertRaisesRegex(ValueError, 'AUTO_LLM_ANALYSIS_CONTRACT_INVALID'):
            investigator.invoke(self.packet,
                endpoint='https://example.test/v1/chat/completions',
                model='fake', opener=lambda req, timeout: Response({
                    'schema_version': 1, 'proposals': [complete]}),
                candidate_options=[p['feature_codes'] for p in pool])

    def test_publication_rejects_forged_provenance(self):
        codes = autonomy.choose_candidates(self.root)['choices'][0]['feature_codes']
        data = self.good_for(codes)
        data['autonomy'] = {
            'schema_version': 1, 'trigger': 'schedule',
            'candidate_id': '0' * 64, 'candidate_pool_ids': ['0' * 64],
            'selection_policy': 'HASH_ORDER_OUTCOME_BLIND_PREFER_PAIRS_ONE_TRIPLE',
            'daily_scheduled_call_slots': 4,
            'account_neurons_verified': False,
            'status': 'SHADOW_EXPLORATION_NOT_VALIDATION'}
        with self.assertRaisesRegex(ValueError, 'INVALID_AUTONOMOUS_PROVENANCE'):
            publisher.publish(self.root, data, run_id='41046486112',
                        commit_sha='b' * 40, when='2026-10-30T13:44:00Z')

    def test_real_catalogue_prompt_stays_bounded_without_network(self):
        root = Path(__file__).resolve().parents[1]
        packet = investigator.build_packet(root)
        pool = autonomy.choose_candidates(root)['choices']
        codes = pool[0]['feature_codes']
        example = self.fixtures.proposal(
            topic_id='T05', feature_codes=codes,
            test_design='Freeze ' + ', '.join(codes) + ' before KO and compare OOS Brier.'
        )
        fields = ('hypothesis', 'null_hypothesis', 'control_group',
                  'falsification', 'data_needed', 'confounders')
        response = {'schema_version': 1, 'analysis': {k: example[k] for k in fields}}
        mock_reply = json.dumps({'choices': [{
            'message': {'content': json.dumps(response)},
            'finish_reason': 'stop',
        }]}, ensure_ascii=False).encode('utf-8')
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, size): return mock_reply
        requests = []
        def opener(req, timeout):
            requests.append(req)
            return Response()
        result = investigator.invoke(packet,
              endpoint='https://example.test/v1/chat/completions',
              model='fake', api_key='DO_NOT_LOG',
              candidate_options=[p['feature_codes'] for p in pool], opener=opener)
        self.assertEqual(result['proposals'][0]['feature_codes'], codes)
        self.assertEqual(len(requests), 1)
        self.assertLessEqual(len(requests[0].data), 20_000)
        self.assertNotIn(b'DO_NOT_LOG', requests[0].data)
        user = json.loads(json.loads(requests[0].data)['messages'][1]['content'])
        self.assertEqual(user['fixed_codes'], codes)
        self.assertNotIn('feature_codes', user['response_schema']['analysis'])

    def test_workflow_uses_at_most_four_slots_with_isolated_writer(self):
        root = Path(__file__).resolve().parents[1]
        wf = (root / '.github/workflows/v6-llm-autonomous.yml').read_text()
        manual = (root / '.github/workflows/v6-llm-investigator.yml').read_text()
        self.assertIn("cron: '43 1,7,13,19 * * *'", wf)
        self.assertIn('v6-llm-global', wf)
        self.assertIn('v6-llm-global', manual)
        self.assertIn('needs: discover', wf)
        self.assertIn('contents: write', wf)
        self.assertIn('contents: read', wf)
        self.assertIn('AUTONOMIA_LLM_UMA_VEZ', wf)
        self.assertIn('python -m scripts.lab_v6_llm_autonomous --mode live --allow-network', wf)
        self.assertNotIn('re-run', wf.lower())
        self.assertEqual(autonomy.MAX_DAILY_AUTOMATED_REQUESTS, 4)

"""One-shot activation guard: with llm_schedule_live_enabled=false (the default), a cron
run can never reach the quota controller or the provider, even if llm_live_enabled=true.
Only workflow_dispatch(mode=live_once, INVESTIGAR_UMA_VEZ), attempt 1, on main passes."""
import json
import unittest
from pathlib import Path

from h1lab.research_gates import DEFAULT_CONFIG, load_config
from scripts.lab_research_cycle import LIVE_CONFIRM, SCHEDULE, live_authorisation

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'RESEARCH_LLM_MODE': 'live_once', 'RESEARCH_LLM_CONFIRMATION': LIVE_CONFIRM}
CRON = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'schedule',
        'GITHUB_EVENT_SCHEDULE': SCHEDULE}


class LiveGuard(unittest.TestCase):
    def test_schedule_blocked_unless_explicitly_allowed(self):
        with self.assertRaisesRegex(ValueError, 'LIVE_SCHEDULE_BLOCKED_BY_CONFIG'):
            live_authorisation(CRON, [], '2026-11-05', schedule_allowed=False)
        self.assertEqual(live_authorisation(CRON, [], '2026-11-05', schedule_allowed=True), 'schedule')

    def test_only_live_once_dispatch_with_confirmation_on_main_first_attempt(self):
        self.assertEqual(live_authorisation(DISPATCH, [], '2026-11-05', schedule_allowed=False), 'workflow_dispatch')
        for change, code in (({'RESEARCH_LLM_MODE': 'preview'}, 'MODE_NOT_LIVE_ONCE'),
                             ({'RESEARCH_LLM_MODE': ''}, 'MODE_NOT_LIVE_ONCE'),
                             ({'RESEARCH_LLM_CONFIRMATION': 'sim'}, 'CONFIRMATION_MISSING'),
                             ({'GITHUB_RUN_ATTEMPT': '2'}, 'RERUN'),
                             ({'GITHUB_REF': 'refs/heads/feature'}, 'NOT_MAIN'),
                             ({'GITHUB_EVENT_NAME': 'push'}, 'EVENT_NOT_AUTHORISED')):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, code):
                live_authorisation(dict(DISPATCH, **change), [], '2026-11-05', schedule_allowed=False)

    def test_default_and_repository_config_keep_cron_blocked(self):
        self.assertIs(DEFAULT_CONFIG['llm_schedule_live_enabled'], False)
        cfg = load_config(ROOT, env={})
        self.assertIs(cfg['llm_schedule_live_enabled'], False)
        raw = json.loads((ROOT / 'config/research-autonomy.json').read_text(encoding='utf-8'))
        self.assertIs(raw['llm_schedule_live_enabled'], False)

    def test_malformed_value_fails_safe(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / 'config').mkdir()
            (Path(t) / 'config/research-autonomy.json').write_text(json.dumps(
                {'schema_version': 1, 'llm_live_enabled': True, 'llm_schedule_live_enabled': 'true'}))
            self.assertIs(load_config(t, env={})['llm_schedule_live_enabled'], False)

    def test_workflow_passes_dispatch_mode_to_the_live_step(self):
        text = (ROOT / '.github/workflows/v6-llm-autonomous.yml').read_text(encoding='utf-8')
        self.assertIn('RESEARCH_LLM_MODE: ${{ inputs.mode }}', text)


if __name__ == '__main__':
    unittest.main()

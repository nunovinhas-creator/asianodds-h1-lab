"""Guard the automatic post-FT monitor path without requiring provider APIs."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MonitorWiringTests(unittest.TestCase):
    def test_monitor_runs_after_failed_or_successful_reconciliation(self):
        source = (ROOT / '.github/workflows/lab-ft-results.yml').read_text()
        job = source.split('\n  integrity:\n', 1)[1]
        self.assertIn('needs: reconcile', job)
        self.assertIn('if: ${{ always() }}', job)
        self.assertIn('uses: ./.github/workflows/ft-operational-integrity.yml', job)
        self.assertIn('upstream_conclusion: ${{ needs.reconcile.result }}', job)
        self.assertNotIn('continue-on-error', job)
        self.assertNotIn('secrets:', job)
        self.assertIn('contents: read', job)

    def test_reusable_monitor_preserves_failure_and_evidence(self):
        source = (ROOT / '.github/workflows/ft-operational-integrity.yml').read_text()
        self.assertIn('workflow_call:\n    inputs:\n      upstream_conclusion:\n        required: true\n        type: string', source)
        self.assertIn("inputs.upstream_conclusion || github.event.workflow_run.conclusion || 'not_applicable'", source)
        self.assertIn('if: always()', source)
        self.assertIn('persist-credentials: false', source)
        self.assertNotIn('secrets.', source)
        self.assertNotIn('contents: write', source)

    def test_existing_independent_fallbacks_remain(self):
        source = (ROOT / '.github/workflows/ft-operational-integrity.yml').read_text()
        for event in ('workflow_run:', 'workflow_dispatch:', 'schedule:'):
            self.assertIn(event, source)

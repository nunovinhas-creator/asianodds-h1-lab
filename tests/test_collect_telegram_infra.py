"""collect.yml: durable Telegram mode is OFF by default and nothing else about the workflow changed."""
import re
import unittest
from pathlib import Path

TEXT = (Path(__file__).resolve().parents[1] / ".github/workflows/collect.yml").read_text(encoding="utf-8")


class CollectTelegramInfraTests(unittest.TestCase):
    def test_durable_mode_defaults_off_and_is_driven_only_by_a_repository_variable(self):
        self.assertEqual(TEXT.count("TG_DURABLE_INTENT: ${{ vars.TG_DURABLE_INTENT == '1' && '1' || '0' }}"), 2)
        self.assertEqual(TEXT.count("TG_IGNORE_AUTH_BLOCK: ${{ vars.TG_IGNORE_AUTH_BLOCK == '1' && '1' || '0' }}"), 2)
        self.assertNotIn("TG_DURABLE_INTENT: '1'", TEXT)
        self.assertNotIn("TG_DURABLE_INTENT: 1", TEXT)

    def test_only_the_two_active_notifiers_get_the_variables(self):
        for step in re.split(r"\n      - ", TEXT):
            if "TG_DURABLE_INTENT" in step:
                self.assertTrue("three_moves_notify" in step or "two_up_notify" in step, step[:80])

    def test_block_file_is_committed_with_the_other_notification_state(self):
        self.assertIn("git add -A -- data/telegram-delivery-block.json", TEXT)
        self.assertNotIn("telegram-delivery-block", Path(".gitignore").read_text())

    def test_schedule_concurrency_permissions_and_steps_are_unchanged(self):
        self.assertIn("- cron: '2-57/5 * * * *'", TEXT)
        self.assertIn("group: asianodds-h1-write", TEXT)
        self.assertIn("cancel-in-progress: false", TEXT)
        self.assertIn("contents: write", TEXT)
        for needle in ("python -m h1lab.cli collect", "python -m h1lab.three_moves_notify",
                       "python -m h1lab.two_up_notify", "python -m scripts.lab_ft_watchdog",
                       "python -m scripts.h1_results_watchdog"):
            self.assertEqual(TEXT.count(needle), 1, needle)
        self.assertNotIn("h1lab.e4_notify", TEXT)
        self.assertNotIn("h1lab.strategy_notify", TEXT)
        self.assertNotIn("h1lab.t05_notify", TEXT)

    def test_yaml_parses(self):
        import yaml
        data = yaml.safe_load(TEXT)
        self.assertIn("collect", data["jobs"])


if __name__ == "__main__":
    unittest.main()

"""collect.yml: E5 is the only Telegram emitter, runs after data publication and is always durable."""
import re
import unittest
from pathlib import Path

TEXT = (Path(__file__).resolve().parents[1] / ".github/workflows/collect.yml").read_text(encoding="utf-8")


class CollectTelegramInfraTests(unittest.TestCase):
    def test_e5_durability_is_mandatory_not_an_opt_in_variable(self):
        # E5 publishes every intent on main BEFORE its Telegram request (at-most-once). The old
        # TG_DURABLE_INTENT opt-in (default off, at-least-once) no longer drives any sender.
        self.assertNotIn("TG_DURABLE_INTENT", TEXT)
        self.assertNotIn("TG_IGNORE_AUTH_BLOCK", TEXT)
        self.assertEqual(TEXT.count("TG_BOT_TOKEN: ${{ secrets.TG_BOT_TOKEN }}"), 1)

    def test_only_the_e5_notifier_gets_the_bot_secrets(self):
        for step in re.split(r"\n      - ", TEXT):
            if "TG_BOT_TOKEN" in step or "TG_CHAT_ID" in step:
                self.assertIn("python -m h1lab.e5_notify", step, step[:80])

    def test_collected_data_is_published_before_any_telegram_request(self):
        self.assertLess(TEXT.index("python -m scripts.collect_publish_safe publish"),
                        TEXT.index("python -m h1lab.e5_notify"))

    def test_block_file_is_committed_with_the_other_notification_state(self):
        # Staged (including deletion of an expired block) by the ownership-matrix stage step.
        from scripts import publication_ownership as own
        self.assertIn("python -m scripts.collect_publish_safe stage", TEXT)
        self.assertTrue(own.is_collector_owned("data/telegram-delivery-block.json"))
        self.assertNotIn("telegram-delivery-block", Path(".gitignore").read_text())

    def test_schedule_concurrency_permissions_and_steps_are_unchanged(self):
        self.assertIn("- cron: '2-57/5 * * * *'", TEXT)
        self.assertIn("group: asianodds-h1-write", TEXT)
        self.assertIn("cancel-in-progress: false", TEXT)
        self.assertIn("contents: write", TEXT)
        for needle in ("python -m h1lab.cli collect", "python -m h1lab.e5_notify",
                       "python -m scripts.lab_ft_watchdog",
                       "python -m scripts.h1_results_watchdog",
                       "python -m scripts.collect_publish_safe stage",
                       "python -m scripts.collect_publish_safe publish"):
            self.assertEqual(TEXT.count(needle), 1, needle)
        self.assertNotIn("h1lab.e4_notify", TEXT)
        self.assertNotIn("h1lab.three_moves_notify", TEXT)
        self.assertNotIn("h1lab.two_up_notify", TEXT)
        self.assertNotIn("h1lab.strategy_notify", TEXT)
        self.assertNotIn("h1lab.t05_notify", TEXT)
        # No rebase/force push after Telegram was sent; no blanket staging of data/lab.
        self.assertNotIn("git pull --rebase origin main\n            git push", TEXT)
        self.assertNotIn("git push origin main", TEXT)
        self.assertNotIn("git add data/lab", TEXT)
        self.assertNotIn("--force", TEXT)

    def test_yaml_parses(self):
        import yaml
        data = yaml.safe_load(TEXT)
        self.assertIn("collect", data["jobs"])


if __name__ == "__main__":
    unittest.main()

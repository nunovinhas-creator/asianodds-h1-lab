"""FT x Telegram: concurrent data/telegram-delivery-block.json, offline bare-Git reproduction."""
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts import lab_ft_publish_safe as p
import tests.test_lab_ft_publish_safe as _base
from tests.test_lab_ft_publish_safe import git

BLOCK = "data/telegram-delivery-block.json"
NOW = datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)


def block(until="2026-11-02T00:00:00+00:00", status=429,
          set_at="2026-11-01T23:00:00+00:00", diagnosis="FLOOD_WAIT_RETRY_AFTER", **extra):
    data = {"schema_version": 1, "until": until, "http_status": status,
            "set_at": set_at, "diagnosis": diagnosis}
    data.update(extra)
    return json.dumps(data, sort_keys=True)


class TelegramBlockConcurrencyTests(_base.GitFTPublicationTests):
    """Reuses the bare-repo FT fixture (sealed bundle, collector clone)."""

    def publish(self):
        with patch.object(p, "_utcnow", return_value=NOW):
            return super().publish()

    def remote_blob(self, path=BLOCK):
        git(self.root, "fetch", "-q", "origin", "main")
        return git(self.root, "show", "origin/main:" + path)

    # --- positive -------------------------------------------------------
    def test_new_valid_block_is_preserved_byte_for_byte_and_ft_is_untouched(self):
        raw = block() + "\n"
        self.collector_commit({BLOCK: raw})
        self.publish()
        self.assertEqual(git(self.root, "show", "HEAD:" + BLOCK), raw.strip())
        self.assertEqual(json.loads(git(self.root, "show", "HEAD:docs/lab/ft-results.json"))["final"], 2)
        self.assertEqual(git(self.root, "show", "HEAD:data/lab/ft-ledger.json"),
                         git(self.root, "show", self.source + ":data/lab/ft-ledger.json"))

    def test_extension_of_an_existing_block_is_allowed(self):
        self.collector_commit({BLOCK: block() + "\n"})
        base = git(self.other, "rev-parse", "HEAD")
        # the FT run started from a checkout that already had the block
        self.base_with_block(base)
        self.collector_commit({BLOCK: block(until="2026-11-02T06:00:00+00:00",
                                            set_at="2026-11-01T23:20:00+00:00") + "\n"})
        self.publish()
        self.assertIn("2026-11-02T06:00:00", git(self.root, "show", "HEAD:" + BLOCK))

    def test_expired_block_may_be_removed(self):
        self.collector_commit({BLOCK: block(until="2026-11-01T23:10:00+00:00") + "\n"})
        self.base_with_block(git(self.other, "rev-parse", "HEAD"))
        git(self.other, "rm", "-q", BLOCK)
        git(self.other, "commit", "-qm", "drop expired pause")
        git(self.other, "push", "-q", "origin", "main")
        self.publish()
        git(self.root, "fetch", "-q", "origin", "main")
        self.assertNotEqual(0, __import__("subprocess").run(
            ["git", "-C", str(self.root), "cat-file", "-e", "HEAD:" + BLOCK]).returncode)

    # --- negative -------------------------------------------------------
    def assertRefused(self, raw, msg="Telegram delivery block invalid"):
        self.collector_commit({BLOCK: raw})
        before = git(self.other, "rev-parse", "HEAD")
        with self.assertRaisesRegex(p.UnsafeFTPublication, msg):
            self.publish()
        self.assertEqual(self.remote_blob("docs/lab/ft-results.json"), '{"final":1}')
        self.assertEqual(git(self.root, "rev-parse", "origin/main"), before)

    def test_malformed_json_refused(self):
        self.assertRefused("{not json\n")

    def test_unknown_field_refused(self):
        self.assertRefused(block(token="123:ABC") + "\n")

    def test_secret_like_diagnosis_refused(self):
        self.assertRefused(block(diagnosis="bot123456:ABCDEF leaked") + "\n")

    def test_bad_status_refused(self):
        self.assertRefused(block(status=500) + "\n")
        
    def test_boolean_status_and_version_refused(self):
        self.assertRefused(block(status=True) + "\n")

    def test_nonfinite_duplicate_and_naive_time_refused(self):
        self.assertRefused('{"schema_version":1,"schema_version":1}\n')
        self.assertRefused(block(until="2026-11-02T00:00:00") + "\n")
        self.assertRefused(block(until="9999-12-31T00:00:00+00:00") + "\n")

    def test_set_at_after_until_refused(self):
        self.assertRefused(block(set_at="2026-11-02T01:00:00+00:00") + "\n")

    def test_oversized_file_refused(self):
        self.assertRefused(block(diagnosis="X" * 10000) + "\n")

    def test_active_block_cannot_be_deleted_or_shortened_or_rolled_back(self):
        self.collector_commit({BLOCK: block() + "\n"})
        self.base_with_block(git(self.other, "rev-parse", "HEAD"))
        git(self.other, "rm", "-q", BLOCK)
        git(self.other, "commit", "-qm", "delete active pause")
        git(self.other, "push", "-q", "origin", "main")
        with self.assertRaisesRegex(p.UnsafeFTPublication, "active Telegram delivery block removed"):
            self.publish()

    def test_shortened_block_refused(self):
        self.collector_commit({BLOCK: block() + "\n"})
        self.base_with_block(git(self.other, "rev-parse", "HEAD"))
        self.collector_commit({BLOCK: block(until="2026-11-01T23:45:00+00:00") + "\n"})
        with self.assertRaisesRegex(p.UnsafeFTPublication, "Telegram delivery block invalid"):
            self.publish()

    def test_other_telegram_paths_still_unknown(self):
        self.collector_commit({"data/telegram-delivery-block.json.bak": block() + "\n"})
        with self.assertRaisesRegex(p.UnsafeFTPublication, "Unknown concurrent path"):
            self.publish()

    def test_symlink_refused(self):
        import os
        os.symlink("/etc/passwd", self.other / BLOCK)
        git(self.other, "add", ".")
        git(self.other, "commit", "-qm", "symlink")
        git(self.other, "push", "-q", "origin", "main")
        with self.assertRaisesRegex(p.UnsafeFTPublication, "Unsafe FT tree entry|Telegram delivery block invalid"):
            self.publish()

    def base_with_block(self, base):
        """Re-pin the FT checkout so the block already exists in its input base."""
        git(self.root, "fetch", "-q", "origin", "main")
        git(self.root, "reset", "-q", "--hard", self.source)
        git(self.root, "rebase", "-q", "--onto", base, self.base)
        self.base = base
        self.source = git(self.root, "rev-parse", "HEAD")


if __name__ == "__main__":
    unittest.main()

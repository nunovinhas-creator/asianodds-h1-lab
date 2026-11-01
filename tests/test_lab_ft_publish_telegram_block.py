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

    # --- temporal policy (NOW = 2026-11-01T23:30Z, skew 60 s, horizon 24 h + 1 s + skew) ----
    def test_set_at_now_and_small_clock_skew_accepted(self):
        for set_at, until in (("2026-11-01T23:30:00+00:00", "2026-11-01T23:35:00+00:00"),
                              ("2026-11-01T23:30:45+00:00", "2026-11-01T23:36:00+00:00")):
            with self.subTest(set_at=set_at):
                self.setUp()
                self.collector_commit({BLOCK: block(until=until, set_at=set_at) + "\n"})
                self.publish()

    def test_full_24h_retry_after_accepted(self):
        self.collector_commit({BLOCK: block(until="2026-11-02T23:30:01+00:00",
                                            set_at="2026-11-01T23:30:00+00:00") + "\n"})
        self.publish()

    def test_future_set_at_beyond_skew_refused(self):
        for set_at, until in (("2026-11-01T23:32:00+00:00", "2026-11-01T23:40:00+00:00"),
                              ("2026-11-02T04:00:00+00:00", "2026-11-02T05:00:00+00:00"),
                              ("2030-01-01T00:00:00+00:00", "2030-01-01T01:00:00+00:00")):
            with self.subTest(set_at=set_at):
                self.setUp()
                self.assertRefused(block(until=until, set_at=set_at) + "\n")

    def test_far_until_and_out_of_range_dates_refused(self):
        for until in ("2026-11-04T00:00:00+00:00", "2099-01-01T00:00:00+00:00",
                      "9999-12-31T23:59:59+00:00", "9999-12-31T23:59:59Z"):
            with self.subTest(until=until):
                self.setUp()
                self.assertRefused(block(until=until, set_at="2026-11-01T23:30:00+00:00") + "\n")
        for bad in ("0000-01-01T00:00:00+00:00", "2026-13-40T00:00:00+00:00",
                    "2026-11-01T23:30:00+01:00", "20261101T233000+00:00"):
            with self.subTest(bad=bad):
                self.setUp()
                self.assertRefused(block(until=bad, set_at="2026-11-01T23:00:00+00:00") + "\n")

    def test_legitimate_transition_between_blocks_accepted(self):
        self.collector_commit({BLOCK: block() + "\n"})
        self.base_with_block(git(self.other, "rev-parse", "HEAD"))
        self.collector_commit({BLOCK: block(status=401, diagnosis=sorted(p._BLOCK_DIAGNOSES[401])[0],
                                            until="2026-11-02T23:00:00+00:00",
                                            set_at="2026-11-01T23:25:00+00:00") + "\n"})
        self.publish()
        self.assertIn('"http_status": 401', git(self.root, "show", "HEAD:" + BLOCK))

    def test_clock_unavailable_fails_closed(self):
        raw = block().encode()
        with patch.object(p, "_utcnow", side_effect=OSError("no clock")):
            self.assertFalse(p.valid_telegram_block_update(None, raw))
        naive = datetime(2026, 11, 1, 23, 30)
        self.assertFalse(p.valid_telegram_block_update(None, raw, now=naive))
        self.assertTrue(p.valid_telegram_block_update(None, raw, now=NOW))

    # --- blobs ------------------------------------------------------------
    def test_truncated_and_duplicate_and_nan_refused(self):
        self.assertRefused(block()[:40])
        self.assertRefused(block().replace('"until"', '"until": "2026-11-02T00:00:00+00:00", "until"', 1) + "\n")
        self.assertRefused(block().replace('"http_status": 429', '"http_status": NaN') + "\n")
        self.assertRefused(block().replace('"http_status": 429', '"http_status": Infinity') + "\n")
        self.assertRefused(block().replace('"http_status": 429', '"http_status": 429.0') + "\n")

    def test_unknown_status_and_diagnosis_pairing_refused(self):
        self.assertRefused(block(status=429, diagnosis=sorted(p._BLOCK_DIAGNOSES[401])[0]) + "\n")
        self.assertRefused(block(status=401, diagnosis="FLOOD_WAIT_RETRY_AFTER") + "\n")
        self.assertRefused(block(status=418) + "\n")

    def test_executable_mode_and_gitlink_refused(self):
        import os
        (self.other / BLOCK).parent.mkdir(parents=True, exist_ok=True)
        (self.other / BLOCK).write_text(block() + "\n")
        os.chmod(self.other / BLOCK, 0o755)
        git(self.other, "add", ".")
        git(self.other, "commit", "-qm", "exec bit")
        git(self.other, "push", "-q", "origin", "main")
        with self.assertRaisesRegex(p.UnsafeFTPublication, "Unsafe FT tree entry"):
            self.publish()

    def test_symlink_previous_blob_refused(self):
        import os
        os.symlink(block(), self.other / BLOCK)  # base: symlink whose target text is valid JSON
        git(self.other, "add", ".")
        git(self.other, "commit", "-qm", "symlink base")
        git(self.other, "push", "-q", "origin", "main")
        self.base_with_block(git(self.other, "rev-parse", "HEAD"))
        git(self.other, "rm", "-q", BLOCK)
        (self.other / BLOCK).write_text(block(until="2026-11-02T06:00:00+00:00") + "\n")
        git(self.other, "add", ".")
        git(self.other, "commit", "-qm", "replace symlink with file")
        git(self.other, "push", "-q", "origin", "main")
        with self.assertRaisesRegex(p.UnsafeFTPublication, "Unsafe FT tree entry"):
            self.publish()

    def test_corrupt_previous_blob_never_repaired(self):
        self.collector_commit({BLOCK: "{broken\n"})
        self.base_with_block(git(self.other, "rev-parse", "HEAD"))
        self.collector_commit({BLOCK: block() + "\n"})
        with self.assertRaisesRegex(p.UnsafeFTPublication, "Telegram delivery block invalid"):
            self.publish()

    def test_unit_rules(self):
        enc = lambda **k: block(**k).encode()
        v = lambda a, b: p.valid_telegram_block_update(a, b, now=NOW)
        active = enc()
        self.assertFalse(v(active, None))                       # active removal
        self.assertTrue(v(enc(until="2026-11-01T23:10:00+00:00"), None))  # expired removal
        self.assertFalse(v(active, enc(until="2026-11-01T23:45:00+00:00")))  # shorten
        self.assertFalse(v(active, enc(set_at="2026-11-01T22:00:00+00:00")))  # rewind
        self.assertFalse(v(active, enc(diagnosis="FLOOD_WAIT_CONSERVATIVE_5MIN")))  # equal until rewrite
        self.assertTrue(v(active, enc(until="2026-11-02T01:00:00+00:00",
                                      set_at="2026-11-01T23:25:00+00:00")))

    def base_with_block(self, base):
        """Re-pin the FT checkout so the block already exists in its input base."""
        git(self.root, "fetch", "-q", "origin", "main")
        git(self.root, "reset", "-q", "--hard", self.source)
        git(self.root, "rebase", "-q", "--onto", base, self.base)
        self.base = base
        self.source = git(self.root, "rev-parse", "HEAD")


if __name__ == "__main__":
    unittest.main()

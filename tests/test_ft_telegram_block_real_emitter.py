"""Integration #197+#199+#200+#201: the file really written by bot._record_block/BlockStore
is accepted by the FT publisher validator (real timestamps, real diagnoses, real clock)."""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from h1lab import bot
from h1lab.telegram_block import BlockStore
from scripts import lab_ft_publish_safe as p
import tests.test_lab_ft_publish_safe as _base
from tests.test_lab_ft_publish_safe import git

BLOCK = "data/telegram-delivery-block.json"


class RealEmitterTests(_base.GitFTPublicationTests):
    def emit(self, status, retry_after):
        store = BlockStore(self.other / BLOCK)
        bot._record_block(store, status, retry_after)
        return (self.other / BLOCK).read_bytes()

    def commit_emitted(self, raw):
        git(self.other, "add", "-A")
        git(self.other, "commit", "-qm", "collector pause")
        git(self.other, "push", "-q", "origin", "main")

    def test_real_emitter_files_are_accepted(self):
        for status, retry in ((429, 30), (429, 3600), (429, 86400), (429, None), (401, None), (403, None)):
            with self.subTest(status=status, retry_after=retry):
                self.setUp()
                raw = self.emit(status, retry)
                self.assertTrue(p.valid_telegram_block_update(None, raw), raw)
                self.commit_emitted(raw)
                self.publish()
                self.assertEqual(git(self.root, "show", "HEAD:" + BLOCK), raw.decode())
                self.assertEqual(json.loads(git(self.root, "show", "HEAD:docs/lab/ft-results.json"))["final"], 2)

    def test_real_emitter_extension_and_transition(self):
        self.commit_emitted(self.emit(429, 600))
        base = git(self.other, "rev-parse", "HEAD")
        git(self.root, "fetch", "-q", "origin", "main")
        git(self.root, "reset", "-q", "--hard", self.source)
        git(self.root, "rebase", "-q", "--onto", base, self.base)
        self.base, self.source = base, git(self.root, "rev-parse", "HEAD")
        self.commit_emitted(self.emit(401, None))  # longer pause replaces it
        self.publish()
        self.assertIn('"http_status": 401', git(self.root, "show", "HEAD:" + BLOCK))

    def test_invalid_state_is_never_published(self):
        raw = self.emit(429, 30).decode().replace("FLOOD_WAIT_RETRY_AFTER", "token 123:ABC")
        (self.other / BLOCK).write_text(raw)
        self.commit_emitted(raw.encode())
        before = git(self.other, "rev-parse", "HEAD")
        with self.assertRaises(p.UnsafeFTPublication):
            self.publish()
        self.assertEqual(git(self.root, "rev-parse", "origin/main"), before)
        self.assertEqual(git(self.root, "show", "origin/main:docs/lab/ft-results.json"), '{"final":1}')


if __name__ == "__main__":
    unittest.main()

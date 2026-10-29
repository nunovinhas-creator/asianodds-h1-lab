import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import publication_guard as g


class GuardTests(unittest.TestCase):
    def test_every_failed_skipped_or_missing_producer_blocks_bundle(self):
        for pipeline, names in g.PRODUCERS.items():
            good = {name: {'outcome': 'success', 'conclusion': 'success'} for name in names}
            g.outcomes(pipeline, good)
            for name in names:
                for status in ('failure', 'skipped', 'cancelled', None):
                    with self.subTest(pipeline=pipeline, name=name, status=status):
                        bad = {**good, name: {'outcome': status, 'conclusion': 'success'}}
                        with self.assertRaises(ValueError):
                            g.outcomes(pipeline, bad)
                with self.assertRaises(ValueError):
                    g.outcomes(pipeline, {key: val for key, val in good.items() if key != name})

    def test_truncated_and_nonfinite_documents_rejected(self):
        for name, content in [('x.json', b'{"count":'), ('x.json', b'{"count":NaN}'),
                              ('x.json', b'null'), ('x.jsonl', b'{}\n{'),
                              ('x.jsonl', b'{}'), ('x.jsonl', b'{}\n\n')]:
            with self.subTest(name=name, content=content), self.assertRaises(ValueError):
                g.validate(name, content)
        g.validate('x.jsonl', b'{}\n{}\n')
        g.validate('x.json', b'{"count":0}')

    def test_git_transaction_rejects_partial_write_and_changed_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            self.addCleanup(os.chdir, previous)
            subprocess.run(['git', 'init', '-q'], check=True)
            subprocess.run(['git', 'config', 'user.name', 'test'], check=True)
            subprocess.run(['git', 'config', 'user.email', 'test@example.invalid'], check=True)
            target = Path('docs/lab/report.json')
            target.parent.mkdir(parents=True)
            target.write_text('{"count":1}')
            subprocess.run(['git', 'add', '.'], check=True)
            manifest = Path(tmp) / 'seal.json'
            with patch.dict(g.REQUIRED, {'ft': (str(target),)}):
                g.seal('ft', manifest)
                subprocess.run(['git', 'commit', '-qm', 'complete bundle'], check=True)
                g.verify(manifest)
                # Concurrent unrelated file does not invalidate the sealed bundle.
                Path('unrelated.txt').write_text('collector')
                subprocess.run(['git', 'add', 'unrelated.txt'], check=True)
                subprocess.run(['git', 'commit', '-qm', 'unrelated'], check=True)
                g.verify(manifest)
                # Simulate a successful rebase which changed one owned output.
                target.write_text('{"count":2}')
                subprocess.run(['git', 'add', str(target)], check=True)
                subprocess.run(['git', 'commit', '-qm', 'concurrent output'], check=True)
                with self.assertRaises(ValueError):
                    g.verify(manifest)
                target.write_text('{"count":')
                subprocess.run(['git', 'add', str(target)], check=True)
                with self.assertRaises(ValueError):
                    g.seal('ft', manifest)
                subprocess.run(['git', 'rm', '-f', str(target)], check=True, stdout=subprocess.DEVNULL)
                with self.assertRaises(subprocess.CalledProcessError):
                    g.seal('ft', manifest)
            os.chdir(previous)

    def test_workflows_guard_before_commit_and_after_each_rebase(self):
        root = Path(__file__).resolve().parents[1]
        for filename, pipeline in [('lab-v4-audit.yml','audit'), ('lab-ft-results.yml','ft')]:
            source = (root / '.github/workflows' / filename).read_text()
            tail = source[source.index('      - name: Commit only'):]
            self.assertLess(tail.index('publication_guard outcomes'), tail.index('git add'))
            self.assertLess(tail.index('publication_guard seal'), tail.index('git commit'))
            self.assertLess(tail.index('git rebase'), tail.index('publication_guard verify'))
            self.assertLess(tail.index('publication_guard verify'), tail.index('git push'))
            for name in g.PRODUCERS[pipeline]:
                self.assertIn('id: ' + name + '\n', source)


if __name__ == '__main__':
    unittest.main()

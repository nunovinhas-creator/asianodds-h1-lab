"""The explicit ownership matrix matches the repository and every workflow that writes main."""
import fnmatch
import re
import subprocess
import unittest
from pathlib import Path

from scripts import publication_ownership as own

ROOT = Path(__file__).resolve().parents[1]


def tracked():
    return subprocess.check_output(["git", "-C", str(ROOT), "ls-files"]).decode().split()


def staged_patterns(workflow):
    """Path arguments of every `git add` in a workflow (globs kept, variables skipped)."""
    text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
    out = []
    for line in re.findall(r"git add ([^;\n|&]+)", text):
        for word in line.split():
            if word.startswith("-") or "$" in word or word in ("2>/dev/null",):
                continue
            out.append(word)
    return out


def expand(pattern):
    names = [n for n in tracked() if fnmatch.fnmatch(n, pattern)]
    return names or [pattern.replace("*", "2026-11")]


class OwnershipMatrixTests(unittest.TestCase):
    def test_every_tracked_file_has_exactly_one_known_owner(self):
        missing = [n for n in tracked() if own.owner_of(n) is None]
        self.assertEqual(missing, [])

    def test_collector_owned_set_is_explicit(self):
        for path in ("data/state.json", "docs/data.json", "data/e5-over25-notifications.json",
                     "data/telegram-delivery-block.json",
                     "data/lab/markets-2026-11.jsonl", "data/lab/markets-2026-11-part0001.jsonl",
                     "data/lab/formats-2026-11.jsonl", "data/lab/v4-revisions-2026-11.jsonl"):
            self.assertEqual(own.owner_of(path), own.COLLECTOR, path)
        # data/lab is shared: these are NOT the collector's even though they live there.
        for path, owner in (("data/lab/v4-runchecks.jsonl", own.LAB_V4),
                            ("data/lab/v6-forecasts-2026-11.jsonl", own.LAB_V4),
                            ("data/lab/v6-archive-index.json", own.LAB_V4),
                            ("data/lab/ft-ledger.json", own.FT),
                            ("data/lab/v6-ft-events-2026-11.jsonl", own.FT),
                            ("data/lab/discovery-state.json", own.FT),
                            ("data/pattern-notifications.json", own.LEGACY),
                            # retired 2026-11-02 (E5 is the only emitter): frozen historical proof
                            ("data/three-total-moves-notifications.json", own.LEGACY),
                            ("data/two-up-total-notifications.json", own.LEGACY),
                            ("data/lab/golden/reviews/x.json", own.MANUAL_REVIEW)):
            self.assertEqual(own.owner_of(path), owner, path)

    def test_workflow_staging_matches_the_matrix(self):
        expected = {
            "results.yml": {own.H1_RESULTS, own.COLLECTOR},     # docs/data.json is re-rendered by H1
            "lab-ft-results.yml": {own.FT},
            "lab-v4-audit.yml": {own.LAB_V4},
            "lab-quality.yml": {own.LAB_QUALITY},
            "v6-llm-autonomous.yml": {own.LLM},
            "v6-llm-investigator.yml": {own.LLM},
            "v6-offline-statistics.yml": {own.OFFLINE_STATS},
        }
        for workflow, owners in expected.items():
            for pattern in staged_patterns(workflow):
                for name in expand(pattern):
                    with self.subTest(workflow=workflow, path=name):
                        self.assertIn(own.owner_of(name), owners)

    def test_collector_no_longer_stages_whole_directories(self):
        self.assertEqual(staged_patterns("collect.yml"), [])
        text = (ROOT / ".github/workflows/collect.yml").read_text()
        self.assertIn("python -m scripts.collect_publish_safe stage", text)


if __name__ == "__main__":
    unittest.main()

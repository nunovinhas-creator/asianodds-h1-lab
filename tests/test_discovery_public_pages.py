import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import publication_guard as guard
from scripts.lab_discoveries import main as generate_discovery
from h1lab.discovery_timeline import build as build_discovery

from h1lab.discovery_public_pages import paginate, verify, encode, PAGE_LIMIT


def sample(n=20, points=12, size=400):
    return {
        "schema_version": 1, "status": "DISCOVERY_OBSERVATION_NOT_BETTING",
        "baseline_at": "2026-10-30T21:00:00Z",
        "timeline": [{"kind": "NEW_EVIDENCE", "id": "one", "target": "OVER_2_5"}],
        "prospective": {"settled_total": 0},
        "patterns": {f"pattern-{i:05d}|OVER_2_5": {
            "latest": {"label": f"pattern-{i:05d}", "known": i},
            "points": [{"at_utc": f"2026-10-30T{j%24:02d}:00:00Z",
                        "payload": str(i) + "x" * size} for j in range(points)]
        } for i in range(n)}
    }


def reconstruct(root, pages):
    patterns = {}
    for meta in root["pattern_pages"]:
        rows = json.loads(pages[meta["path"]])["patterns"]
        if patterns.keys() & rows.keys():
            raise AssertionError("duplicate pattern")
        patterns.update(rows)
    result = dict(root)
    result.pop("pattern_count")
    result.pop("pattern_pages")
    result.pop("public_cache")
    result["patterns"] = patterns
    return result


class DiscoveryPublicPagesTests(unittest.TestCase):
    def test_repeated_growth_beyond_original_limit_preserves_every_pattern_and_point(self):
        source = sample(1120, points=24, size=250)
        before = copy.deepcopy(source)
        self.assertGreater(len(encode(source)), 1_400_000)
        root, pages = paginate(source)
        self.assertEqual(before, source)
        self.assertLessEqual(len(encode(root)), 1_400_000)
        self.assertTrue(pages)
        self.assertTrue(all(len(raw) <= PAGE_LIMIT for raw in pages.values()))
        self.assertEqual(verify(root, pages), 1120)
        self.assertEqual(reconstruct(root, pages)["patterns"], source["patterns"])
        self.assertEqual(reconstruct(root, pages)["timeline"], source["timeline"])
        self.assertEqual(reconstruct(root, pages)["prospective"], source["prospective"])

    def test_actual_committed_public_snapshot_roundtrips_losslessly(self):
        original = json.loads((Path(__file__).resolve().parents[1] /
                               "docs/lab/discoveries.json").read_text(encoding="utf-8"))
        # When this test is later rebased on a paged snapshot, the synthetic
        # growth regression remains the source of truth for full reconstruction.
        if "pattern_pages" in original:
            self.skipTest("Committed root is already paginated")
        root, pages = paginate(original)
        self.assertEqual(verify(root, pages), len(original["patterns"]))
        rebuilt = reconstruct(root, pages)
        for field in ("schema_version", "status", "timeline", "prospective",
                      "baseline_at", "patterns"):
            self.assertEqual(rebuilt[field], original[field])

    def test_complete_offline_producer_replay_with_real_inputs(self):
        source = Path(__file__).resolve().parents[1]
        input_files = ("docs/lab/pattern-research.json",
                       "data/lab/pattern-watch-first-seen.json",
                       "data/lab/ft-ledger.json",
                       "data/lab/discovery-state.json")
        with tempfile.TemporaryDirectory() as td:
            root_dir = Path(td)
            for relative in input_files:
                destination = root_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative, destination)
            generated = generate_discovery(["--root", td])
            published = json.loads((root_dir / "docs/lab/discoveries.json").read_text())
            stored = json.loads((root_dir / "data/lab/discovery-state.json").read_text())
            page_files = {p["path"]: (root_dir / "docs/lab" / p["path"]).read_bytes()
                          for p in published["pattern_pages"]}
            self.assertEqual(verify(published, page_files), len(stored["patterns"]))
            self.assertEqual(generated, published)
            report, first, ledger, prior = [
                json.loads((source / item).read_text(encoding="utf-8"))
                for item in input_files
            ]
            _, full, _ = build_discovery(report, first, ledger, prior)
            self.assertEqual(reconstruct(published, page_files)["patterns"],
                             full["patterns"])
            self.assertEqual(reconstruct(published, page_files)["timeline"],
                             full["timeline"])

    def test_deterministic_and_reusable_content_addressed_pages(self):
        source = sample(40)
        a, pages_a = paginate(source)
        b, pages_b = paginate(copy.deepcopy(source))
        self.assertEqual(a, b)
        self.assertEqual(pages_a, pages_b)
        for descriptor in a["pattern_pages"]:
            self.assertEqual(descriptor["sha256"],
                             hashlib.sha256(pages_a[descriptor["path"]]).hexdigest())

    def test_missing_corrupt_or_duplicate_pages_fail_closed(self):
        root, pages = paginate(sample(60))
        first = root["pattern_pages"][0]["path"]
        for candidate in ({}, {**pages, first: b'{"patterns":{}}'}):
            with self.assertRaises(ValueError):
                verify(root, candidate)
        corrupt = copy.deepcopy(root)
        corrupt["pattern_pages"].append(copy.deepcopy(corrupt["pattern_pages"][0]))
        with self.assertRaises(ValueError):
            verify(corrupt, pages)
        traversal = copy.deepcopy(root)
        traversal["pattern_pages"][0]["path"] = "../secrets.json"
        with self.assertRaises(ValueError):
            verify(traversal, pages)

    def test_git_seal_includes_pages_and_rejects_rebase_mutation(self):
        root, pages = paginate(sample(30, points=24, size=300))
        documents = {"docs/lab/discoveries.json": encode(root)}
        documents.update({"docs/lab/" + k: v for k, v in pages.items()})
        def staged_git(*args):
            if args[0] == "diff":
                return b"docs/lab/discoveries.json\0"
            if args[0] in ("ls-files", "ls-tree"):
                # No segmented store is staged/committed in this public-page fixture.
                return b""
            if args[0] == "show":
                return documents[args[1].split(":", 1)[1]]
            raise AssertionError(args)
        with tempfile.TemporaryDirectory() as d:
            manifest = Path(d) / "seal.json"
            with (patch.dict(guard.REQUIRED, {"ft": ("docs/lab/discoveries.json",)}),
                  patch.object(guard, "inventory", return_value=[]),
                  patch.object(guard, "git", side_effect=staged_git)):
                guard.seal("ft", manifest)
                saved = json.loads(manifest.read_text())["sha256"]
                self.assertIn("docs/lab/discoveries.json", saved)
                self.assertEqual(set(saved), set(documents))
                guard.verify(manifest)
                first = next(iter(pages))
                documents["docs/lab/" + first] += b" "
                with self.assertRaises(ValueError):
                    guard.verify(manifest)
                with self.assertRaises(ValueError):
                    guard.seal("ft", manifest)

    def test_single_oversized_pattern_fails_closed(self):
        with self.assertRaises(ValueError):
            paginate(sample(1, points=1, size=300000))
    
    def test_unshrinkable_root_metadata_fails_closed(self):
        source = sample(1)
        source["mandatory_description"] = "x" * 1_500_000
        with self.assertRaises(ValueError):
            paginate(source)

    def test_nonfinite_and_malformed_pattern_fail_closed(self):
        source = sample(1)
        key = next(iter(source["patterns"]))
        source["patterns"][key]["latest"]["known"] = float("nan")
        with self.assertRaises(ValueError):
            paginate(source)
        source = sample(1)
        source["patterns"][key] = []
        with self.assertRaises(ValueError):
            paginate(source)


if __name__ == "__main__":
    unittest.main()

"""FT/H1 transport over collector V4 files once they are partitioned (``-partNNNN``).

Contracts (``scripts.publication_ownership``):
* ``v4-revisions-YYYY-MM[-partNNNN].jsonl`` is an append-only SHA journal: each file may only
  grow; a new part may appear; a part is never rewritten or deleted.
* ``markets-``/``formats-YYYY-MM[-partNNNN].jsonl`` are mutable latest views, repartitioned
  by ``h1lab.lab_archive.write_monthly_view``. Byte growth proves nothing about a view (a new
  part is "append-only" from empty), so ANY change is accepted only when the collector's own
  replay (``collect_publish_safe.verify_v4``) proves it: valid journal chain, exact projection,
  no lost event, only audited revisions change a row. Journal changes need that replay too.

Every scenario is offline: a local bare repository plays GitHub and the production V4 stores
(``h1lab.market_v4`` / ``h1lab.shadow_formats``) write the data.
"""
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from h1lab.lab_ft_final_guard import final_snapshot
from scripts import h1_publish_safe as h1
from scripts import lab_ft_publish_safe as p
from tests.git_writers import BareGitFixture, git, observe, write

MARKETS = "data/lab/markets-2026-11.jsonl"
MARKETS_P1 = "data/lab/markets-2026-11-part0001.jsonl"
FORMATS = "data/lab/formats-2026-11.jsonl"
FORMATS_P1 = "data/lab/formats-2026-11-part0001.jsonl"
COLLECTOR_MESSAGE = "data: collect and notify H1 [skip ci]"
# Test-only size bound: one revision (1478 B) per journal file, two market rows (977 B) and
# three format rows (618 B) per view file, so the PRODUCTION writers (append_monthly and
# write_monthly_view) create, grow and repartition ``-partNNNN`` files themselves.
SMALL_BOUND = 2100


def journal_files(root):
    return sorted(p.name for p in (Path(root) / "data/lab").glob("v4-revisions-*.jsonl"))


def journal(root):
    """The closed base file of the V4 revision journal (month = processing clock)."""
    return "data/lab/" + [n for n in journal_files(root) if "-part" not in n][-1]


def part_of(name, n=1):
    return name[:-len(".jsonl")] + "-part%04d.jsonl" % n


def bounded():
    from h1lab import lab_archive
    return patch.object(lab_archive, "MAX_BYTES", SMALL_BOUND)


def grow(root, *events):
    """Collector cycles observed with the production stores under the small bound."""
    with bounded():
        for n in events:
            observe(root, n, observed="2026-11-02T%02d:00:00+00:00" % (5 + n))


def revise(root, n, under):
    """A genuine, journalled V4 revision (content change) of an already observed event."""
    with bounded():
        observe(root, n, observed="2026-11-02T%02d:00:00+00:00" % (5 + n), under=under)


def edit_market_row(root, event_id, under):
    """Unjournalled in-place edit of a published observation, wherever its part is."""
    for path in sorted((Path(root) / "data/lab").glob("markets-*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if any(r["event_id"] == event_id for r in rows):
            for row in rows:
                if row["event_id"] == event_id:
                    row["markets"]["total"]["after"]["under_price"] = under
            path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                                    for r in rows))
            return path
    raise AssertionError("event not found " + event_id)


class Writers(unittest.TestCase):
    def setUp(self):
        self.fx = BareGitFixture(v4_events=(1,))
        self.addCleanup(self.fx.cleanup)
        self.root = self.fx.clone("ft")

    def collector(self, action, name="collector"):
        root = self.fx.clone(name)
        git(root, "fetch", "-q", "origin", "main")
        git(root, "reset", "-q", "--hard", "origin/main")
        action(root)
        git(root, "add", "-A")
        git(root, "commit", "-qm", COLLECTOR_MESSAGE)
        git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
        git(self.root, "fetch", "-q", "origin", "main")
        return git(self.root, "rev-parse", "FETCH_HEAD")


class CollectorV4PartitionPolicy(Writers):
    """The concurrent-path policies of the FT and H1 publishers."""

    def check(self, remote, base=None):
        """FT accepts every remote path; H1 keeps them all."""
        base = base or self.fx.base
        changed = sorted(p.changed_paths(self.root, base, remote))
        self.assertEqual(p.allowed_remote_changes(self.root, base, remote, set(), set()), changed)
        h1.remote_policy(self.root, base, remote)
        return changed

    def refused(self, remote, text, base=None):
        base = base or self.fx.base
        with self.assertRaisesRegex(p.UnsafeFTPublication, text):
            p.allowed_remote_changes(self.root, base, remote, set(), set())
        with self.assertRaisesRegex(h1.UnsafeH1Publication, text):
            h1.remote_policy(self.root, base, remote)

    def partitioned(self):
        """main with journal parts 1..2, markets part0001 and a single formats file."""
        remote = self.collector(lambda r: grow(r, 2, 3))
        self.assertIsNotNone(self.fx.show(MARKETS_P1))
        self.assertIsNotNone(self.fx.show(part_of(journal(self.root), 2)))
        return remote

    # ------------------------------------------------------------------ accepted
    def test_journal_rotation_creates_part0001_and_is_accepted(self):
        before = self.fx.show(journal(self.root))
        changed = self.check(self.collector(lambda r: grow(r, 2)))
        self.assertIn(part_of(journal(self.root)), changed)
        self.assertNotIn(journal(self.root), changed, "closed base keeps its bytes")
        self.assertEqual(self.fx.show(journal(self.root)), before)

    def test_view_partition_creation_is_accepted(self):
        changed = self.check(self.partitioned())
        self.assertIn(MARKETS_P1, changed)

    def test_append_to_existing_view_part_and_new_format_part_are_accepted(self):
        base = self.partitioned()
        markets_base = self.fx.show(MARKETS)
        changed = self.check(self.collector(lambda r: grow(r, 4)), base)
        self.assertIn(MARKETS_P1, changed)
        self.assertIn(FORMATS_P1, changed)
        self.assertNotIn(MARKETS, changed)
        self.assertEqual(self.fx.show(MARKETS), markets_base)

    def test_legitimate_repartition_removing_a_view_part_is_accepted(self):
        # Without the small bound (same observation time as grow(r, 4)) write_monthly_view merges the view back into ONE file and
        # deletes part0001: a removed file that is not a lost event.
        base = self.partitioned()
        changed = self.check(self.collector(lambda r: observe(
            r, 4, observed="2026-11-02T09:00:00+00:00")), base)
        self.assertIn(MARKETS_P1, changed)
        self.assertIsNone(self.fx.show(MARKETS_P1))

    def test_audited_in_place_revision_of_a_view_is_accepted(self):
        # Before the fix the FT publisher applied the journal rule to the mutable view and
        # refused this legitimate, journalled Telegram edit ("V4/H1 journal rewritten").
        before = self.fx.show(MARKETS)
        changed = self.check(self.collector(lambda r: revise(r, 1, 1.80)))
        self.assertIn(MARKETS, changed)
        self.assertFalse(self.fx.show(MARKETS).startswith(before), "row changed in place")

    def test_audited_revision_inside_a_view_part_is_accepted(self):
        base = self.partitioned()
        before = self.fx.show(MARKETS_P1)
        changed = self.check(self.collector(lambda r: revise(r, 3, 1.70)), base)
        self.assertIn(MARKETS_P1, changed)
        self.assertFalse(self.fx.show(MARKETS_P1).startswith(before))

    # ------------------------------------------------------------------ refused
    def test_unjournalled_view_edit_is_refused(self):
        self.refused(self.collector(lambda r: edit_market_row(r, "c:1", 1.50)),
                     "Collector V4 change not proven")

    def test_unjournalled_edit_inside_a_view_part_is_refused(self):
        base = self.partitioned()
        remote = self.collector(lambda r: self.assertEqual(
            edit_market_row(r, "c:3", 1.50).name, Path(MARKETS_P1).name))
        self.refused(remote, "Collector V4 change not proven", base)

    def test_view_part_deleted_losing_events_is_refused(self):
        base = self.partitioned()
        self.refused(self.collector(lambda r: git(r, "rm", "-q", MARKETS_P1)),
                     "Collector V4 change not proven", base)

    def test_corrupt_row_appended_to_a_view_part_is_refused(self):
        base = self.partitioned()
        remote = self.collector(
            lambda r: (r / MARKETS_P1).write_bytes((r / MARKETS_P1).read_bytes() + b'{"event_id":\n'))
        self.refused(remote, "Collector V4 change not proven", base)

    def test_journal_part_rewritten_is_refused(self):
        base = self.partitioned()
        one, two = part_of(journal(self.root), 1), part_of(journal(self.root), 2)

        def swap(root):
            a, b = (root / one).read_bytes(), (root / two).read_bytes()
            (root / one).write_bytes(b)
            (root / two).write_bytes(a)
        self.refused(self.collector(swap), "V4 revision journal rewritten", base)

    def test_journal_part_deleted_is_refused(self):
        base = self.partitioned()
        self.refused(self.collector(lambda r: git(r, "rm", "-q", part_of(journal(r), 2))),
                     "V4 revision journal rewritten", base)

    def test_closed_journal_base_rewritten_while_rotating_is_refused(self):
        def action(root):
            name = root / journal(root)
            first = name.read_bytes()
            grow(root, 2)
            name.write_bytes(first.replace(b'"c:1"', b'"c:7"'))
        # Both proofs fail: the per-file append rule and the chain replay.
        self.refused(self.collector(action), "V4 revision (journal rewritten|chain altered)")

    def test_unknown_partition_like_names_remain_unknown(self):
        remote = self.collector(lambda r: write(r, "data/lab/markets-2026-11-part1.jsonl", "{}\n"))
        with self.assertRaisesRegex(p.UnsafeFTPublication, "Unknown concurrent path"):
            p.allowed_remote_changes(self.root, self.fx.base, remote, set(), set())


class FTPublishOverCollectorPartitions(Writers):
    """End to end: the real FT publisher transports a sealed FT commit over partitioned V4."""

    def setUp(self):
        super().setUp()
        self.base = git(self.root, "rev-parse", "HEAD")
        ledger = self.root / "data/lab/ft-ledger.json"
        self.baseline = self.fx.home / "baseline.json"
        self.baseline.write_text(json.dumps(final_snapshot(ledger.read_bytes())))
        value = json.loads(ledger.read_text())
        value["matches"]["2026-11-02,3,4"] = {"status": "FINAL",
                                              "result": {"home_goals": 2, "away_goals": 2}}
        write(self.root, "data/lab/ft-ledger.json", value)
        write(self.root, "docs/lab/ft-results.json", {"final": 2})
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "data(lab): reconcile observed match FT [skip ci]")
        self.source = git(self.root, "rev-parse", "HEAD")
        hashes = {n: hashlib.sha256((self.root / n).read_bytes()).hexdigest()
                  for n in ("data/lab/ft-ledger.json", "docs/lab/ft-results.json")}
        self.manifest = self.fx.home / "seal.json"
        self.manifest.write_text(json.dumps({"pipeline": "ft", "segmented": {"backend": "segmented"},
                                             "sha256": hashes}))

    def publish(self, push_hook=None):
        old_run = p.run
        pushes = []

        def hooked(root, *args, **kwargs):
            if args and args[0] == "push":
                pushes.append(1)
                if push_hook:
                    push_hook(len(pushes))
            return old_run(root, *args, **kwargs)
        with patch.object(p, "run", side_effect=hooked), \
                patch.object(p.publication_guard, "verify", return_value=None), \
                patch.object(p, "discovery_verify", return_value=None), \
                patch("urllib.request.urlopen", side_effect=AssertionError("provider call")):
            result = p.publish(self.root, base=self.base, manifest=self.manifest,
                               baseline=self.baseline, max_attempts=5, sleep=lambda s: None)
        return result, pushes

    def assert_collector_bytes_kept(self, collector_head):
        for name in git(self.fx.remote, "ls-tree", "-r", "--name-only", collector_head,
                        "--", "data/lab/").split():
            if name.startswith(("data/lab/markets-", "data/lab/formats-", "data/lab/v4-revisions-")):
                self.assertEqual(self.fx.show(name), self.fx.show(name, collector_head), name)
        self.assertEqual(self.fx.json("data/lab/ft-ledger.json"),
                         json.loads((self.root / "data/lab/ft-ledger.json").read_text()))

    def rotate_everything(self, root):
        grow(root, 2, 3, 4)       # journal parts 1..3, markets and formats part0001

    def test_ft_published_over_collector_partition_creation(self):
        head = self.collector(self.rotate_everything)
        published, pushes = self.publish()
        self.assertEqual(published, self.fx.main())
        self.assertEqual(git(self.fx.remote, "rev-parse", published + "^"), head)
        self.assertEqual(len(pushes), 1)
        self.assert_collector_bytes_kept(head)
        self.assertIsNotNone(self.fx.show(MARKETS_P1))
        self.assertIsNotNone(self.fx.show(FORMATS_P1))
        self.assertIsNotNone(self.fx.show(part_of(journal(self.root), 3)))

    def test_ft_recovers_from_cas_race_with_a_collector_revision_in_a_part(self):
        self.collector(self.rotate_everything)
        state = {}

        def race(n):
            if n == 1:   # the collector lands an audited edit between fetch and push
                state["head"] = self.collector(lambda r: revise(r, 3, 1.70), "collector2")
        published, pushes = self.publish(race)
        self.assertEqual(len(pushes), 2, "CAS rejection then revalidated retry")
        self.assertEqual(git(self.fx.remote, "rev-parse", published + "^"), state["head"])
        self.assert_collector_bytes_kept(state["head"])

    def test_ft_refuses_over_an_unjournalled_rewrite_and_main_is_untouched(self):
        self.collector(self.rotate_everything)
        bad = self.collector(lambda r: edit_market_row(r, "c:3", 1.40))
        with self.assertRaisesRegex(p.UnsafeFTPublication, "Collector V4 change not proven"):
            self.publish()
        self.assertEqual(self.fx.main(), bad)


if __name__ == "__main__":
    unittest.main()

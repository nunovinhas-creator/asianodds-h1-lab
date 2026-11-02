"""Offline demonstration of the FT observation checkpoint: bare Git, interruption, concurrency."""
import hashlib
import json
import multiprocessing
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import lab_ft_observation_checkpoint as ck
from scripts import lab_ft_publish_safe as p
from tests import test_lab_ft_publish_safe as base

KICKOFF = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)
OBSERVED = KICKOFF + timedelta(hours=3, minutes=17)       # like the lost 05:17 run
BODY = json.dumps({"event": {"id": 67067, "status": "finished", "home": 2, "away": 1}}).encode()


def bsd_parse(body, match_key):
    data = json.loads(body)["event"]
    if data["status"] != "finished":
        return None
    return {"event_id": data["id"], "home_goals": data["home"], "away_goals": data["away"]}


PARSERS = {"bsd": ("bsd-v11", bsd_parse)}


def observation(**over):
    obs = {"match_key": "2026-11-02,59190,67067", "provider": "bsd",
           "kickoff_utc": KICKOFF.isoformat(), "observed_at": OBSERVED.isoformat(),
           "http_status": 200, "adapter_version": "bsd-v11",
           "endpoint": "https://sports.bzzoiro.com/api/v2/events/67067/", "body": BODY,
           "provider_event_id": "67067"}
    obs.update(over)
    return obs


def document(run_id="41393026365", observations=None, **over):
    kw = dict(run_id=run_id, code_commit="9eb7f3f7357903dd75032980f471454723a739e3",
              remote_commit="edaf600ef255e6de03f9515189a4fc74d05b78f5",
              config_sha256="c" * 64, rejection_reasons=["HTTP 408"],
              observations=observations or [observation()], created_at=OBSERVED)
    kw.update(over)
    return ck.build(**kw)


def _child_write(directory, crash):
    doc = document()
    if crash:
        ck.write_once(directory, doc, before_rename=lambda: os._exit(9))
    ck.write_once(directory, doc)


class CheckpointRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def replay(self, doc, now, **kw):
        return ck.replay(doc, now=now, parsers=kw.pop("parsers", PARSERS),
                         trusted_run_ids={"41393026365"}, **kw)

    def test_reuse_within_window_needs_no_provider_call_and_is_never_final(self):
        path = ck.write_once(self.dir, document())
        with patch("urllib.request.urlopen", side_effect=AssertionError("provider call")):
            reusable, refused = self.replay(ck.load(path), OBSERVED + timedelta(minutes=40))
        self.assertEqual(refused, [])
        self.assertEqual(reusable[0].derived, {"event_id": 67067, "home_goals": 2, "away_goals": 1})
        self.assertFalse(reusable[0].certified)
        self.assertFalse(hasattr(reusable[0], "status"))
        with self.assertRaises(ck.CheckpointRefused):
            ck.UncertifiedObservation("k", "bsd", OBSERVED.isoformat(), {}, "r", certified=True)

    def test_window_and_staleness(self):
        with self.assertRaisesRegex(ck.CheckpointRefused, "after the 24 h window"):
            document(observations=[observation(observed_at=(KICKOFF + timedelta(hours=25)).isoformat())])
        doc = document()
        self.assertEqual(self.replay(doc, KICKOFF + timedelta(hours=24, seconds=1))[1][0][2],
                         "window_elapsed_at_replay")
        self.assertEqual(self.replay(doc, OBSERVED + timedelta(hours=6, seconds=1))[1][0][2],
                         "stale_observation")
        self.assertEqual(self.replay(doc, OBSERVED - timedelta(minutes=1))[1][0][2], "observed_in_future")

    def test_tamper_and_provenance(self):
        path = ck.write_once(self.dir, document())
        raw = json.loads(path.read_text())
        raw["observations"][0]["observed_at"] = KICKOFF.isoformat()  # back-dating
        path.chmod(0o644)
        bad = self.dir / "bad.json"
        bad.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ck.CheckpointRefused, "seal mismatch"):
            ck.load(bad)
        # body swapped and resealed by an attacker: the body hash still refuses it
        raw = json.loads(path.read_text())
        raw["observations"][0]["body_b64"] = __import__("base64").b64encode(b'{"event":{}}').decode()
        raw.pop("seal")
        raw["seal"] = hashlib.sha256(ck._canonical(raw)).hexdigest()
        self.assertEqual(self.replay(raw, OBSERVED + timedelta(minutes=5))[1][0][2], "body_hash_mismatch")
        with self.assertRaisesRegex(ck.CheckpointRefused, "provenance"):
            ck.replay(document(run_id="999"), now=OBSERVED, parsers=PARSERS, trusted_run_ids={"1"})

    def test_incompatible_adapter_refused(self):
        parsers = {"bsd": ("bsd-v12", lambda body, key: None)}
        reusable, refused = self.replay(document(), OBSERVED + timedelta(minutes=5), parsers=parsers)
        self.assertEqual((reusable, refused[0][2]), ([], "adapter_incompatible"))

    def test_secret_and_size_limits(self):
        with self.assertRaisesRegex(ck.CheckpointRefused, "credential"):
            document(observations=[observation(body=b'{"api_key":"x"}')])
        with self.assertRaisesRegex(ck.CheckpointRefused, "body outside"):
            document(observations=[observation(body=b"x" * (ck.MAX_BODY_BYTES + 1))])
        with self.assertRaisesRegex(ck.CheckpointRefused, "count outside"):
            document(observations=[observation(match_key=str(i)) for i in range(ck.MAX_OBSERVATIONS + 1)])

    def test_interrupted_writer_leaves_no_checkpoint_and_rerun_succeeds(self):
        proc = multiprocessing.get_context("fork").Process(target=_child_write, args=(self.dir, True))
        proc.start()
        proc.join(30)
        self.assertEqual(proc.exitcode, 9)
        self.assertEqual(list(self.dir.glob("ft-checkpoint-*.json")), [])
        path = ck.write_once(self.dir, document())
        self.assertEqual(ck.load(path)["seal"], document()["seal"])

    def test_concurrent_writers_produce_one_identical_checkpoint(self):
        ctx = multiprocessing.get_context("fork")
        procs = [ctx.Process(target=_child_write, args=(self.dir, False)) for _ in range(4)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(30)
        self.assertTrue(all(proc.exitcode == 0 for proc in procs))
        self.assertEqual(len(list(self.dir.glob("ft-checkpoint-*.json"))), 1)
        with self.assertRaisesRegex(ck.CheckpointRefused, "different checkpoint"):
            ck.write_once(self.dir, document(rejection_reasons=["other"]))


class ProvenanceReview(unittest.TestCase):
    """Phase-5 review items: the local seal is integrity, not authenticated origin."""

    def run_record(self, **over):
        rec = {"id": 41393026365, "repository": ck.SOURCE_REPOSITORY, "path": ck.SOURCE_WORKFLOW,
               "head_sha": "9eb7f3f7357903dd75032980f471454723a739e3",
               "created_at": "2026-11-02T05:16:15Z", "updated_at": "2026-11-02T05:17:51Z"}
        rec.update(over)
        return rec

    def test_github_vouches_for_workflow_commit_bytes_and_time(self):
        doc = document()
        raw = ck._canonical(doc)
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(ck.verify_provenance(doc, self.run_record(), digest, raw), {"41393026365"})
        for bad in ({"path": ".github/workflows/other.yml"}, {"repository": "evil/fork"},
                    {"head_sha": "0" * 40}, {"id": 1}, {"updated_at": "2026-11-02T05:16:59Z"}):
            with self.subTest(bad=bad), self.assertRaises(ck.CheckpointRefused):
                ck.verify_provenance(doc, self.run_record(**bad), digest, raw)

    def test_body_swap_with_recomputed_hashes_is_caught_by_github_digest(self):
        doc = document()
        digest = hashlib.sha256(ck._canonical(doc)).hexdigest()   # what GitHub stored
        forged = json.loads(ck._canonical(doc))
        new_body = json.dumps({"event": {"id": 67067, "status": "finished", "home": 0, "away": 3}}).encode()
        forged["observations"][0]["body_b64"] = __import__("base64").b64encode(new_body).decode()
        forged["observations"][0]["body_sha256"] = hashlib.sha256(new_body).hexdigest()
        forged.pop("seal")
        forged["seal"] = hashlib.sha256(ck._canonical(forged)).hexdigest()   # locally "valid"
        with self.assertRaisesRegex(ck.CheckpointRefused, "differ from the artifact"):
            ck.verify_provenance(forged, self.run_record(), digest, ck._canonical(forged))

    def test_premature_other_game_and_header_fields_refused(self):
        with self.assertRaisesRegex(ck.CheckpointRefused, "Premature"):
            document(observations=[observation(observed_at=(KICKOFF + timedelta(minutes=60)).isoformat())])
        with self.assertRaisesRegex(ck.CheckpointRefused, "Unexpected observation fields"):
            document(observations=[observation(headers={"x-apisports-key": "k"})])
        with self.assertRaisesRegex(ck.CheckpointRefused, "event id"):
            document(observations=[observation(provider_event_id="")])
        other = document(observations=[observation(provider_event_id="99999")])
        reusable, refused = ck.replay(other, now=OBSERVED + timedelta(minutes=5), parsers=PARSERS,
                                      trusted_run_ids={"41393026365"})
        self.assertEqual((reusable, refused[0][2]), ([], "identity_mismatch"))


class BareGitRejectionDemo(base.GitFTPublicationTests):
    """A refused publication keeps its observations; the remote ledger stays untouched."""

    def test_rejected_publication_checkpoint_then_reuse_without_provider(self):
        self.collector_commit({"h1lab/lab_results.py": "# FT rule changed during the poll\n"})
        remote_before = base.git(self.other, "rev-parse", "HEAD")
        with self.assertRaisesRegex(p.UnsafeFTPublication, "program changed") as refusal:
            self.publish()
        out = Path(self.tmp.name) / "artifact"
        path = ck.write_once(out, document(run_id="41393026365",
                                           code_commit=self.base, remote_commit=remote_before,
                                           rejection_reasons=[str(refusal.exception)]))
        self.assertEqual(base.git(self.remote, "rev-parse", "refs/heads/main"), remote_before)
        self.assertEqual(base.git(self.remote, "show", "main:data/lab/ft-ledger.json"), base.ft(1).strip())
        calls = []
        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: calls.append(a)):
            reusable, refused = ck.replay(ck.load(path), now=OBSERVED + timedelta(minutes=40),
                                          parsers=PARSERS, trusted_run_ids={"41393026365"})
        self.assertEqual(calls, [])
        self.assertEqual(len(reusable), 1)
        self.assertEqual(refused, [])
        # Nothing reached the ledger: certification remains the normal path's job.
        self.assertEqual(base.git(self.remote, "show", "main:data/lab/ft-ledger.json"), base.ft(1).strip())


for _name in [n for n in dir(base.GitFTPublicationTests) if n.startswith("test_")]:
    if _name not in BareGitRejectionDemo.__dict__:
        setattr(BareGitRejectionDemo, _name, None)


if __name__ == "__main__":
    unittest.main()

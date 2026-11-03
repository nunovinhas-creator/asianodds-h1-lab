"""Concurrency-safe publication of the V6 offline statistics report (no rebase, no force push).

Replaces the bare ``git push origin HEAD:main`` of ``v6-offline-statistics.yml``, which
failed with ``[rejected] HEAD -> main (fetch first)`` whenever the collector, FT or
LAB V4 published during the ~1 minute between checkout and push (runs 41420785839
and 41540018891). Transport, CAS retry and push-outcome handling are the shared
selective engine (``scripts.git_selective_publish``) used by the collector, H1, FT
and LAB V4 publishers; this module only adds the V6 dependency policy.

Scientific isolation
--------------------
The report is a pure, offline function of tracked repository files (``V6 inputs``,
see ``is_input``). It never calls an LLM, a sports provider or Telegram. A
recomputation in the publish job runs the same ``h1lab.v6_offline_statistics.build``
with sockets and subprocesses blocked by an audit hook.

Policy for every path changed concurrently on ``main`` since the input commit:

* non-input paths of a known owner (``docs/data.json``, H1 results, V4 reports the
  V6 build does not read, Telegram receipts, ...): kept byte-for-byte; the report is
  transported unchanged because its inputs did not move;
* a VALID change of a V6 input (``data/state.json``, top-level ``data/lab/*``, the LLM
  investigator archives, the V4 reports quoted by the planner): the report computed on
  the old inputs is NOT published. It is recomputed offline on the exact remote inputs
  (bounded by the engine's attempts) and published with ``V6-Input-Commit: <remote>``;
* an INCOMPATIBLE input change refuses (red, receipt, bundle): FT FINAL changed or
  removed, append-only journal rewritten, fixture identity rewritten, input deleted,
  or the recomputation itself fails;
* a program/config change: ``SUPERSEDED_BY_NEWER_INPUTS`` (exit 0, receipt). The report
  was produced by code no longer on main and the publish job never runs unreviewed
  code; the next scheduled run (<= 6 h) recomputes with the new program;
* another writer of the V6 outputs: the immutable history of an earlier run may only
  be ADDED, never rewritten or deleted; this run's own history file appearing on main
  is a concurrent writer and refuses; an unknown path refuses.

Immutability: ``docs/lab/llm-statistics-runs/<run_id>.json`` must be absent on the
base and on every remote it is published over; it is never overwritten. A re-run of
an already published run is recognised up-front (``ALREADY_PUBLISHED_FOR_RUN``).

Every outcome writes one ``V6_OFFLINE_STATS_PUBLISH_RECEIPT`` (stdout + JSON file)
with the input commit, the published commit and the sha256 of the published report,
so ``git show <published>:<run file> | sha256sum`` verifies it independently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts import git_publish_outcome as outcome
from scripts import git_selective_publish as sel
from scripts import publication_ownership as own
from scripts.h1_publish_safe import UnsafeH1Publication, verify_ft_inputs
from scripts.lab_ft_publish_safe import append_only_jsonl, stable_fixtures

NAME = "V6_OFFLINE_STATS"
REPORT = "docs/lab/llm-statistics.json"
RUNS_DIR = "docs/lab/llm-statistics-runs/"
RUN_FILE = re.compile(r"docs/lab/llm-statistics-runs/(\d+)\.json\Z")
TRAILER = "V6-Input-Commit: "
MESSAGE = "data(llm): offline statistical audit %s [skip ci]"
# V4/FT reports read by the discovery planner (h1lab.v6_llm_investigator.SOURCES).
PLANNER_SOURCES = frozenset({
    "docs/lab/v6-p0-gates.json", "docs/lab/v6-falsification.json", "docs/lab/v6-readiness.json",
    "docs/lab/v6-weekly-drift.json", "docs/lab/pattern-research.json"})
INVESTIGATOR_RUN = re.compile(r"docs/lab/llm-investigator-runs/[^/]+\.json\Z")
EXPECTED_STATUS = "LLM_OFFLINE_EXPLORATORY_NO_PROMOTION"


def is_input(path):
    """Every tracked file the offline build reads (or lists): see tests for the traced proof."""
    if path == own.COLLECT_STATE or path in PLANNER_SOURCES or INVESTIGATOR_RUN.fullmatch(path):
        return True
    return path.startswith("data/lab/") and "/" not in path[len("data/lab/"):]


def run_path(run_id):
    if not re.fullmatch(r"\d+", str(run_id or "")):
        raise sel.PublicationRefused("Invalid run id", "INVALID_INPUT")
    return RUNS_DIR + str(run_id) + ".json"


def source_hashes(root, ref):
    """``source_sha256`` exactly as ``build`` computes it, from the blobs of ``ref``."""
    names = git_ls(root, ref, "data/lab/")
    hashes = {}
    for name in names:
        rest = name[len("data/lab/"):]
        if "/" in rest or ".json" not in rest:
            continue
        hashes[name] = hashlib.sha256(sel.blob(root, ref, name) or b"").hexdigest()
    state = sel.blob(root, ref, own.COLLECT_STATE)
    if state is None:
        raise sel.PublicationRefused("data/state.json missing", "INVALID_INPUT")
    hashes[own.COLLECT_STATE] = hashlib.sha256(state).hexdigest()
    return hashes


def git_ls(root, ref, prefix):
    raw = sel.git(root, "ls-tree", "-z", "--name-only", ref, "--", prefix)
    return [n.decode("utf-8") for n in raw.split(b"\0") if n]


def check_report(raw, label):
    """Research-only invariants (the same ones the evaluate job asserts)."""
    try:
        report = json.loads(raw)
    except (TypeError, ValueError):
        raise sel.PublicationRefused("Unreadable V6 report: " + label, "INTEGRITY")
    if not isinstance(report, dict) or report.get("status") != EXPECTED_STATUS \
            or report.get("llm_calls") != 0 or report.get("validated") != 0 \
            or not isinstance(report.get("hypotheses"), list) \
            or any(h.get("scientifically_proven") is not False for h in report["hypotheses"]) \
            or not isinstance(report.get("source_sha256"), dict) \
            or not isinstance(report.get("generated_at"), str):
        raise sel.PublicationRefused("V6 report violates research-only invariants: " + label,
                                     "INTEGRITY")
    return report


# ------------------------------------------------------------------ offline recomputation
_OFFLINE = {"active": False}
_BLOCKED = ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "urllib.Request",
            "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "http.client.connect")


def _audit(event, _args):
    if _OFFLINE["active"] and event.startswith(_BLOCKED):
        raise RuntimeError("V6_OFFLINE_ISOLATION: %s blocked during recomputation" % event)


_HOOKED = {"done": False}


def offline_build(root, now):
    """The production build, with network and subprocesses blocked while it runs."""
    from h1lab.v6_offline_statistics import build
    if not _HOOKED["done"]:
        sys.addaudithook(_audit)
        _HOOKED["done"] = True
    _OFFLINE["active"] = True
    try:
        return build(Path(root), now=now)
    finally:
        _OFFLINE["active"] = False


def serialize(report):
    from scripts.lab_v6_offline_statistics import serialize as dump
    return dump(report).encode("utf-8")


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


# ------------------------------------------------------------------ policy
class V6OfflineStatsPolicy(sel.Policy):
    name = NAME

    def __init__(self, run_id, *, builder=offline_build, clock=utcnow):
        self.run_id = str(run_id)
        self.run_file = run_path(run_id)
        self.rerender_paths = frozenset({REPORT, self.run_file})
        self.builder, self.clock = builder, clock
        self.base = None
        self._remote = None
        self.recomputations = []
        self.message = MESSAGE % self.run_id

    def _message(self, input_commit):
        return MESSAGE % self.run_id + "\n\n" + TRAILER + input_commit

    def owns(self, path):
        return path in self.rerender_paths

    def verify_own(self, root, base, source, produced):
        self.base = base
        self.message = self._message(base)
        if produced != self.rerender_paths:
            sel_refuse("Producer commit must add exactly the latest report and its run file: %r"
                       % sorted(produced), "INVALID_INPUT")
        if sel.blob(root, base, self.run_file) is not None:
            sel_refuse("Immutable run history already exists on the base: " + self.run_file,
                       "INTEGRITY")
        body = sel.git(root, "log", "-1", "--format=%B", source).decode()
        if TRAILER in body and (TRAILER + base) not in body:
            sel_refuse("V6 commit names a different input commit", "INVALID_INPUT")
        latest, history = sel.blob(root, source, REPORT), sel.blob(root, source, self.run_file)
        if latest != history:
            sel_refuse("Latest report and run history differ", "INTEGRITY")
        report = check_report(latest, "producer")
        # Provenance: the report must describe exactly the inputs of the commit it was built on.
        if report["source_sha256"] != source_hashes(root, base):
            sel_refuse("Report source_sha256 does not match its base commit", "INVALID_INPUT")
        return {"producer_input_commit": base, "run_file": self.run_file,
                "producer_report_sha256": hashlib.sha256(latest).hexdigest(),
                "producer_generated_at": report["generated_at"]}

    def check_remote(self, root, base, remote, path, produced, source):
        if remote != self._remote:      # first path of a new attempt: inputs assumed unchanged
            self._remote = remote
            self.message = self._message(base)
        owner = own.owner_of(path)
        before, after = sel.blob(root, base, path), sel.blob(root, remote, path)
        if owner is None:
            sel_refuse("Unknown concurrent path: " + path, "UNKNOWN_PATH")
        if owner == own.PROGRAM:
            raise sel.Superseded("Program/config changed on main since %s: %s" % (base[:12], path))
        if owner == own.OFFLINE_STATS:
            if path == self.run_file:
                sel_refuse("Concurrent writer of this run's immutable history: " + path,
                           "CONCURRENT_OWNER_WRITE")
            if RUN_FILE.fullmatch(path):
                if before is not None:
                    sel_refuse("Immutable V6 run history rewritten or deleted: " + path, "INTEGRITY")
                check_report(after, path)
                return "keep"
            if path == REPORT:
                if after is None:
                    sel_refuse("Latest V6 report deleted concurrently", "INTEGRITY")
                return self._recompute(remote)    # never regress a newer latest report
            sel_refuse("Unexpected V6 output path: " + path, "UNKNOWN_PATH")
        if not is_input(path):
            return "keep"
        self._validate_input(path, before, after)
        return self._recompute(remote)

    def _validate_input(self, path, before, after):
        if after is None:
            sel_refuse("V6 input deleted concurrently: " + path, "DEPENDENCY_CHANGED")
        if path == own.FT_LEDGER:
            try:
                verify_ft_inputs(before, after)
            except UnsafeH1Publication as exc:
                sel_refuse("Incompatible FT input: %s" % exc, "INTEGRITY")
        elif own.is_append_only(path):
            if not append_only_jsonl(before, after):
                sel_refuse("Append-only V6 input journal rewritten: " + path, "INTEGRITY")
        elif path == own.COLLECT_STATE and before is not None:
            if not stable_fixtures(before, after):
                sel_refuse("Fixture identity rewritten under the V6 report: " + path, "INTEGRITY")

    def _recompute(self, remote):
        self.message = self._message(remote)
        return "rerender"

    def rerender(self, root):
        """Recompute offline on the candidate tree (= remote inputs + nothing else)."""
        head = sel.sha(root, "HEAD")
        now = self.clock()
        try:
            report = self.builder(root, now)
        except Exception as exc:  # any build failure is a documented safe refusal
            sel_refuse("Offline recomputation on %s failed: %s: %s"
                       % (head[:12], type(exc).__name__, str(exc)[:200]), "RECOMPUTE_FAILED")
        data = serialize(report)
        check_report(data, "recomputed")
        for path in (REPORT, self.run_file):
            target = Path(root) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.recomputations.append({"generated_at": report["generated_at"],
                                    "report_sha256": hashlib.sha256(data).hexdigest()})

    def verify_candidate(self, root, remote, candidate, produced):
        if sel.blob(root, remote, self.run_file) is not None:
            sel_refuse("Run history already on main; never overwritten: " + self.run_file,
                       "CONCURRENT_OWNER_WRITE")
        latest, history = sel.blob(root, candidate, REPORT), sel.blob(root, candidate, self.run_file)
        if latest is None or latest != history:
            sel_refuse("Candidate latest report and run history differ", "INTEGRITY")
        report = check_report(latest, "candidate")
        body = sel.git(root, "log", "-1", "--format=%B", candidate).decode()
        found = re.findall(re.escape(TRAILER) + r"([a-f0-9]{40})", body)
        if len(found) != 1:
            sel_refuse("Candidate has no unique V6 input commit", "INTEGRITY")
        input_commit = found[0]
        if not outcome.contains(root, input_commit, remote):
            sel_refuse("V6 input commit is not on main", "INTEGRITY")
        moved = sorted(p for p in sel.changed_paths(root, input_commit, remote) if is_input(p))
        if moved:
            sel_refuse("Report inputs differ from its input commit: %r" % moved[:8], "INTEGRITY")
        if report["source_sha256"] != source_hashes(root, candidate):
            sel_refuse("Report source_sha256 contradicts the published tree", "INTEGRITY")
        self.published_input_commit = input_commit
        self.published_report_sha256 = hashlib.sha256(latest).hexdigest()


def sel_refuse(message, kind):
    raise sel.PublicationRefused(message, kind)


def already_published(root, run_file, sleep=None):
    """Remote head and blob of this run's history when an earlier attempt already published it."""
    kwargs = {"sleep": sleep} if sleep else {}
    remote = outcome.remote_head(root, "main", **kwargs)
    if remote is None:
        return None, None
    return remote, sel.blob(root, remote, run_file)


def emit(path, document):
    """The single authoritative receipt of this publication attempt."""
    print(NAME + "_FINAL_RECEIPT", json.dumps(document, sort_keys=True))
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def publish(root, *, base, run_id, receipt=None, bundle=None, max_attempts=6, policy=None,
            push=sel.default_push, sleep=None):
    """Returns (status, receipt document). Raises PublicationRefused/Superseded otherwise."""
    import tempfile
    import time
    policy = policy or V6OfflineStatsPolicy(run_id)
    sleep = sleep or time.sleep
    common = {"base": base, "run_id": str(run_id), "run_file": policy.run_file,
              "provider_requeries": 0, "telegram_requests": 0, "llm_calls": 0,
              "force_push": False, "rebase": False}
    remote, existing = already_published(root, policy.run_file, sleep=sleep)
    if existing is not None:
        doc = {**common, "status": "ALREADY_PUBLISHED_FOR_RUN",
               "path": "IMMUTABLE_RUN_ALREADY_ON_MAIN", "remote": remote,
               "published_report_sha256": hashlib.sha256(existing).hexdigest()}
        emit(receipt, doc)
        return doc["status"], doc
    with tempfile.TemporaryDirectory(prefix="v6-receipt-") as tmp:
        engine_path = Path(tmp) / "engine.json"
        try:
            commit = sel.publish(root, base=base, policy=policy, receipt=engine_path,
                                 bundle=bundle, max_attempts=max_attempts, push=push, sleep=sleep)
            error = None
        except sel.PublicationRefused as exc:
            commit, error = None, exc
        engine = json.loads(engine_path.read_text()) if engine_path.exists() else {}
    doc = {**engine, **common, "recomputed": bool(policy.recomputations),
           "recomputations": policy.recomputations}
    if error is None:
        doc.update({"published_commit": commit,
                    "input_commit": getattr(policy, "published_input_commit", None),
                    "published_report_sha256": getattr(policy, "published_report_sha256", None)})
    emit(receipt, doc)
    if error is not None:
        raise error
    return doc["status"], doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--max-attempts", type=int, default=6)
    args = parser.parse_args(argv)
    try:
        status, _ = publish(args.root, base=args.base, run_id=args.run_id, receipt=args.receipt,
                            bundle=args.bundle, max_attempts=args.max_attempts)
    except sel.Superseded as exc:
        print("::notice title=V6_OFFLINE_STATS_SUPERSEDED::%s" % str(exc)[:300])
        print("V6_OFFLINE_STATS_SUPERSEDED")
        return 0
    except sel.PublicationRefused as exc:
        print("::error title=V6_OFFLINE_STATS_PUBLISH_FAILED::%s %s" % (exc.kind, str(exc)[:300]))
        print("V6_OFFLINE_STATS_PUBLISH_FAILED")
        return 1
    print("V6_OFFLINE_STATS_" + status)
    return 0


if __name__ == "__main__":
    sys.exit(main())

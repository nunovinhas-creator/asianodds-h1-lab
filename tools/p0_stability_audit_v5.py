"""MASTER BRAIN — P0 read-only stability audit of the four safe publishers (#107). V5.

V5 = V4 (commit db2d40685e787b0f5af0febb0b51e69ebf39971b, ``tools/p0_stability_audit.py``,
sha256 46f0fafe9bf817c3375c9c49aeac274684eac57e5a449f97c19ba01959b5eb51, left unchanged)
plus one correction found by the 24 h audit of 2026-11-03:

  * Telegram ledgers are read **as declared at each audited revision** (``TELEGRAM_LEDGERS``
    parsed with ``ast`` from ``scripts/publication_ownership.py`` at that commit), never from
    the working tree. V4 imported the CURRENT module, so after PR #209 (2026-11-02T18:35Z,
    ``TELEGRAM_LEDGERS = (E5_LEDGER,)``) it counted 0 ``sent`` at baseline b8bc46ca, whose
    ledgers were three-total-moves (6) + two-up-total (7) = 13 → false ``BASELINE_INVALID``.
    The same import made the commit-by-commit Telegram check (and the integrity table)
    watch only the E5 ledger, so the legacy ledgers' transitions before #209 were not
    verified. V5 checks the union of every ledger declared anywhere in ``[baseline, head]``.
    An unparseable declaration is an evidence gap (``HISTORY_UNAVAILABLE``), never a guess.

Read-only by construction:
  * GitHub: only GET requests (runs, jobs, job logs, Pages metadata). Never posts,
    dispatches, re-runs, merges or pushes. Commenting on #107 is done separately by
    the operator/session, never by this script.
  * Git: reads ``origin/main`` objects (``git fetch`` only); verifiers run in a throwaway
    ``git worktree`` under a temporary directory that is removed afterwards; nothing is
    committed.
  * No sports-provider calls, no Telegram calls.

Usage (from a clone of the repository, with ``gh`` authenticated):
  python tools/p0_stability_audit_v5.py --label 24h --start 2026-11-02T09:58:45Z \
      --hours 24 --out /path/report.md --json /path/report.json [--cache DIR]

Window semantics (half-open): ``[start, start + hours)``, truncated to ``now`` when the
window has not fully elapsed (the report then says "JANELA INCOMPLETA").  Each run carries
three distinct instants: creation/start (``created_at``), conclusion (``updated_at``) and
publication (timestamp of its ``*_PUBLISH_RECEIPT`` log line).  A publication counts for a
window only when the *receipt* timestamp is inside the window; a green workflow without a
receipt is never counted as a publication.

Missing evidence (logs unavailable, GitHub API errors, unreadable receipts, green runs
without receipt, runs still in progress at window close, history not reachable) is reported
as an *evidence gap* and yields ``INCONCLUSIVO_OPERACIONAL`` — never "no incidents" and
never a corruption incident.
"""
from __future__ import annotations

import argparse
import hashlib
import concurrent.futures as cf
import csv
import io
import urllib.parse
import zipfile
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = "nunovinhas-creator/asianodds-h1-lab"
MERGE_206 = "b8bc46cab95549a3f43a5b05dd3c5693af723398"
WINDOW_START = "2026-11-02T09:58:45Z"
# Baseline = the state of main AT the window start: the #206 merge itself (committed
# 2026-11-02T09:58:45Z).  Counts verified from the real commit objects.
BASELINE_COMMIT = MERGE_206
BASELINE_COUNTS = {
    "ft": {"FINAL": 446, "EXPIRED_UNVERIFIED": 423, "PENDING": 308, "IDENTITY_CONFLICT": 1},
    "h1_certified": 116,
    "telegram_sent": 13,
}
# Commits that must never be used as the opening snapshot of the window.
REJECTED_BASELINES = {
    "2fbc3e93f6482707c82d23a7a12873021582262c":
        "posterior ao início da janela (2026-11-02T10:07:14Z; 447 FINAL)",
}
PUBLISHERS = {  # workflow file -> (label, receipt prefix)
    "collect.yml": ("Coletor", "COLLECT"),
    "lab-v4-audit.yml": ("LAB V4", "LAB_V4"),
    "lab-ft-results.yml": ("FT", "FT"),
    "results.yml": ("H1", "H1"),
}
RESULTS_CSV = "data/results.csv"
FT_LEDGER = "data/lab/ft-ledger.json"
RECEIPT = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+"
                     r"(?P<prefix>[A-Z0-9_]+)_PUBLISH_RECEIPT (?P<doc>\{\".*\})\s*$")
RECEIPT_TS = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s")
FLAG = re.compile(r"^\S+\s+(TG_DURABLE_INTENT|TG_IGNORE_AUTH_BLOCK): (\S+)\s*$")
TG_BLOCK_SIGNAL = re.compile(r"(TELEGRAM[A-Z_]*(BLOCK|429|401|403)[A-Z_]*|retry_after|"
                             r"Too Many Requests|Unauthorized|Forbidden: bot)", re.I)
LOG_UNAVAILABLE = "__LOG_UNAVAILABLE__"
ALERT_STREAK, ALERT_GAP_MIN, ALERT_RATE, ALERT_RATE_MIN_N = 3, 30, 0.25, 8
LOOKBACK = timedelta(hours=3)  # runs created before the window may still publish inside it

# Evidence states of a run (``evidence`` field).
EV_RECEIPT = "RECEIPT"                          # readable receipt (any status)
EV_GREEN_NO_RECEIPT = "GREEN_NO_RECEIPT"        # success, no receipt: NOT a publication
EV_FAILED_NO_RECEIPT = "FAILED_NO_RECEIPT"      # failure/timed_out, no receipt: observed failure
EV_CANCELLED_NO_RECEIPT = "CANCELLED_NO_RECEIPT"
EV_LOGS_UNAVAILABLE = "LOGS_UNAVAILABLE"
EV_API_ERROR = "GITHUB_API_ERROR"
EV_IN_PROGRESS = "IN_PROGRESS_AT_WINDOW_CLOSE"
EV_RECEIPT_UNREADABLE = "RECEIPT_UNREADABLE"
# Green run, no receipt, and the jobs API shows every publish/receipt/push step SKIPPED
# (e.g. H1 "Avoid duplicate queued result cycles"): no publication was attempted.  Not a
# publication, not an incident; listed as a non-blocking evidence note because the
# producer emitted no NOTHING_TO_PUBLISH receipt.
EV_NO_PUBLISH_ATTEMPT = "GREEN_NO_RECEIPT_PUBLISH_STEPS_SKIPPED"
PUBLISH_STEP = re.compile(r"publish|receipt|push", re.I)
GAP_EVIDENCE = {EV_GREEN_NO_RECEIPT, EV_CANCELLED_NO_RECEIPT, EV_LOGS_UNAVAILABLE, EV_API_ERROR,
                EV_IN_PROGRESS, EV_RECEIPT_UNREADABLE}
# Window position of a run.
POS_IN = "IN_WINDOW"
POS_STARTED_BEFORE = "STARTED_BEFORE_WINDOW"      # created before start, published/ended inside
POS_PUBLISHED_AFTER = "PUBLISHED_AFTER_WINDOW"    # receipt timestamp >= end: next window
POS_OUTSIDE = "OUTSIDE_WINDOW"                    # nothing of it belongs to this window


class EvidenceGap(Exception):
    """Evidence needed for a verdict could not be collected (never a violation)."""


class GhError(RuntimeError):
    def __init__(self, path, status, msg):
        super().__init__(f"gh api {path}: HTTP {status}: {msg}")
        self.path, self.status = path, status


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s):
    if s is None:
        return None
    s = s.strip().replace("Z", "+00:00")
    if "." in s:  # drop fractional seconds, keep offset
        head, _, tail = s.partition(".")
        off = re.search(r"[+-]\d{2}:\d{2}$", tail)
        s = head + (off.group(0) if off else "+00:00")
    dt = datetime.fromisoformat(s)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def window_bounds(start, hours, now):
    """Half-open window ``[start, end)``; ``end`` is truncated to ``now``."""
    nominal = start + timedelta(hours=hours)
    return start, min(now, nominal), now >= nominal


class ApiBudget:
    """Process-wide GitHub REST pacing and accounting (thread safe).

    * Paces request starts to ``rps`` (default 8/s, under GitHub's secondary limit of
      900 REST points/min).
    * Reads ``X-RateLimit-Remaining`` / ``X-RateLimit-Reset`` from every response and
      pauses until the reset when ``remaining`` drops below ``reserve``.
    * Honours ``Retry-After`` (and ``X-RateLimit-Reset`` when ``remaining`` is 0) on
      403/429; never hammers.
    * Gives up once cumulative waiting exceeds ``max_wait_s``: callers then record the
      affected runs as evidence gaps (never silently skipped).
    """

    def __init__(self, rps=8.0, reserve=300, max_wait_s=4500):
        self.min_interval = 1.0 / rps
        self.reserve, self.max_wait_s = reserve, max_wait_s
        self.lock = threading.Lock()
        self.next_slot = 0.0
        self.calls = self.errors = 0
        self.waited_s = 0.0
        self.waits = []
        self.remaining = self.reset = self.limit = None
        self.min_remaining = None
        self.exhausted = False

    def slot(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_slot)
            self.next_slot = t + self.min_interval
            self.calls += 1
        if t > now:
            time.sleep(t - now)

    def observe(self, headers):
        with self.lock:
            if "x-ratelimit-remaining" in headers:
                self.remaining = int(headers["x-ratelimit-remaining"])
                self.min_remaining = (self.remaining if self.min_remaining is None
                                      else min(self.min_remaining, self.remaining))
            if "x-ratelimit-reset" in headers:
                self.reset = int(headers["x-ratelimit-reset"])
            if "x-ratelimit-limit" in headers:
                self.limit = int(headers["x-ratelimit-limit"])

    def wait(self, seconds, why):
        seconds = max(1.0, float(seconds))
        with self.lock:
            if self.waited_s + seconds > self.max_wait_s:
                self.exhausted = True
                return False
            self.waited_s += seconds
            self.waits.append({"at": iso(datetime.now(timezone.utc)), "seconds": round(seconds),
                               "why": why})
        time.sleep(seconds)
        return True

    def guard(self):
        """Pause before a request if the primary budget is nearly spent."""
        if self.exhausted:
            raise GhError("-", None, "orçamento de espera da API esgotado")
        if self.remaining is not None and self.remaining < self.reserve and self.reset:
            delay = self.reset - time.time() + 5
            if delay > 0 and not self.wait(delay, f"remaining={self.remaining}<{self.reserve}"):
                raise GhError("-", None, "orçamento de espera da API esgotado")
            with self.lock:
                self.remaining = None

    def summary(self):
        return {"calls": self.calls, "errors": self.errors, "limit": self.limit,
                "remaining_last": self.remaining, "remaining_min": self.min_remaining,
                "waited_seconds": round(self.waited_s), "waits": self.waits[:20],
                "exhausted": self.exhausted, "rps_cap": round(1 / self.min_interval, 2)}


BUDGET = ApiBudget()


def split_response(raw):
    """``(status, headers, body_bytes)`` from ``gh api -i`` output."""
    for sep in (b"\r\n\r\n", b"\n\n"):
        if sep in raw:
            head, body = raw.split(sep, 1)
            break
    else:
        head, body = raw, b""
    lines = head.decode("latin-1").splitlines()
    m = re.match(r"HTTP/\S+\s+(\d{3})", lines[0]) if lines else None
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        headers[k.strip().lower()] = v.strip()
    return (int(m.group(1)) if m else None), headers, body


def gh(path, raw=False, retries=3, budget=None, binary=False, with_headers=False):
    budget = budget or BUDGET
    last = None
    for i in range(retries + 1):
        budget.guard()
        budget.slot()
        r = subprocess.run(["gh", "api", "-i", "-H", "Accept: application/vnd.github+json", path],
                           capture_output=True)
        status, headers, body = split_response(r.stdout)
        budget.observe(headers)
        if r.returncode == 0 and status and status < 300:
            if binary:
                return body
            text = body.decode("utf-8", errors="replace")
            data = text if raw else json.loads(text)
            return (data, headers) if with_headers else data
        if status is None:
            m = re.search(rb"HTTP (\d{3})", r.stderr)
            status = int(m.group(1)) if m else None
        msg = (body or r.stderr).decode("utf-8", errors="replace").strip()[:300]
        last = GhError(path, status, msg)
        with budget.lock:
            budget.errors += 1
        limited = status == 429 or (status == 403 and (
            "rate limit" in msg.lower() or headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in headers))
        if limited:
            if "retry-after" in headers:
                delay = float(headers["retry-after"])
            elif headers.get("x-ratelimit-remaining") == "0" and headers.get("x-ratelimit-reset"):
                delay = int(headers["x-ratelimit-reset"]) - time.time() + 5
            else:
                delay = 60 * (2 ** i)  # secondary limit without hint: exponential backoff
            if not budget.wait(delay, f"HTTP {status} {path[:60]}"):
                break
            continue
        if status and status < 500:
            break
        time.sleep(2 * (i + 1))
    raise last


def git(*args, cwd=".", check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout


def has_commit(sha):
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True).returncode == 0


def show(rev, path):
    r = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


# ----------------------------------------------------------------------------- baseline
_BLOB_CACHE: dict = {}


def blob_ids(rev, paths):
    out = git("ls-tree", rev, "--", *paths, check=False)
    ids = {}
    for ln in out.splitlines():
        meta, _, p = ln.partition("\t")
        ids[p] = meta.split()[2]
    return ids


def load_blob(blob, kind):
    key = (blob, kind)
    if key not in _BLOB_CACHE:
        raw = subprocess.run(["git", "cat-file", "blob", blob], capture_output=True,
                             check=True).stdout
        if kind == "results":
            _BLOB_CACHE[key] = {r["match_key"]: r
                                for r in csv.DictReader(io.StringIO(raw.decode()))}
        elif kind == "ft":
            _BLOB_CACHE[key] = json.loads(raw)["matches"]
        elif kind == "tg":
            _BLOB_CACHE[key] = json.loads(raw)["entries"]
        else:
            _BLOB_CACHE[key] = raw
    return _BLOB_CACHE[key]


OWNERSHIP_MODULE = "scripts/publication_ownership.py"
_LEDGER_CACHE: dict = {}


def declared_ledgers(source):
    """``TELEGRAM_LEDGERS`` of one ``publication_ownership.py`` source text, resolved with
    ``ast`` (module-level string constants and names only; nothing is executed)."""
    import ast
    tree = ast.parse(source)
    consts, target = {}, None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                consts[name] = value.value
            if name == "TELEGRAM_LEDGERS":
                target = value
    if not isinstance(target, (ast.Tuple, ast.List)):
        raise EvidenceGap("TELEGRAM_LEDGERS ausente ou não literal em " + OWNERSHIP_MODULE)
    out = []
    for elt in target.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            out.append(elt.value)
        elif isinstance(elt, ast.Name) and elt.id in consts:
            out.append(consts[elt.id])
        else:
            raise EvidenceGap("TELEGRAM_LEDGERS com elemento não resolúvel: " + ast.dump(elt)[:80])
    return out


def telegram_ledgers(rev=None):
    """Ledgers declared at ``rev`` (V5). ``rev=None`` keeps V4's working-tree behaviour and is
    used only where no revision applies."""
    if rev is None:
        sys.path.insert(0, str(Path.cwd()))
        from scripts import publication_ownership as own
        return list(own.TELEGRAM_LEDGERS)
    if rev not in _LEDGER_CACHE:
        raw = show(rev, OWNERSHIP_MODULE)
        if raw is None:
            raise EvidenceGap(f"{OWNERSHIP_MODULE} indisponível em {str(rev)[:12]}")
        _LEDGER_CACHE[rev] = declared_ledgers(raw.decode("utf-8"))
    return list(_LEDGER_CACHE[rev])


def window_ledgers(base, head):
    """Union of the ledgers declared at ``base``, ``head`` and at every commit in between that
    changed the ownership module (so retired ledgers stay verified)."""
    revs = [base, head] + git("log", "--format=%H", f"{base}..{head}", "--", OWNERSHIP_MODULE,
                              check=False).split()
    seen = []
    for rev in revs:
        for led in telegram_ledgers(rev):
            if led not in seen:
                seen.append(led)
    return seen


def snapshot(rev, parts=("results", "ft", "tg"), ledgers=None):
    """Parsed integrity-relevant state of ``rev`` (missing file -> None). ``ledgers``: the
    Telegram ledgers to read (default: those declared at ``rev`` itself)."""
    paths = {"results": [RESULTS_CSV], "ft": [FT_LEDGER],
             "tg": list(ledgers) if ledgers is not None else
             (telegram_ledgers(rev) if "tg" in parts else [])}
    want = [p for k in parts for p in paths[k]]
    ids = blob_ids(rev, want)
    snap = {}
    if "results" in parts:
        snap["results"] = load_blob(ids[RESULTS_CSV], "results") if RESULTS_CSV in ids else None
    if "ft" in parts:
        snap["ft"] = load_blob(ids[FT_LEDGER], "ft") if FT_LEDGER in ids else None
    if "tg" in parts:
        snap["tg"] = {p: (load_blob(ids[p], "tg") if p in ids else None) for p in paths["tg"]}
    return snap


def snapshot_counts(rev):
    if not has_commit(rev):
        raise EvidenceGap(f"commit {rev[:12]} indisponível no clone")
    s = snapshot(rev)
    if s["results"] is None or s["ft"] is None:
        raise EvidenceGap(f"ficheiros de integridade ausentes em {rev[:12]}")
    sent = sum(1 for ents in s["tg"].values() if ents
               for e in ents.values() if e.get("status") == "sent")
    return {"ft": dict(Counter(m["status"] for m in s["ft"].values())),
            "h1_certified": len(s["results"]), "telegram_sent": sent}


def commit_time(rev):
    return parse_ts(git("log", "-1", "--format=%cI", rev).strip())


def verify_baseline(rev, start, expected=None, counts=None, ctime=None, last_before=None):
    """Return the list of reasons why ``rev`` is NOT a valid opening snapshot (empty = ok).

    ``counts``/``ctime``/``last_before`` may be injected (tests); otherwise read from git.
    """
    expected = expected or BASELINE_COUNTS
    problems = []
    if rev in REJECTED_BASELINES:
        problems.append(f"baseline rejeitada: {REJECTED_BASELINES[rev]}")
    ctime = ctime if ctime is not None else commit_time(rev)
    if ctime > start:
        problems.append(f"commit {rev[:12]} ({iso(ctime)}) é posterior ao início da janela "
                        f"({iso(start)})")
    if last_before is None:
        last_before = git("rev-list", "-1", "--first-parent", f"--before={iso(start)}",
                          "origin/main", check=False).strip() or None
    if last_before and last_before != rev:
        problems.append(f"o último commit da main ≤ início é {last_before[:12]}, não {rev[:12]}")
    counts = counts if counts is not None else snapshot_counts(rev)
    for key in ("h1_certified", "telegram_sent"):
        if counts.get(key) != expected[key]:
            problems.append(f"{key}: {counts.get(key)} ≠ esperado {expected[key]}")
    for st, n in expected["ft"].items():
        if counts["ft"].get(st, 0) != n:
            problems.append(f"FT {st}: {counts['ft'].get(st, 0)} ≠ esperado {n}")
    extra = set(counts["ft"]) - set(expected["ft"])
    if extra:
        problems.append(f"FT estados inesperados na baseline: {sorted(extra)}")
    return problems


# ----------------------------------------------------------------------------- runs/logs
SEGMENT = timedelta(hours=12)


def list_runs(workflow, start, end, gaps, coverage=None):
    """Runs created in ``[start - LOOKBACK, end)``, listed per 12 h segment.

    Every segment records the API ``total_count`` and the run ids actually retrieved in
    ``coverage``; any listing error or count mismatch is an evidence gap naming the
    period (no silent exclusion).
    """
    coverage = coverage if coverage is not None else []
    runs, t = [], start - LOOKBACK
    while t < end:  # segments: the runs API caps a filtered query at 1000 results
        t2 = min(end, t + SEGMENT)
        seg = {"workflow": workflow, "from": iso(t), "to": iso(t2), "expected": None,
               "retrieved": 0, "ids_sha256": None, "complete": False}
        seg_runs, page, ok = [], 1, True
        while True:
            try:
                d = gh(f"repos/{REPO}/actions/workflows/{workflow}/runs?per_page=100&page={page}"
                       f"&created={iso(t)}..{iso(t2)}")
            except GhError as exc:
                gaps.append({"kind": EV_API_ERROR, "workflow": workflow, "run_id": None,
                             "detail": f"listagem {iso(t)}..{iso(t2)} p{page}: {exc}"})
                ok = False
                break
            if seg["expected"] is None:
                seg["expected"] = d.get("total_count")
            seg_runs += d["workflow_runs"]
            if len(d["workflow_runs"]) < 100:
                break
            page += 1
        ids = sorted({r["id"] for r in seg_runs})
        seg["retrieved"] = len(ids)
        seg["ids_sha256"] = hashlib.sha256(",".join(map(str, ids)).encode()).hexdigest()[:16]
        seg["complete"] = ok and seg["expected"] == len(ids) and len(ids) < 1000
        if ok and not seg["complete"]:
            gaps.append({"kind": "SEGMENT_INCOMPLETE", "workflow": workflow, "run_id": None,
                         "detail": f"{iso(t)}..{iso(t2)}: API total_count={seg['expected']}, "
                                   f"obtidos={len(ids)}"})
        coverage.append(seg)
        runs += seg_runs
        t = t2
    seen, out = set(), []
    for r in runs:
        if r["id"] not in seen and parse_ts(r["created_at"]) < end:
            seen.add(r["id"])
            out.append(r)
    return sorted(out, key=lambda r: r["created_at"])


def job_steps(jobs):
    return [{"job": j.get("name"), "step": st.get("name"), "conclusion": st.get("conclusion")}
            for j in jobs for st in (j.get("steps") or [])]


def publish_steps_all_skipped(steps):
    """True only when publish/receipt/push steps exist and every one was skipped."""
    pub = [s for s in (steps or []) if PUBLISH_STEP.search(s.get("step") or "")]
    return bool(pub) and all(s.get("conclusion") == "skipped" for s in pub)


RELEVANT = re.compile(r"_PUBLISH_RECEIPT|TG_DURABLE_INTENT|TG_IGNORE_AUTH_BLOCK|"
                      + TG_BLOCK_SIGNAL.pattern, re.I)


def _record_digest(rec):
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def cache_key(run):
    return f"{run['id']}-a{run.get('run_attempt', 1)}"


def load_cached(run, cache):
    """A cached evidence record, only if it is complete, for the same run id/attempt and
    conclusion time, and its self-digest verifies.  Anything else is refetched."""
    f = cache / f"{cache_key(run)}.json"
    if not f.exists():
        return None
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if (rec.get("run_id") != run["id"] or rec.get("run_attempt") != run.get("run_attempt", 1)
            or rec.get("updated_at") != run.get("updated_at") or not rec.get("complete")
            or rec.get("record_sha256") != _record_digest(rec)):
        return None
    return rec


def _job_logs_via_jobs_api(run, jobs):
    """Fallback: one request per non-skipped job.  Returns (lines, fingerprints, failed)."""
    lines, fp, failed = [], [], 0
    for job in jobs:
        if job.get("conclusion") == "skipped":
            continue
        try:
            body = gh(f"repos/{REPO}/actions/jobs/{job['id']}/logs", raw=True)
        except GhError as exc:
            failed += 1
            lines.append(f"{LOG_UNAVAILABLE} job={job['id']} {exc}")
            fp.append({"job_id": job["id"], "error": str(exc)[:200]})
            continue
        fp.append({"job_id": job["id"], "name": job.get("name"),
                   "log_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                   "log_bytes": len(body.encode("utf-8"))})
        lines += [ln for ln in body.splitlines() if RELEVANT.search(ln)]
    return lines, fp, failed


def _logs_via_zip(run):
    """One request: the run-attempt log archive (one top-level file per job).

    Returns ``(lines, fingerprints, n_job_files)`` or raises ``GhError``."""
    attempt = run.get("run_attempt", 1)
    blob = gh(f"repos/{REPO}/actions/runs/{run['id']}/attempts/{attempt}/logs", binary=True)
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise GhError("zip", None, f"arquivo de logs ilegível: {exc}")
    lines, fp, n = [], [{"zip_sha256": hashlib.sha256(blob).hexdigest(), "zip_bytes": len(blob)}], 0
    for info in sorted(z.infolist(), key=lambda i: i.filename):
        if "/" in info.filename or not info.filename.endswith(".txt"):
            continue  # per-step copies live in sub-folders; top-level file = whole job
        data = z.read(info)
        n += 1
        fp.append({"file": info.filename, "log_sha256": hashlib.sha256(data).hexdigest(),
                   "log_bytes": len(data)})
        lines += [ln for ln in data.decode("utf-8", errors="replace").splitlines()
                  if RELEVANT.search(ln)]
    return lines, fp, n


def run_logs(run, cache):
    """``(text, error, steps)`` for a completed run.

    Primary path: ONE request (run-attempt log zip).  The jobs listing (one more request)
    is only fetched when no receipt is visible, to prove either "every publish step was
    skipped" or "a job log is missing".  ``text`` holds only evidence-relevant lines;
    every log file is fingerprinted (sha256, bytes).  ``error`` is ``None``,
    ``GITHUB_API_ERROR`` or ``LOGS_UNAVAILABLE`` (a readable receipt still wins).
    Only complete records are cached, keyed by run id + attempt, validated on read.
    """
    rec = load_cached(run, cache)
    if rec:
        return "\n".join(rec["lines"]), None, rec["steps"]
    lines, fp, failed, steps, n_files = [], [], 0, None, None
    zip_error = None
    try:
        lines, fp, n_files = _logs_via_zip(run)
    except GhError as exc:
        zip_error = exc
    has_receipt = any("_PUBLISH_RECEIPT" in ln and "[36;1m" not in ln for ln in lines)
    if zip_error is not None or not has_receipt:
        try:
            jobs = gh(f"repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
        except GhError as exc:
            if zip_error is not None:
                return f"{LOG_UNAVAILABLE} {zip_error}; {exc}", EV_API_ERROR, None
            return "\n".join(lines), EV_API_ERROR, None  # cannot prove completeness
        steps = job_steps(jobs)
        wanted = sum(1 for j in jobs if j.get("conclusion") != "skipped")
        if zip_error is not None or (n_files or 0) < wanted:
            lines2, fp2, failed = _job_logs_via_jobs_api(run, jobs)
            lines, fp = lines2, fp + fp2
    rec = {"run_id": run["id"], "run_attempt": run.get("run_attempt", 1),
           "updated_at": run.get("updated_at"), "complete": failed == 0, "logs": fp,
           "steps": steps, "lines": lines}
    rec["record_sha256"] = _record_digest(rec)
    if failed == 0:
        (cache / f"{cache_key(run)}.json").write_text(json.dumps(rec), encoding="utf-8")
    return "\n".join(lines), (EV_LOGS_UNAVAILABLE if failed else None), steps


def classify(doc):
    s = doc.get("status")
    if s == "PUBLISHED":
        path = doc.get("path")
        if path in ("AFTER_CAS", "AFTER_TRANSPORT"):
            return path
        if doc.get("transport_failures"):
            return "AFTER_TRANSPORT"
        if int(doc.get("cas_retries", 0) or 0) > 0:
            return "AFTER_CAS"
        att = int(doc.get("attempt", doc.get("attempts", 1)) or 1)
        return "FIRST_ATTEMPT" if att == 1 else "AFTER_CAS"
    if s in ("PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR",):
        return "RECOVERED_408"
    if s == "ALREADY_PUBLISHED_EQUIVALENT":
        return "RECOVERED_EQUIVALENT"
    if s == "SUPERSEDED_BY_NEWER_INPUTS" or doc.get("reason_kind") == "SUPERSEDED_BY_NEWER_INPUTS":
        return "SUPERSEDED"
    if s == "REFUSED":
        return "INTEGRITY_REFUSAL"
    if s in ("RETRY_EXHAUSTED", "OUTCOME_UNRESOLVED", "PUSH_REFUSED"):
        return "UNRECOVERED_FAILURE"
    if s == "NOTHING_TO_PUBLISH":
        return "NOTHING_TO_PUBLISH"
    return "UNCLASSIFIED:" + str(s)


PUBLISHED_CATS = {"FIRST_ATTEMPT", "AFTER_CAS", "AFTER_TRANSPORT", "RECOVERED_408",
                  "RECOVERED_EQUIVALENT"}


def extract_receipts(prefix, log):
    """``(receipts, unreadable, flags, tg_signals)``; receipts = [(ts, doc)] in log order."""
    receipts, unreadable, flags, tg_signals = [], [], Counter(), []
    marker = f"{prefix}_PUBLISH_RECEIPT"
    for line in log.splitlines():
        if "[36;1m" in line:  # echoed script source, not output
            continue
        if marker in line:
            m = RECEIPT.match(line)
            if m and m["prefix"] == prefix:
                try:
                    receipts.append((m["ts"], json.loads(m["doc"])))
                    continue
                except ValueError:
                    pass
            mt = RECEIPT_TS.match(line)
            if mt and re.search(rf"(^|\s){re.escape(marker)}(\s|$)", line):
                unreadable.append((mt["ts"], line[:240]))
            continue
        fm = FLAG.match(line)
        if fm:
            flags[f"{fm[1]}={fm[2]}"] += 1
        elif TG_BLOCK_SIGNAL.search(line) and "::" in line:
            tg_signals.append(line[:240])
    return receipts, unreadable, flags, tg_signals


def window_position(created, finished, published, start, end):
    """Where a run sits relative to the half-open window ``[start, end)``.

    ``published`` (receipt timestamp) wins over ``finished``; ``finished`` is ``None``
    for a run that is still in progress.
    """
    ref = published or finished
    if created >= end:
        return POS_OUTSIDE
    if published is not None and published >= end:
        return POS_PUBLISHED_AFTER
    if created < start:
        if ref is not None and ref < start:
            return POS_OUTSIDE
        return POS_STARTED_BEFORE
    return POS_IN


def analyse_run(run, prefix, log, start, end, log_error=None, now=None, steps=None):
    now = now or datetime.now(timezone.utc)
    created = parse_ts(run["created_at"])
    completed = run.get("status") == "completed"
    finished = parse_ts(run.get("updated_at")) if completed else None
    receipts, unreadable, flags, tg_signals = extract_receipts(prefix, log or "")
    rec_ts, rec = (receipts[-1] if receipts else (None, None))
    published_at = parse_ts(rec_ts) if rec_ts else None
    last_unreadable = unreadable[-1] if unreadable else None
    unreadable_is_last = bool(last_unreadable) and (
        rec_ts is None or parse_ts(last_unreadable[0]) >= parse_ts(rec_ts))

    if not completed or (finished and finished >= end and rec is None):
        evidence = EV_IN_PROGRESS
    elif unreadable_is_last:
        evidence = EV_RECEIPT_UNREADABLE
    elif rec is not None:
        evidence = EV_RECEIPT
    elif log_error:
        evidence = log_error
    else:
        concl = run.get("conclusion")
        evidence = {"success": EV_GREEN_NO_RECEIPT, "cancelled": EV_CANCELLED_NO_RECEIPT,
                    "skipped": "SKIPPED"}.get(concl, EV_FAILED_NO_RECEIPT)
    if evidence == EV_GREEN_NO_RECEIPT and publish_steps_all_skipped(steps):
        evidence = EV_NO_PUBLISH_ATTEMPT
    if evidence == EV_RECEIPT:
        cat = classify(rec)
    elif evidence == EV_NO_PUBLISH_ATTEMPT:
        cat = "NO_PUBLISH_ATTEMPT"
    elif evidence == EV_FAILED_NO_RECEIPT:
        cat = "NO_RECEIPT_WORKFLOW_" + str(run.get("conclusion")).upper()
    elif evidence == "SKIPPED":
        cat = "SKIPPED"
    else:
        cat = "EVIDENCE_GAP"
    position = window_position(created, finished, published_at if evidence == EV_RECEIPT
                               else None, start, end)
    r = rec or {}
    att = r.get("attempt", r.get("attempts"))
    return {
        "run_id": run["id"], "created_at": run["created_at"],
        "run_started_at": run.get("run_started_at"),
        "updated_at": run.get("updated_at"), "completed_at": iso(finished) if finished else None,
        "published_at": iso(published_at) if published_at and evidence == EV_RECEIPT else None,
        "status": run.get("status"), "workflow_conclusion": run.get("conclusion"),
        "event": run.get("event"), "head_sha": run.get("head_sha"),
        "evidence": evidence, "evidence_gap": evidence in GAP_EVIDENCE, "position": position,
        "input_commit": r.get("input_commit") or r.get("base") or r.get("remote_base"),
        "published_commit": r.get("published_commit"),
        "receipt_status": r.get("status"), "category": cat, "attempts": att,
        "cas_retries": r.get("cas_retries", 0),
        "transport_failures": r.get("transport_failures", 0),
        "reason_kind": r.get("reason_kind") or r.get("failure_class"),
        "bundle": r.get("bundle") if cat not in PUBLISHED_CATS else None,
        "provider_requeries": r.get("provider_requeries"),
        "telegram_requests": r.get("telegram_requests"),
        "telegram_receipts_changed": r.get("telegram_receipts_changed"),
        "receipts_in_log": len(receipts), "unreadable_receipts": len(unreadable),
        "flags": dict(flags), "tg_signals": tg_signals[:5],
    }


def in_window(rows):
    """Rows that belong to the window (outside and published-after are excluded)."""
    return [r for r in rows if r["position"] in (POS_IN, POS_STARTED_BEFORE)]


def evidence_gaps(per):
    out = []
    for wf, rows in per.items():
        for r in rows:
            if r["evidence"] == EV_NO_PUBLISH_ATTEMPT and r["position"] != POS_OUTSIDE:
                out.append({"kind": r["evidence"], "workflow": wf, "run_id": r["run_id"],
                            "blocking": False,
                            "detail": "verde, sem recibo; API confirma passos de "
                                      "publicação/recibo todos skipped (sem tentativa de "
                                      "publicação)"})
            elif r["evidence_gap"] and r["position"] != POS_OUTSIDE:
                out.append({"kind": r["evidence"], "workflow": wf, "run_id": r["run_id"],
                            "detail": f"criado {r['created_at']}, workflow "
                                      f"{r['status']}/{r['workflow_conclusion']}"})
    return out


# ----------------------------------------------------------------------------- LAB metrics
def lab_metrics(rows, start, end):
    cycles = [r for r in in_window(rows) if r["category"] not in ("SKIPPED",
                                                                     "NO_PUBLISH_ATTEMPT")]
    pubs = [r for r in cycles if r["category"] in PUBLISHED_CATS]
    sup = [r for r in cycles if r["category"] == "SUPERSEDED"]
    gaps = [r for r in cycles if r["evidence_gap"]]
    streak = best = 0
    streak_start = None
    recoveries = []
    for r in cycles:
        if r["category"] == "SUPERSEDED":
            streak += 1
            best = max(best, streak)
            streak_start = streak_start or r["created_at"]
        elif r["category"] in PUBLISHED_CATS:
            if streak_start:
                recoveries.append((parse_ts(r["published_at"]) - parse_ts(streak_start))
                                  .total_seconds() / 60)
            streak, streak_start = 0, None
        # failures / evidence gaps neither break the streak nor count as publication
    marks = [start] + sorted(parse_ts(r["published_at"]) for r in pubs) + [end]
    gaps_min = [(b - a).total_seconds() / 60 for a, b in zip(marks, marks[1:])]
    max_gap = max(gaps_min) if gaps_min else None
    gap_at, gap_runs = None, []
    if gaps_min:
        i = gaps_min.index(max_gap)
        gap_at = (iso(marks[i]), iso(marks[i + 1]))
        gap_runs = [g["run_id"] for g in gaps
                    if marks[i] <= parse_ts(g["created_at"]) < marks[i + 1]]
    n = len(cycles)
    rate = (len(sup) / n) if n else 0.0
    alerts = []
    if best >= ALERT_STREAK:
        alerts.append(f"{best} supersessões consecutivas (limite {ALERT_STREAK})")
    if max_gap is not None and max_gap > ALERT_GAP_MIN:
        prov = (f"; PROVISÓRIO: {len(gap_runs)} run(s) sem evidência no intervalo {gap_runs[:5]}"
                if gap_runs else "")
        alerts.append(f"{max_gap:.0f} min sem publicação LAB ({gap_at[0]} → {gap_at[1]}; "
                      f"limite {ALERT_GAP_MIN}){prov}")
    if n >= ALERT_RATE_MIN_N and rate > ALERT_RATE:
        alerts.append(f"taxa de supersessão {rate:.0%} em {n} ciclos (limite 25%, n≥8)")
    return {"cycles": n, "published": len(pubs), "superseded": len(sup),
            "evidence_gaps": len(gaps),
            "supersession_rate": round(rate, 4), "max_consecutive_superseded": best,
            "max_minutes_without_publication": round(max_gap, 1) if max_gap is not None else None,
            "max_gap_interval": gap_at, "max_gap_evidence_gap_runs": gap_runs,
            "recovery_minutes": {"count": len(recoveries),
                                 "max": round(max(recoveries), 1) if recoveries else None,
                                 "mean": round(sum(recoveries) / len(recoveries), 1)
                                 if recoveries else None},
            "open_supersession_streak_at_end": streak, "alerts": alerts}


# ----------------------------------------------------------------------------- integrity
def compare_states(prev, cur, where=""):
    """Integrity rules between two snapshots (``prev`` earlier). Returns violations."""
    sfx = f" @ {where}" if where else ""
    problems = []
    if prev.get("results") is not None:
        rh = cur.get("results") or {}
        for k, v in prev["results"].items():
            if rh.get(k) != v:
                problems.append(f"H1 certificado alterado/removido: {k}{sfx}")
    if prev.get("ft") is not None:
        fh = cur.get("ft") or {}
        for k, v in prev["ft"].items():
            h = fh.get(k)
            if h is None:
                problems.append(f"FT jogo removido: {k}{sfx}")
            elif v["status"] == "FINAL" and h != v:
                problems.append(f"FT FINAL alterado: {k}{sfx}")
            elif v["status"] == "EXPIRED_UNVERIFIED" and h["status"] != "EXPIRED_UNVERIFIED":
                problems.append(f"FT expirado reaberto: {k} -> {h['status']}{sfx}")
    for led, b in (prev.get("tg") or {}).items():
        if b is None:
            continue
        h = (cur.get("tg") or {}).get(led) or {}
        for k, v in b.items():
            if k not in h:
                problems.append(f"Recibo Telegram removido: {led} {k}{sfx}")
            elif v.get("status") == "sent" and h[k] != v:
                problems.append(f"Recibo Telegram terminal alterado: {led} {k}{sfx}")
    return problems


def integrity(base, head):
    sys.path.insert(0, str(Path.cwd()))
    from scripts import publication_ownership as own
    problems, notes = [], []
    ledgers = window_ledgers(base, head)
    sb, sh = snapshot(base, ledgers=ledgers), snapshot(head, ledgers=ledgers)
    problems += compare_states(sb, sh)
    tg = {}
    for led in ledgers:
        b, h = sb["tg"].get(led) or {}, sh["tg"].get(led) or {}
        tg[led] = {"base": len(b), "head": len(h),
                   "statuses": dict(Counter(e.get("status") for e in h.values())),
                   "new": sorted(set(h) - set(b))}
    # append-only journals (collector V4 revisions, LAB V6, FT events)
    base_files = git("ls-tree", "-r", "--name-only", base, "data/lab").split()
    head_files = set(git("ls-tree", "-r", "--name-only", head, "data/lab").split())
    checked = 0
    for p in base_files:
        if not own.is_append_only(p):
            continue
        checked += 1
        if p not in head_files:
            notes.append(f"journal ausente na head (verificar repartição/arquivo): {p}")
            continue
        a, b = show(base, p), show(head, p)
        if not b.startswith(a):
            problems.append(f"journal reescrito (não append-only): {p}")
    rb, rh, fb, fh = sb["results"], sh["results"], sb["ft"], sh["ft"]
    return problems, notes, {
        "h1_certified": len(rh), "h1_new": len(set(rh) - set(rb)),
        "ft_status": dict(Counter(m["status"] for m in fh.values())),
        "ft_status_base": dict(Counter(m["status"] for m in fb.values())),
        "telegram": tg, "journals_checked": checked}


def window_commits(base, head):
    """First-parent commits ``base..head`` (oldest first) with files changed vs parent 1."""
    out = git("log", "--first-parent", "--reverse", "--diff-merges=first-parent",
              "--name-only", "--format=__C__%H %P", f"{base}..{head}")
    commits, cur = [], None
    for ln in out.splitlines():
        if ln.startswith("__C__"):
            sha, *parents = ln[5:].split()
            cur = {"sha": sha, "parent": parents[0] if parents else None, "files": []}
            commits.append(cur)
        elif ln.strip() and cur is not None:
            cur["files"].append(ln.strip())
    return commits


def history_integrity(base, head, is_append_only=None, push_time=None):
    """Check every transition ``parent -> commit`` along main's first-parent chain.

    Catches temporary changes later reverted, which a base-vs-head diff cannot see.
    Raises ``EvidenceGap`` when the history is not available locally.
    """
    if is_append_only is None:
        sys.path.insert(0, str(Path.cwd()))
        from scripts.publication_ownership import is_append_only
    if not (has_commit(base) and has_commit(head)):
        raise EvidenceGap("baseline ou head indisponível para a verificação histórica")
    if subprocess.run(["git", "merge-base", "--is-ancestor", base, head],
                      capture_output=True).returncode != 0:
        raise EvidenceGap(f"baseline {base[:12]} não é antecessora da head no clone")
    ledgers = window_ledgers(base, head)
    tg_paths = set(ledgers)
    problems, notes, checked = [], [], 0
    commits = window_commits(base, head)
    for c in commits:
        if c["parent"] is None or not has_commit(c["parent"]):
            raise EvidenceGap(f"pai de {c['sha'][:12]} indisponível (clone raso)")
        files = set(c["files"])
        parts = tuple(k for k, hit in (("results", RESULTS_CSV in files),
                                       ("ft", FT_LEDGER in files),
                                       ("tg", bool(files & tg_paths))) if hit)
        if parts:
            checked += 1
            where = c["sha"][:12] + (f" (push {push_time[c['sha']]})"
                                     if push_time and c["sha"] in push_time else "")
            problems += compare_states(snapshot(c["parent"], parts, ledgers=ledgers),
                                       snapshot(c["sha"], parts, ledgers=ledgers), where=where)
        for p in sorted(files):
            if not is_append_only(p):
                continue
            a = show(c["parent"], p)
            if a is None:
                continue  # journal created in this commit
            b = show(c["sha"], p)
            if b is None:
                notes.append(f"journal removido em {c['sha'][:12]} (repartição/arquivo?): {p}")
            elif not b.startswith(a):
                problems.append(f"journal reescrito (não append-only): {p} @ {c['sha'][:12]}")
    return problems, notes, {"commits_walked": len(commits), "state_transitions_checked": checked}


# ----------------------------------------------------------------------------- push timeline
ALLOWED_PUSH_TYPES = {"push", "pr_merge", "merge_queue_merge"}
CUTOFF_UNDETERMINED = "CUTOFF_UNDETERMINED"


def fetch_push_activity(since, max_pages=200):
    """Server-side ref-update log of ``main`` (newest first), back to ``since``.

    Uses the repository activity API (timestamps recorded by GitHub when the ref moved —
    NOT commit dates).  The ``next`` link points at a numeric-id path the proxy refuses,
    so the cursor is re-applied on the ``repos/{owner}/{repo}`` path.  Raises
    ``EvidenceGap`` if the log cannot be read back to ``since``."""
    out, cursor = [], None
    for _ in range(max_pages):
        q = f"repos/{REPO}/activity?ref=refs%2Fheads%2Fmain&per_page=100&direction=desc"
        if cursor:
            q += "&after=" + urllib.parse.quote(cursor, safe="")
        try:
            data, headers = gh(q, with_headers=True)
        except GhError as exc:
            raise EvidenceGap(f"registo de pushes ilegível: {exc}")
        out += [{"ts": d.get("timestamp"), "type": d.get("activity_type"),
                 "before": d.get("before"), "after": d.get("after")} for d in data]
        if not data or min(d.get("timestamp") or "" for d in data) < iso(since):
            return out
        m = re.search(r'[?&]after=([^&>]+)[^>]*>;\s*rel="next"', headers.get("link", ""))
        if not m:
            raise EvidenceGap(f"registo de pushes termina em {data[-1].get('timestamp')} "
                              f"sem cobrir {iso(since)}")
        cursor = urllib.parse.unquote(m.group(1))
    raise EvidenceGap("registo de pushes demasiado longo (limite de páginas)")


def push_chain(activities, base, head, is_ancestor=None):
    """Ordered ref updates ``base -> ... -> head`` chained by ``before``/``after``.

    Returns ``(steps, problems)``; any problem means the cut-off cannot be trusted.
    Checks: continuity, no ambiguity, only fast-forward types, ``before`` ancestor of
    ``after``, non-decreasing server timestamps, chain reaches ``head``."""
    by_before = {}
    for a in activities:
        by_before.setdefault(a["before"], []).append(a)
    steps, problems, cur, last_ts = [], [], base, None
    while cur != head:
        nxt = by_before.get(cur, [])
        if not nxt:
            problems.append(f"cadeia de pushes interrompida após {cur[:12]} (sem registo do "
                            f"push seguinte)")
            break
        if len({(n["after"], n["ts"]) for n in nxt}) > 1:
            problems.append(f"cadeia ambígua após {cur[:12]}: {len(nxt)} pushes com o mesmo "
                            f"'before'")
            break
        a = nxt[0]
        if a["type"] not in ALLOWED_PUSH_TYPES:
            problems.append(f"atualização não fast-forward ({a['type']}) em {a['ts']}")
            break
        if is_ancestor and not is_ancestor(a["before"], a["after"]):
            problems.append(f"push {a['ts']} não é fast-forward ({a['before'][:12]} ⊄ "
                            f"{a['after'][:12]})")
            break
        ts = parse_ts(a["ts"])
        if last_ts and ts < last_ts:
            problems.append(f"timestamps de push não monótonos em {a['ts']}")
            break
        steps.append({"ts": ts, "before": a["before"], "after": a["after"],
                      "type": a["type"]})
        last_ts, cur = ts, a["after"]
        if len(steps) > 100000:
            problems.append("cadeia de pushes cíclica")
            break
    return steps, problems


def cutoff_commit(steps, base, end):
    """``after`` of the last ref update with server timestamp ``< end`` (half-open)."""
    c = base
    for st in steps:
        if st["ts"] >= end:
            break
        c = st["after"]
    return c


def commits_in(before, after):
    out = git("rev-list", "--first-parent", "--reverse", f"{before}..{after}", check=False)
    return out.split()


def boundary_audit(base, head, activities, end, is_append_only=None, commits_between=None,
                   is_ancestor=None):
    """Snapshot A = transitions pushed in ``[start, end)`` (base -> cut-off);
    snapshot B = transitions pushed at or after ``end`` (cut-off -> head at audit time).

    Attribution uses GitHub's ref-update timestamps, never commit dates.  If the cut-off
    cannot be established from evidence, ``cutoff`` is ``None`` and snapshot A is an
    evidence gap (no invented cut-off)."""
    commits_between = commits_between or commits_in
    is_ancestor = is_ancestor or (lambda a, b: subprocess.run(
        ["git", "merge-base", "--is-ancestor", a, b], capture_output=True).returncode == 0)
    steps, problems = push_chain(activities, base, head, is_ancestor)
    res = {"cutoff": None, "chain_problems": problems, "pushes_total": len(steps),
           "A": None, "B": None, "push_time": {}, "commits_A": [], "commits_B": []}
    if problems:
        return res
    push_time = {}
    for st in steps:
        for sha in commits_between(st["before"], st["after"]):
            push_time[sha] = iso(st["ts"])
    c_end = cutoff_commit(steps, base, end)
    res.update(cutoff=c_end, push_time=push_time,
               pushes_A=sum(1 for st in steps if st["ts"] < end),
               pushes_B=sum(1 for st in steps if st["ts"] >= end),
               cutoff_push_ts=next((iso(st["ts"]) for st in reversed(steps)
                                    if st["after"] == c_end), None),
               first_push_after_end=next((iso(st["ts"]) for st in steps if st["ts"] >= end),
                                         None))
    res["commits_A"] = commits_between(base, c_end) if c_end != base else []
    res["commits_B"] = commits_between(c_end, head) if c_end != head else []
    for label, (a, b) in (("A", (base, c_end)), ("B", (c_end, head))):
        if a == b:
            res[label] = {"problems": [], "notes": [],
                          "summary": {"commits_walked": 0, "state_transitions_checked": 0}}
            continue
        try:
            pr, no, su = history_integrity(a, b, is_append_only=is_append_only,
                                           push_time=push_time)
            res[label] = {"problems": pr, "notes": no, "summary": su}
        except EvidenceGap as exc:
            res[label] = {"problems": [], "notes": [], "gap": str(exc)}
    return res


def attribution_conflicts(rows, push_time, end, in_a):
    """Receipts inside the window whose published commit was pushed at/after ``end``
    (or is not in snapshot A), and vice-versa: never silently re-attributed."""
    out = []
    for wf, rs in rows.items():
        for r in rs:
            pc = r.get("published_commit")
            if not pc or r["category"] not in PUBLISHED_CATS:
                continue
            pt = push_time.get(pc)
            if r["position"] in (POS_IN, POS_STARTED_BEFORE):
                if (pt and parse_ts(pt) >= end) or (pt and pc not in in_a):
                    out.append({"kind": "ATTRIBUTION_CONFLICT", "workflow": wf,
                                "run_id": r["run_id"],
                                "detail": f"recibo {r['published_at']} < fecho, mas push de "
                                          f"{pc[:12]} em {pt}"})
            elif r["position"] == POS_PUBLISHED_AFTER and pc in in_a:
                out.append({"kind": "ATTRIBUTION_CONFLICT", "workflow": wf,
                            "run_id": r["run_id"],
                            "detail": f"recibo {r['published_at']} ≥ fecho, mas {pc[:12]} está "
                                      f"na fotografia A (push {pt})"})
    return out


def verifiers(head):
    """Production readers on a throwaway worktree of ``head``; nothing is committed."""
    out = {}
    tmp = Path(tempfile.mkdtemp(prefix="p0-audit-"))
    wt = tmp / "wt"
    try:
        git("worktree", "add", "--detach", str(wt), head)
        code = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, '.')
res = {}
try:
    from h1lab.v4_revisions import read_events, verify_projection
    res['v4_events'] = len(read_events(Path('.')))
    res['v4_projection'] = bool(verify_projection(Path('.')))
except Exception as e:
    res['v4_error'] = repr(e)[:300]
try:
    from scripts.collect_publish_safe import dashboard_is_coherent
    res['docs_data_json_coherent'] = bool(dashboard_is_coherent(Path('.'), 'HEAD'))
except Exception as e:
    res['docs_data_json_error'] = repr(e)[:300]
try:
    from datetime import datetime, timezone
    from h1lab import lab_archive as la
    now = datetime.now(timezone.utc)
    raw = {'error': None, 'committed': None, 'fresh': None}
    try:
        r = la.build(Path('.'), now, verify_only=True)
        raw['fresh'] = r
    except Exception as e:
        raw['error'] = f'{type(e).__name__}: {e}'[:400]
        if 'replay mismatch' in str(e):
            # build() checks the sealed index BEFORE the derived health report; rebuild the
            # report inside this THROWAWAY worktree only, to compare field by field.
            raw['committed'] = json.loads(Path(la.PUBLIC).read_text(encoding='utf-8'))
            raw['fresh'] = la.build(Path('.'), now, verify_only=False)
    res['archive_raw'] = raw
except Exception as e:
    res['archive_raw'] = {'error': f'READ: {type(e).__name__}: {e}'[:400], 'committed': None,
                          'fresh': None}
try:
    g = json.loads(Path('docs/lab/v6-p0-gates.json').read_text())
    res['scientific_state'] = g.get('scientific_state')
except Exception as e:
    res['scientific_error'] = repr(e)[:200]
print(json.dumps(res))
"""
        r = subprocess.run([sys.executable, "-c", code], cwd=wt, capture_output=True,
                           text=True, timeout=900)
        last = (r.stdout.strip().splitlines() or ["{}"])[-1]
        out = json.loads(last) if last.startswith("{") else {"error": r.stderr[-400:]}
    except Exception as exc:  # pragma: no cover - reported, never fatal
        out = {"error": repr(exc)[:300]}
    finally:
        git("worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
    return out


ARCHIVE_INTACT = "INDICE_SELADO_INTEGRO"
ARCHIVE_STALE = "RELATORIO_SAUDE_DESATUALIZADO"
ARCHIVE_INCONSISTENT = "RELATORIO_SAUDE_INCONSISTENTE"
ARCHIVE_INDEX_INCOMPATIBLE = "INDICE_INCOMPATIVEL"
ARCHIVE_JOURNAL_ALTERED = "JOURNAL_SELADO_ALTERADO"
ARCHIVE_SIZE = "FICHEIRO_LAB_ACIMA_DO_LIMITE"
ARCHIVE_READ_ERROR = "ERRO_LEITURA_EVIDENCIA_INCOMPLETA"
# Derived-report fields that only grow while the LAB appends (staleness signature).
MONOTONE_FIELDS = {"lab_files_checked", "largest_file_bytes", "monthly_parts", "replay"}
# Observed 2026-11-01..02: regeneration interval median 5.1 min, p99 55 min, max 75 min;
# stale episodes median 0.7 min, p99 30 min, max 70.7 min.  Alert above the observed max.
STALE_ALERT_MIN = 90


def _numeric_leaves(x, prefix=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _numeric_leaves(v, f"{prefix}{k}.")
    elif isinstance(x, (int, float)) and not isinstance(x, bool):
        yield prefix.rstrip("."), x


def archive_state(raw):
    """Classify the V6 archive check.  Returns ``(state, detail)``.

    Sealed-index integrity and derived-report freshness are reported separately: a stale
    health report is never corruption, and is never hidden.
    """
    err = (raw or {}).get("error")
    if not raw or (err and err.startswith("READ:")):
        return ARCHIVE_READ_ERROR, err or "sem dados"
    if err is None:
        return ARCHIVE_INTACT, "índice selado em sincronia; relatório de saúde atual"
    if "SEALED_MONTH_MUTATED" in err:
        return ARCHIVE_JOURNAL_ALTERED, err
    if "index version changed" in err or "out of sync" in err:
        return ARCHIVE_INDEX_INCOMPATIBLE, err
    if "LAB_FILE_OVER_20_MB" in err:
        return ARCHIVE_SIZE, err
    if "replay mismatch" in err:
        old, new = raw.get("committed"), raw.get("fresh")
        if not isinstance(old, dict) or not isinstance(new, dict):
            return ARCHIVE_READ_ERROR, "relatório não reconstruído: " + err
        diff = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
        olds, news = dict(_numeric_leaves({k: old.get(k) for k in diff})), \
            dict(_numeric_leaves({k: new.get(k) for k in diff}))
        shrunk = [k for k, v in olds.items() if k not in news or news[k] < v]
        if set(diff) <= MONOTONE_FIELDS and not shrunk:
            grown = {k: (olds.get(k), v) for k, v in news.items() if olds.get(k) != v}
            return ARCHIVE_STALE, ("índice selado em sincronia; relatório derivado atrasado: "
                                   + ", ".join(f"{k} {a}→{b}" for k, (a, b) in
                                               sorted(grown.items())[:8]))
        return ARCHIVE_INCONSISTENT, f"campos divergentes {diff}; diminuíram {shrunk[:8]}"
    return ARCHIVE_READ_ERROR, err


def stale_episodes(commits, report_path="docs/lab/v6-archive-health.json",
                   index_path="data/lab/v6-archive-index.json"):
    """Upper-bound staleness episodes of the derived health report along main.

    ``commits``: oldest-first ``{"t": datetime, "files": [...]}``.  An episode opens at the
    first commit changing ``data/lab/`` (other than the index) after a regeneration and
    closes at the next commit regenerating the report.  Upper bound: not every LAB change
    alters the report.  Returns ``(closed_episodes, open_since)``.
    """
    episodes, dirty = [], None
    for c in commits:
        files = c["files"]
        if report_path in files:
            if dirty is not None:
                episodes.append((dirty, c["t"]))
            dirty = None
        elif dirty is None and any(f.startswith("data/lab/") and f != index_path for f in files):
            dirty = c["t"]
    return episodes, dirty


def archive_freshness(start, end, lab_rows=(), commits=None):
    """``commits``: oldest-first ``{"t": push time, "files": [...]}`` of snapshot A."""
    commits = commits or []
    eps, open_since = stale_episodes(commits)
    durs = sorted(((b - a).total_seconds() / 60, a, b) for a, b in eps if b >= start)
    longest = durs[-1] if durs else None
    open_min = (end - open_since).total_seconds() / 60 if open_since else None
    regen = [c["t"] for c in commits if "docs/lab/v6-archive-health.json" in c["files"]
             and c["t"] >= start]
    cyc = 0
    if longest:
        cyc = sum(1 for r in lab_rows if longest[1] <= parse_ts(r["created_at"]) < longest[2])
    alerts = []
    if longest and longest[0] > STALE_ALERT_MIN:
        alerts.append(f"relatório de saúde desatualizado {longest[0]:.0f} min "
                      f"({iso(longest[1])} → {iso(longest[2])}; {cyc} ciclos LAB; limite "
                      f"{STALE_ALERT_MIN} min)")
    if open_min is not None and open_min > STALE_ALERT_MIN:
        alerts.append(f"relatório de saúde desatualizado há {open_min:.0f} min no fecho "
                      f"(desde {iso(open_since)}; limite {STALE_ALERT_MIN} min)")
    return {"regenerations_in_window": len(regen), "episodes": len(durs),
            "max_episode_min": round(longest[0], 1) if longest else None,
            "max_episode": (iso(longest[1]), iso(longest[2])) if longest else None,
            "lab_cycles_in_max_episode": cyc,
            "p50_episode_min": round(durs[len(durs) // 2][0], 1) if durs else None,
            "open_at_close_min": round(open_min, 1) if open_min is not None else None,
            "threshold_min": STALE_ALERT_MIN, "alerts": alerts}


def main_commits(shas):
    """Ownership summary of the given first-parent commits (snapshot A)."""
    sys.path.insert(0, str(Path.cwd()))
    from scripts.publication_ownership import owner_of
    out = []
    for sha in shas:
        ln = git("log", "-1", "--format=%H%x09%P%x09%an%x09%s", sha).strip()
        sha, parents, author, subject = ln.split("\t", 3)
        if len(parents.split()) > 1:
            out.append({"sha": sha, "merge": True, "author": author, "subject": subject})
            continue
        files = git("diff-tree", "--no-commit-id", "--name-only", "-r", sha).split()
        owners = sorted({str(owner_of(f)) for f in files})
        out.append({"sha": sha, "merge": False, "author": author, "subject": subject,
                    "owners": owners, "files": len(files),
                    "tg_block": "data/telegram-delivery-block.json" in files})
    return out


def published_commit_check(per, ref="origin/main"):
    """``(missing_from_main, unverifiable)`` for commits named in PUBLISHED receipts."""
    published = {r["published_commit"] for rows in per.values() for r in in_window(rows)
                 if r["published_commit"] and r["category"] in PUBLISHED_CATS}
    missing, unverifiable = [], []
    for p in sorted(published):
        if not has_commit(p):
            unverifiable.append(p)
        elif subprocess.run(["git", "merge-base", "--is-ancestor", p, ref],
                            capture_output=True).returncode != 0:
            missing.append(p)
    return missing, unverifiable


def pages_state(head):
    st = {"bytes": "NOT VERIFIED"}
    try:
        b = gh(f"repos/{REPO}/pages/builds/latest")
        st.update(build_status=b.get("status"), build_commit=b.get("commit"),
                  build_at=b.get("updated_at"))
    except GhError as exc:
        st["build_error"] = str(exc)[:200]
    try:
        r = subprocess.run(["curl", "-fsS", "--max-time", "20",
                            f"https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/data.json"],
                           capture_output=True)
        if r.returncode == 0:
            served = json.loads(r.stdout)
            main_view = json.loads(show(head, "docs/data.json"))
            st["bytes"] = ("MATCH_MAIN_HEAD" if served == main_view else
                           f"DIFFERS_FROM_MAIN_HEAD (served generated_at={served.get('generated_at')})")
        else:
            st["bytes_error"] = r.stderr.decode()[:160]
    except Exception as exc:
        st["bytes_error"] = repr(exc)[:160]
    return st


# ----------------------------------------------------------------------------- report
def render(label, start, end, complete, per, lab, integ, hist, verif, commits, pages, flags,
           tg_sig, head, baseline_problems, gaps, missing, unverifiable):
    L = []
    L.append(f"<!-- MASTER_BRAIN_P0_AUDIT:{label} -->")
    L.append(f"## MASTER BRAIN — AUDITORIA P0 {label} (leitura apenas · auditor V5)")
    L.append(f"Período (semiaberto): **[{iso(start)}, {iso(end)})** · "
             f"{'janela completa' if complete else '**JANELA INCOMPLETA**'} · fecho "
             f"`{(head or 'INDETERMINADO')[:12]}`")
    L.append("Estado científico #63: INCONCLUSIVO (não alterado por esta auditoria). "
             "Workflow verde ≠ publicação confirmada: só o recibo conta, datado pela linha do "
             "recibo (não pelo início nem pela conclusão do run).")
    L.append("")
    L.append("### 1. Publicadores")
    L.append("| Publicador | Execuções | Publicações efetivas | 1.ª tentativa | após CAS | após 408 | "
             "recuperado (408/equivalente) | superadas | recusas integridade | falhas não recuperadas | "
             "nada a publicar (recibo / passos skipped) | sem evidência | taxa sucesso* | publicadas após a janela |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for wf, (name, _) in PUBLISHERS.items():
        all_rows = per[wf]
        rows = in_window(all_rows)
        c = Counter(r["category"] for r in rows)
        eff = sum(c[k] for k in PUBLISHED_CATS)
        failed_norec = sum(v for k, v in c.items() if k.startswith("NO_RECEIPT"))
        uncl = sum(v for k, v in c.items() if k.startswith("UNCLASSIFIED"))
        gap = c["EVIDENCE_GAP"]
        after = sum(1 for r in all_rows if r["position"] == POS_PUBLISHED_AFTER)
        attempted = eff + c["UNRECOVERED_FAILURE"] + c["INTEGRITY_REFUSAL"] + failed_norec + uncl
        rate = f"{eff / attempted:.1%}" if attempted else "—"
        extra = f" (+{uncl} não classif.)" if uncl else ""
        L.append(f"| {name} | {len(rows)} | {eff} | {c['FIRST_ATTEMPT']} | {c['AFTER_CAS']} | "
                 f"{c['AFTER_TRANSPORT']} | {c['RECOVERED_408'] + c['RECOVERED_EQUIVALENT']} | "
                 f"{c['SUPERSEDED']} | {c['INTEGRITY_REFUSAL']} | "
                 f"{c['UNRECOVERED_FAILURE'] + failed_norec}{extra} | "
                 f"{c['NOTHING_TO_PUBLISH']} / {c['NO_PUBLISH_ATTEMPT']} | {gap} | {rate}{' (provisória)' if gap else ''} | "
                 f"{after} |")
    L.append("\\* publicações efetivas ÷ (efetivas + recusas + falhas); supersessões, "
             "'nada a publicar' e runs sem evidência excluídos do denominador. "
             "'Sem evidência' = verde sem recibo, logs indisponíveis, erro da API, recibo "
             "ilegível, cancelado sem recibo ou em curso no fecho.")
    prov = sum(1 for rows in per.values() for r in in_window(rows)
               if (r["provider_requeries"] or 0) > 0)
    L.append(f"Consultas repetidas a fornecedores comprovadas nos recibos: **{prov}**.")
    inc = [(PUBLISHERS[wf][0], r) for wf, rows in per.items() for r in in_window(rows)
           if not r["evidence_gap"] and (
               r["category"] not in PUBLISHED_CATS | {"NOTHING_TO_PUBLISH", "SUPERSEDED",
                                                      "SKIPPED", "NO_PUBLISH_ATTEMPT"}
               or r["category"] in ("AFTER_CAS", "AFTER_TRANSPORT", "RECOVERED_408",
                                    "RECOVERED_EQUIVALENT"))]
    L.append("")
    L.append(f"### 2. Falhas e recuperações (todas visíveis): {len(inc)}")
    if inc:
        L.append("| Publicador | Run | Criado | Publicado | Workflow | Recibo | Categoria | Tent. | "
                 "CAS | 408 | Entrada | Commit | Motivo | Bundle |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for name, r in inc[:60]:
            L.append(f"| {name} | {r['run_id']} | {r['created_at']} | {r['published_at'] or ''} | "
                     f"{r['workflow_conclusion']} | {r['receipt_status']} | {r['category']} | "
                     f"{r['attempts']} | {r['cas_retries']} | {r['transport_failures']} | "
                     f"`{(r['input_commit'] or '')[:8]}` | `{(r['published_commit'] or '')[:8]}` | "
                     f"{r['reason_kind'] or ''} | {'sim' if r['bundle'] else ''} |")
        if len(inc) > 60:
            L.append(f"(+{len(inc) - 60} no JSON anexo do executor)")
    L.append("")
    L.append(f"### 3. Lacunas de evidência: {len(gaps)}")
    if gaps:
        L.append("Lacunas de observabilidade — **não** são incidentes de corrupção nem provas de "
                 "publicação. As bloqueantes impedem uma conclusão de estabilidade "
                 "(INCONCLUSIVO_OPERACIONAL); as informativas ficam registadas.")
        L.append("| Tipo | Bloqueante | Workflow | Run | Detalhe |")
        L.append("|---|---|---|---|---|")
        for g in gaps[:60]:
            L.append(f"| {g['kind']} | {'sim' if g.get('blocking', True) else 'não'} | "
                     f"{g['workflow']} | {g['run_id'] or '—'} | {str(g['detail'])[:160]} |")
        if len(gaps) > 60:
            L.append(f"(+{len(gaps) - 60} no JSON anexo do executor)")
    L.append("")
    L.append("### 4. Supersessão / starvation LAB V4")
    L.append(f"Ciclos: **{lab['cycles']}** · publicações efetivas: **{lab['published']}** · "
             f"superados: **{lab['superseded']}** · sem evidência: **{lab['evidence_gaps']}** · "
             f"taxa: **{lab['supersession_rate']:.1%}** · "
             f"maior sequência consecutiva: **{lab['max_consecutive_superseded']}** · "
             f"tempo máximo sem publicação: **{lab['max_minutes_without_publication']} min** "
             f"({lab['max_gap_interval']}) · recuperação após supersessão: "
             f"n={lab['recovery_minutes']['count']}, máx {lab['recovery_minutes']['max']} min, "
             f"média {lab['recovery_minutes']['mean']} min · sequência aberta no fim: "
             f"{lab['open_supersession_streak_at_end']}.")
    if lab["alerts"]:
        L.append("**ALERTA OPERACIONAL (gatilho de investigação, não prova de falha científica):** "
                 + "; ".join(lab["alerts"]))
    else:
        L.append("Sem gatilhos de alerta (3 consecutivas / >30 min / >25% com n≥8).")
    L.append("")
    L.append("### 5. Integridade")
    probs, notes, s = integ
    bc = BASELINE_COUNTS
    L.append(f"- Baseline `{BASELINE_COMMIT[:12]}` (main no início da janela, {WINDOW_START}): "
             f"FT {bc['ft']}, H1 {bc['h1_certified']}, Telegram {bc['telegram_sent']} `sent` — "
             + ("**verificada** contra o objeto Git." if not baseline_problems else
                "**FALHOU a verificação**: " + "; ".join(baseline_problems)))
    L.append(f"- **Fotografia A — fecho da janela** (`{(head or 'INDETERMINADO')[:12]}`, "
             f"último push < fim): H1 "
             f"certificados **{s['h1_certified']}** (+{s['h1_new']} novos); FT {s['ft_status']}.")
    L.append(f"- Journals append-only verificados (baseline→fecho): {s['journals_checked']}.")
    if hist.get("gap"):
        L.append(f"- Verificação histórica commit a commit: **NÃO EXECUTADA** ({hist['gap']}) — "
                 "lacuna de evidência.")
    else:
        L.append(f"- Verificação histórica commit a commit (baseline→fecho; atribuição pela hora "
                 f"de push registada pelo GitHub, não pela data do commit): "
                 f"{hist['summary']['commits_walked']} commits, "
                 f"{hist['summary']['state_transitions_checked']} transições de estado FT/H1/"
                 f"Telegram verificadas; violações transitórias: **{len(hist['problems'])}**.")
    L.append(f"- Leitores de produção: V4 eventos={verif.get('v4_events')}, projeção="
             f"{verif.get('v4_projection', verif.get('v4_error'))}; `docs/data.json` coerente="
             f"{verif.get('docs_data_json_coherent', verif.get('docs_data_json_error'))}; arquivo V6: "
             f"ver secção 9; estado científico="
             f"{verif.get('scientific_state', verif.get('scientific_error'))}.")
    mixed = [c for c in commits if not c["merge"] and len(c.get("owners", [])) > 1]
    prog = [c for c in commits if not c["merge"] and "PROGRAM" in c.get("owners", [])]
    unk = [c for c in commits if not c["merge"] and "None" in c.get("owners", [])]
    L.append(f"- Commits publicados na main no período (pela hora de push): {len(commits)} (merges {sum(c['merge'] for c in commits)}); "
             f"multi-dono: {len(mixed)}; programa: {len(prog)}; caminho desconhecido: {len(unk)}; "
             f"commits com recibo PUBLISHED ausentes da main: {len(missing)}"
             + (f"; não verificáveis (objeto ausente no clone): {len(unverifiable)}"
                if unverifiable else "") + ".")
    for c in (prog + unk)[:10]:
        L.append(f"  - `{c['sha'][:8]}` {c['author']}: {c['subject'][:90]} {c.get('owners')}")
    if mixed:
        L.append("  - multi-dono (revisão manual; H1 re-renderiza `docs/data.json`): "
                 + ", ".join(f"`{c['sha'][:8]}` {c.get('owners')}" for c in mixed[:8]))
    all_probs = probs + hist.get("problems", [])
    L.append(f"- **Violações de integridade: {len(all_probs)}**")
    for p in all_probs[:30]:
        L.append(f"  - {p}")
    for n in (notes + hist.get("notes", []))[:10]:
        L.append(f"  - nota: {n}")
    L.append("")
    L.append("### 6. Telegram")
    L.append(f"- Modos efetivos nos logs do coletor: {dict(flags)}")
    for led, t in s["telegram"].items():
        L.append(f"- `{led}`: {t['base']} → {t['head']} {t['statuses']} novos={len(t['new'])}")
    blk = [c for c in commits if c.get("tg_block")]
    L.append(f"- Commits a `data/telegram-delivery-block.json` no período: {len(blk)} "
             f"(persistência de bloqueio {'exercitada' if blk else 'não exercitada'}).")
    L.append(f"- Sinais 429/401/403 nos logs: {len(tg_sig)}" +
             ("".join(f"\n  - `{x}`" for x in tg_sig[:5])))
    L.append("- Exactly-once **não** é afirmado (AT-LEAST-ONCE com modo durável desligado).")
    L.append("")
    L.append("### 7. Pages")
    L.append(f"- {pages}")
    L.append("")
    return L, all_probs, mixed, prog, unk


def coverage_summary(per, coverage, outside=None):
    """Per workflow: API-expected runs vs listed vs classified (no silent exclusion)."""
    out = []
    for wf, (name, _) in PUBLISHERS.items():
        segs = [c for c in coverage if c["workflow"] == wf]
        rows = per.get(wf, [])
        ev = Counter(r["evidence"] for r in in_window(rows))
        before = sum(c.get("finished_before_window", 0) for c in segs)
        out_r = (outside or {}).get(wf, 0)
        after = sum(1 for r in rows if r["position"] == POS_PUBLISHED_AFTER)
        retrieved = sum(c["retrieved"] for c in segs)
        out.append({"workflow": wf, "name": name, "segments": len(segs),
                    "segments_complete": sum(c["complete"] for c in segs),
                    "expected": sum(c["expected"] or 0 for c in segs),
                    "retrieved": sum(c["retrieved"] for c in segs),
                    "finished_before_window": sum(c.get("finished_before_window", 0)
                                                  for c in segs),
                    "in_window": len(in_window(rows)),
                    "with_receipt": ev[EV_RECEIPT],
                    "without_full_evidence": sum(v for k, v in ev.items() if k in GAP_EVIDENCE),
                    "outside_by_receipt": out_r, "published_after_window": after,
                    "identity_ok": retrieved == before + out_r + len(in_window(rows)) + after,
                    "evidence": dict(ev)})
    return out


def render_boundary(b, end, head, integ_b, verif_b):
    L = ["### 8. Fronteira temporal — fotografias A e B"]
    if b["cutoff"] is None:
        L.append("- **Fecho da janela INDETERMINADO** — "
                 + "; ".join(b["chain_problems"])[:400]
                 + ". A fotografia A não foi verificada (INCONCLUSIVO_OPERACIONAL); não foi "
                   "inventado nenhum ponto de corte.")
    else:
        L.append(f"- Fecho: `{b['cutoff'][:12]}` = último push com hora de servidor < "
                 f"{iso(end)} (push às {b.get('cutoff_push_ts') or 'baseline'}); primeiro "
                 f"push ≥ fecho: {b.get('first_push_after_end') or 'nenhum'}. Cadeia de "
                 f"{b['pushes_total']} pushes contínua desde a baseline (A: "
                 f"{b.get('pushes_A')}, B: {b.get('pushes_B')}). Fonte: registo de atividade "
                 f"do GitHub (não a data dos commits).")
        hb = b.get("B") or {}
        nb = len(hb.get("problems", []))
        L.append(f"- **Fotografia B — main na auditoria** (`{head[:12]}`): "
                 f"{len(b['commits_B'])} commits publicados após o fecho; "
                 + (f"verificação NÃO executada ({hb['gap']})" if hb.get("gap") else
                    f"violações posteriores ao fecho: **{nb}**")
                 + " — fora dos indicadores e do veredito desta janela.")
        for pr in hb.get("problems", [])[:15]:
            L.append(f"  - pós-fecho: {pr}")
        if nb:
            L.append("  - **ALERTA PÓS-FECHO**: violações publicadas depois do fecho; pertencem "
                     "à janela seguinte e exigem investigação imediata.")
    s = integ_b[2]
    L.append(f"- Estado na auditoria: H1 {s['h1_certified']}; FT {s['ft_status']}; projeção V4 "
             f"{verif_b.get('v4_projection', verif_b.get('v4_error'))}; `docs/data.json` "
             f"coerente {verif_b.get('docs_data_json_coherent', verif_b.get('docs_data_json_error'))}.")
    L.append("")
    return L


def render_extra(archive, fresh, cov_rows, coverage, budget, rate_before, fresh_ok, head,
                 remote_head):
    L = ["### 9. Arquivo V6 (índice selado ≠ relatório derivado)"]
    L.append(f"- Estado: **{archive[0]}** — {archive[1]}")
    L.append(f"- Frescura do relatório de saúde na janela (limite superior via Git): "
             f"{fresh['regenerations_in_window']} regenerações; {fresh['episodes']} episódios "
             f"desatualizados; mediana {fresh['p50_episode_min']} min; máximo "
             f"{fresh['max_episode_min']} min {fresh['max_episode']} "
             f"({fresh['lab_cycles_in_max_episode']} ciclos LAB); aberto no fecho: "
             f"{fresh['open_at_close_min']} min; limite de alerta {fresh['threshold_min']} min.")
    if fresh["alerts"]:
        L.append("- **ALERTA DE ATUALIZAÇÃO (não é corrupção):** " + "; ".join(fresh["alerts"]))
    L.append("")
    L.append("### 10. Cobertura e orçamento da API")
    L.append("| Publicador | Segmentos completos | Esperados (API) | Obtidos | Terminados antes "
             "do início (lookback, metadados) | Na janela | Com recibo | Sem evidência completa |")
    L.append("|---|---|---|---|---|---|---|---|")
    for c in cov_rows:
        L.append(f"| {c['name']} | {c['segments_complete']}/{c['segments']} | {c['expected']} | "
                 f"{c['retrieved']} | {c['finished_before_window']} | {c['in_window']} | {c['with_receipt']} | "
                 f"{c['without_full_evidence']} |")
    bad = [c for c in coverage if not c["complete"]]
    L.append("- Cobertura integral demonstrada (total_count = obtidos em todos os segmentos)."
             if not bad else "- **Segmentos incompletos:** " + "; ".join(
                 f"{c['workflow']} {c['from']}..{c['to']} ({c['retrieved']}/{c['expected']})"
                 for c in bad[:10]))
    L.append(f"- API: {budget['calls']} pedidos, {budget['errors']} erros, limite "
             f"{budget['limit']}/h, mínimo restante {budget['remaining_min']}, espera por "
             f"limites {budget['waited_seconds']} s"
             f"{' — ORÇAMENTO ESGOTADO' if budget['exhausted'] else ''}; ritmo máx. "
             f"{budget['rps_cap']} pedidos/s. Início: {rate_before}.")
    L.append(f"- Head auditada `{head[:12]}` "
             + ("= main remota." if fresh_ok else f"**≠ main remota `{(remote_head or '?')[:12]}`**."))
    L.append("")
    return L


def classification(per, lab, probs, verif, complete, missing, tg_flags, gaps,
                   baseline_problems=(), archive=None, freshness_alerts=()):
    """Operational verdict.  Evidence gaps never become corruption incidents and never
    allow "no incidents": they yield ``INCONCLUSIVO_OPERACIONAL``."""
    rows = [r for rs in per.values() for r in in_window(rs)]
    unrec = sum(1 for r in rows if r["category"] == "UNRECOVERED_FAILURE")
    refus = sum(1 for r in rows if r["category"] == "INTEGRITY_REFUSAL")
    failed_norec = sum(1 for r in rows if r["category"].startswith("NO_RECEIPT"))
    uncl = sum(1 for r in rows if r["category"].startswith("UNCLASSIFIED"))
    verif_gap = [k for k in verif if k.endswith("_error") or k == "error"]
    a_state, a_detail = archive or (None, None)
    if a_state in (ARCHIVE_INCONSISTENT, ARCHIVE_READ_ERROR) and not any(
            g["kind"] == f"ARCHIVE_{a_state}" for g in gaps):
        gaps = list(gaps) + [{"kind": f"ARCHIVE_{a_state}", "workflow": "-", "run_id": None,
                              "detail": a_detail}]
    verif_gaps = [{"kind": "VERIFIER_ERROR", "workflow": "-", "run_id": None,
                   "detail": f"{k}: {verif[k]}"} for k in verif_gap]
    gap_list = list(gaps) + verif_gaps
    blocking = [g for g in gap_list if g.get("blocking", True)]
    if baseline_problems:
        g = {"kind": "BASELINE_INVALID", "workflow": "-", "run_id": None,
             "detail": "; ".join(baseline_problems)}
        gap_list.append(g)
        blocking.append(g)
    if probs or missing or verif.get("docs_data_json_coherent") is False \
            or verif.get("v4_projection") is False or a_state == ARCHIVE_JOURNAL_ALTERED:
        level = "CRÍTICO — violação de integridade verificada"
    elif unrec or failed_norec or lab["alerts"] or any(k.endswith("=1") for k in tg_flags) \
            or a_state in (ARCHIVE_INDEX_INCOMPATIBLE, ARCHIVE_SIZE) or freshness_alerts:
        level = "DEGRADADO — incidentes operacionais a investigar"
    elif refus or uncl:
        level = "DEGRADADO (ligeiro) — recusas seguras ou recibos não classificados"
    elif blocking:
        level = "INCONCLUSIVO_OPERACIONAL — lacunas de evidência impedem concluir"
    else:
        level = "SEM INCIDENTES NÃO RECUPERADOS NA JANELA"
    if blocking and not level.startswith("INCONCLUSIVO"):
        level += " + INCONCLUSIVO_OPERACIONAL (lacunas de evidência)"
    reasons = [f"falhas não recuperadas={unrec}, falhas sem recibo={failed_norec}, "
               f"recusas={refus}, alertas LAB={len(lab['alerts'])}, violações={len(probs)}, "
               f"arquivo V6={a_state}, alertas de atualização={len(freshness_alerts)}, "
               f"lacunas de evidência bloqueantes={len(blocking)}, "
               f"informativas={len(gap_list) - len(blocking)}"]
    affected = [str(g["run_id"]) for g in blocking if g.get("run_id")]
    if affected:
        reasons.append("runs sem evidência: " + ", ".join(affected[:15])
                       + (f" (+{len(affected) - 15})" if len(affected) > 15 else ""))
    if not complete:
        reasons.append("janela incompleta")
    return level, reasons, gap_list


def ensure_history(start):
    # History must reach back before the window start AND contain the baseline/merge
    # commits; never use a shallow --depth=1 fetch here (it would cut history short).
    git("fetch", "-q", f"--shallow-since={iso(start - timedelta(days=1))}", "origin",
        "main:refs/remotes/origin/main", check=False)
    depth = 500
    while depth <= 20000 and not all(has_commit(c) for c in (BASELINE_COMMIT, MERGE_206)):
        git("fetch", "-q", f"--depth={depth}", "origin", "main:refs/remotes/origin/main",
            check=False)
        depth *= 4
    first = git("rev-list", "--max-parents=0", "origin/main", check=False).split()
    if first:
        t0 = git("log", "-1", "--format=%cI", first[0]).strip()
        if t0 and parse_ts(t0) > start:
            raise SystemExit(f"history does not reach window start ({t0}); deepen the clone")


def head_is_fresh(attempts=3):
    """``(ok, local, remote)``: local ``origin/main`` equals the remote main.

    A failed fetch must not let the audit run silently on a stale head; main moves every
    few minutes, so a mismatch is retried with a fresh fetch."""
    local = remote = None
    for _ in range(attempts):
        remote = (git("ls-remote", "origin", "refs/heads/main", check=False).split() or [None])[0]
        local = git("rev-parse", "origin/main", check=False).strip()
        if remote and remote == local:
            return True, local, remote
        git("fetch", "-q", "origin", "main:refs/remotes/origin/main", check=False)
    return False, local, remote


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--start", default=WINDOW_START)
    ap.add_argument("--hours", type=float, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--cache", type=Path, default=Path(tempfile.gettempdir()) / "p0-audit-cache")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    start, end, complete = window_bounds(parse_ts(a.start), a.hours, now)
    a.cache.mkdir(parents=True, exist_ok=True)
    ensure_history(start)
    fresh_ok, head, remote_head = head_is_fresh()
    try:
        rate_before = gh("rate_limit")["resources"]["core"]
    except GhError as exc:
        rate_before = {"error": str(exc)[:200]}

    try:
        baseline_problems = verify_baseline(BASELINE_COMMIT, start)
    except EvidenceGap as exc:
        baseline_problems = [f"baseline não verificável: {exc}"]

    per, flags, tg_sig, api_gaps, coverage, outside = {}, Counter(), [], [], [], {}
    for wf, (name, prefix) in PUBLISHERS.items():
        runs = list_runs(wf, start, end, api_gaps, coverage)
        before = [r for r in runs if r["status"] == "completed"
                  and parse_ts(r["created_at"]) < start and parse_ts(r["updated_at"]) < start]
        skip = {r["id"] for r in before}
        for c in coverage:
            if c["workflow"] == wf:
                c["finished_before_window"] = sum(
                    1 for r in before if c["from"] <= r["created_at"] < c["to"])
        runs = [r for r in runs if r["id"] not in skip]
        done = [r for r in runs if r["status"] == "completed"]
        with cf.ThreadPoolExecutor(6) as ex:
            logs = dict(zip([r["id"] for r in done], ex.map(lambda r: run_logs(r, a.cache), done)))
        rows = []
        for r in runs:
            text, err, steps = logs.get(r["id"], ("", None, None))
            rows.append(analyse_run(r, prefix, text, start, end, log_error=err, now=now,
                                    steps=steps))
        outside[wf] = sum(1 for r in rows if r["position"] == POS_OUTSIDE)
        rows = [r for r in rows if r["position"] != POS_OUTSIDE]
        per[wf] = rows
        if wf == "collect.yml":
            for r in in_window(rows):
                flags.update(r["flags"])
        for r in in_window(rows):
            tg_sig += r["tg_signals"]
        print(f"{name}: {len(rows)} runs; API {BUDGET.calls} pedidos, restante "
              f"{BUDGET.remaining}", file=sys.stderr, flush=True)
    gaps = api_gaps + evidence_gaps(per)
    if not fresh_ok:
        gaps.append({"kind": "HEAD_NOT_CURRENT", "workflow": "-", "run_id": None,
                     "detail": f"origin/main local {head} ≠ remoto {remote_head}"})
    lab = lab_metrics(per["lab-v4-audit.yml"], start, end)
    # --- temporal boundary: snapshot A (pushed before end) vs B (pushed at/after end)
    try:
        activities = fetch_push_activity(start - timedelta(hours=1))
        boundary = boundary_audit(BASELINE_COMMIT, head, activities, end)
    except EvidenceGap as exc:
        boundary = {"cutoff": None, "chain_problems": [str(exc)], "A": None, "B": None,
                    "push_time": {}, "commits_A": [], "commits_B": []}
    c_end = boundary["cutoff"]
    if c_end is None:
        gaps.append({"kind": CUTOFF_UNDETERMINED, "workflow": "-", "run_id": None,
                     "detail": "commit de fecho não determinável com evidência: "
                               + "; ".join(boundary["chain_problems"])[:300]})
        hist = {"problems": [], "notes": [], "gap": "fecho da janela indeterminado"}
        integ = ([], [], integrity(BASELINE_COMMIT, head)[2])
        integ[2]["note"] = "contagens da main na auditoria (fecho indeterminado)"
    else:
        hist = boundary["A"]
        if hist.get("gap"):
            gaps.append({"kind": "HISTORY_UNAVAILABLE", "workflow": "-", "run_id": None,
                         "detail": hist["gap"]})
        integ = integrity(BASELINE_COMMIT, c_end)
        gaps += attribution_conflicts(per, boundary["push_time"], end,
                                      set(boundary["commits_A"]))
    integ_b = integrity(BASELINE_COMMIT, head)
    verif = verifiers(c_end or head)
    verif_b = verifiers(head) if c_end and c_end != head else verif
    commits = main_commits(boundary["commits_A"])
    pages = pages_state(head)
    archive = archive_state(verif.get("archive_raw"))
    pt = boundary["push_time"]
    a_commits = [{"t": parse_ts(pt[c["sha"]]), "files": c["files"]}
                 for c in (window_commits(BASELINE_COMMIT, c_end) if c_end else [])
                 if c["sha"] in pt]
    fresh = archive_freshness(start, end, per["lab-v4-audit.yml"], a_commits)
    if archive[0] in (ARCHIVE_INCONSISTENT, ARCHIVE_READ_ERROR):
        gaps.append({"kind": f"ARCHIVE_{archive[0]}", "workflow": "-", "run_id": None,
                     "detail": archive[1]})
    if archive[0] == ARCHIVE_STALE:
        gaps.append({"kind": "ARCHIVE_HEALTH_REPORT_STALE", "workflow": "-", "run_id": None,
                     "blocking": False, "detail": archive[1]})
    if pages.get("bytes") == "NOT VERIFIED":
        gaps.append({"kind": "PAGES_NOT_VERIFIED", "workflow": "-", "run_id": None,
                     "blocking": False,
                     "detail": "bytes servidos não obtidos (informativo; não bloqueia o "
                               "veredito dos publicadores)"})
    missing, unverifiable = published_commit_check(per, c_end or head)
    for p in unverifiable:
        gaps.append({"kind": "PUBLISHED_COMMIT_UNVERIFIABLE", "workflow": "-", "run_id": None,
                     "detail": p})
    L, probs, mixed, prog, unk = render(a.label, start, end, complete, per, lab, integ, hist,
                                        verif, commits, pages, flags, tg_sig, c_end,
                                        baseline_problems, gaps, missing, unverifiable)
    level, reasons, gap_list = classification(per, lab, probs, verif, complete, missing, flags,
                                              gaps, baseline_problems, archive, fresh["alerts"])
    cov_rows = coverage_summary(per, coverage, outside)
    for c in cov_rows:
        if not c["identity_ok"]:
            gap_list.append({"kind": "COVERAGE_IDENTITY_FAILED", "workflow": c["workflow"],
                             "run_id": None, "detail": str(c)})
            level = ("INCONCLUSIVO_OPERACIONAL — contabilidade de cobertura não fecha"
                     if not level.startswith(("CRÍTICO", "DEGRADADO")) else
                     level + " + INCONCLUSIVO_OPERACIONAL (cobertura)")
    L += render_boundary(boundary, end, head, integ_b, verif_b)
    L += render_extra(archive, fresh, cov_rows, coverage, BUDGET.summary(), rate_before,
                      fresh_ok, head, remote_head)
    L.append("### 11. Bloqueios P0 e classificação")
    L.append(f"- Classificação operacional: **{level}** ({'; '.join(reasons)}).")
    L.append("- Bloqueios P0 conhecidos mantidos: Telegram AT-LEAST-ONCE (modo durável desligado; "
             "crash entre envio e publicação sem diagnóstico); recusas FT conhecidas sobre nova "
             "geração do índice de arquivo/partições.")
    L.append("- CI verde não é usado como prova de estabilidade. #107 permanece **OPEN**; "
             "o fecho exige avaliação explícita. #204 isolada; #63 INCONCLUSIVO.")
    a.out.write_text("\n".join(L) + "\n", encoding="utf-8")
    if a.json:
        a.json.write_text(json.dumps({"label": a.label, "start": iso(start), "end": iso(end),
                                      "complete": complete, "head": head,
                                      "baseline": {"commit": BASELINE_COMMIT,
                                                   "expected": BASELINE_COUNTS,
                                                   "problems": baseline_problems},
                                      "lab": lab, "runs": per, "evidence_gaps": gap_list,
                                      "integrity": {"problems": probs, "summary": integ[2],
                                                    "notes": integ[1], "history": hist},
                                      "verifiers": verif, "pages": pages,
                                      "boundary": {k: v for k, v in boundary.items()
                                                   if k != "push_time"},
                                      "snapshot_B": {"head": head, "summary": integ_b[2],
                                                     "state_problems": integ_b[0],
                                                     "verifiers": verif_b},
                                      "github_rate_limit_at_start": rate_before,
                                      "api_budget": BUDGET.summary(),
                                      "coverage": {"segments": coverage, "per_workflow": cov_rows},
                                      "archive": {"state": archive[0], "detail": archive[1],
                                                  "freshness": fresh},
                                      "head_fresh": {"ok": fresh_ok, "local": head,
                                                     "remote": remote_head},
                                      "classification": level}, indent=1, default=str),
                          encoding="utf-8")
    print(level)
    return 0


if __name__ == "__main__":
    sys.exit(main())

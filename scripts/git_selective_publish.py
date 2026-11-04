"""Shared selective, concurrency-safe Git publisher (no rebase, no force push, no provider calls).

Generalises the mechanism proven by the FT (#202) and H1 (#203) publishers so
that every producer that writes ``main`` uses ONE transport and ONE push-outcome
machine, while each producer keeps its own integrity rules in a ``Policy``.

Contract
--------
The producer job already did its work and committed ONLY its outputs on top of
``base`` (the commit it checked out). ``publish`` then, for a bounded number of
attempts:

1. reads the current remote ``main`` (``git fetch``; read only);
2. refuses if ``main`` no longer descends from ``base`` (history rewrite);
3. recognises an earlier accepted publication (lost HTTP response, crash after
   push, rerun) by comparing the producer's blobs with the remote blobs ->
   ``ALREADY_PUBLISHED_EQUIVALENT``; nothing is pushed twice;
4. asks the policy to classify EVERY path changed concurrently on the remote
   (``keep`` the exact remote bytes, ``rerender`` a derived view offline, or
   refuse). Unknown paths are refused by the policies;
5. transplants exactly the producer's blobs over the remote tree with an
   isolated Git index (the remote blobs of every other path stay byte-for-byte);
6. re-verifies the exact candidate tree (``Policy.verify_candidate``);
7. pushes ``<candidate>:refs/heads/main`` as an ordinary fast-forward and
   classifies a failure with ``git_publish_outcome``:
   CAS_REJECTED -> next attempt (full revalidation); UNCERTAIN/TRANSIENT -> read
   the remote first, accept a confirmed publication, otherwise a bounded retry
   (``git_publish_outcome.transport_backoff``); UNKNOWN -> read the remote once (a
   confirmed publication is accepted), then stop; AUTH -> stop.

A Git conflict is only a Git problem: the publisher never re-runs producers,
never contacts a provider and never sends a Telegram message.

Every outcome writes one receipt (``<PREFIX>_PUBLISH_RECEIPT`` on stdout and an
optional JSON file) with the final state and SHAs. On failure the local branch
is put back on the unpublished producer commit and, when requested, that commit
is exported as a Git bundle so its outputs are never silently lost.

Receipt ``path`` values distinguish: FIRST_ATTEMPT, AFTER_CAS, AFTER_TRANSPORT,
CONFIRMED_AFTER_TRANSPORT_ERROR, EQUIVALENT_ALREADY_ON_REMOTE. Failure statuses:
REFUSED (persistent incompatibility; ``failure_class`` PERSISTENT_INCOMPATIBILITY),
RETRY_EXHAUSTED (``TRANSIENT_CONTENTION`` that did not clear inside the bound),
OUTCOME_UNRESOLVED (transport; the remote could not be read), PUSH_REFUSED
(auth/protection/unknown push error).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from scripts import git_publish_outcome as outcome

SHA = re.compile(r"[a-f0-9]{40}\Z")


class PublicationRefused(ValueError):
    """Publication must not happen. ``kind`` is a stable machine-readable reason."""

    def __init__(self, message, kind="REFUSED"):
        super().__init__(message)
        self.kind = kind


class Superseded(PublicationRefused):
    """Valid, but computed on inputs that changed on main meanwhile: not published, recomputed by
    the producer's next run. Never a partial publication, never presented as current state."""

    def __init__(self, message):
        super().__init__(message, "SUPERSEDED_BY_NEWER_INPUTS")


class RetryExhausted(PublicationRefused):
    def __init__(self, message):
        super().__init__(message, "RETRY_EXHAUSTED")


class OutcomeUnresolved(PublicationRefused):
    def __init__(self, message):
        super().__init__(message, "OUTCOME_UNRESOLVED")


class PushRefused(PublicationRefused):
    def __init__(self, message):
        super().__init__(message, "PUSH_REFUSED")


# ------------------------------------------------------------------ Git helpers
def run(root, *args, env=None, check=True):
    proc = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env)
    if check and proc.returncode:
        raise PublicationRefused("Git operation failed: %s (%s)" % (
            " ".join(args[:2]), proc.stderr.decode("utf-8", "replace")[-300:]), "GIT_ERROR")
    return proc


def git(root, *args, env=None):
    return run(root, *args, env=env).stdout


def sha(root, ref):
    value = git(root, "rev-parse", "--verify", ref).decode().strip()
    if not SHA.fullmatch(value):
        raise PublicationRefused("Invalid Git revision " + ref, "GIT_ERROR")
    return value


def changed_paths(root, a, b):
    raw = git(root, "diff", "--no-renames", "--name-only", "-z", a, b)
    names = {p.decode("utf-8") for p in raw.split(b"\0") if p}
    if any(not n or n.startswith("/") or ".." in n.split("/") for n in names):
        raise PublicationRefused("Malformed Git paths", "GIT_ERROR")
    return names


def blob(root, ref, path):
    proc = run(root, "show", ref + ":" + path, check=False)
    return None if proc.returncode else proc.stdout


def tree_entry(root, ref, path):
    """(mode, sha) of a regular file, None when absent; anything else is refused."""
    raw = git(root, "ls-tree", "-z", ref, "--", path)
    if not raw:
        return None
    items = [i for i in raw.split(b"\0") if i]
    if len(items) != 1:
        raise PublicationRefused("Ambiguous tree entry: " + path)
    header, name = items[0].split(b"\t", 1)
    mode, kind, obj = header.decode("ascii").split()
    if name.decode() != path or kind != "blob" or mode != "100644" or not SHA.fullmatch(obj):
        raise PublicationRefused("Unsafe tree entry (mode/type): " + path)
    return mode, obj


def transport(root, remote, source, paths, message):
    """Commit = remote tree + the source entries of ``paths`` (isolated index, parent = remote)."""
    with tempfile.TemporaryDirectory(prefix="selective-index-") as d:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(d) / "index")}
        git(root, "read-tree", remote, env=env)
        for path in sorted(paths):
            row = tree_entry(root, source, path)
            if row is None:
                git(root, "update-index", "--force-remove", "--", path, env=env)
            else:
                git(root, "update-index", "--add", "--cacheinfo",
                    "%s,%s,%s" % (row[0], row[1], path), env=env)
        tree = git(root, "write-tree", env=env).decode().strip()
        return git(root, "commit-tree", tree, "-p", remote, "-m", message, env=env).decode().strip()


def default_push(root, candidate, branch="main"):
    return run(root, "push", "origin", candidate + ":refs/heads/" + branch, check=False)


# ------------------------------------------------------------------ policy
class Policy:
    """Producer-specific rules. Subclasses override what they need."""

    name = "GENERIC"            # receipt prefix, e.g. COLLECT -> COLLECT_PUBLISH_RECEIPT
    message = "data: publish [skip ci]"
    rerender_paths = frozenset()  # derived views rebuilt offline when their inputs moved

    def owns(self, path):       # may this producer publish ``path``?
        raise NotImplementedError

    def verify_own(self, root, base, source, produced):
        """base -> source guards on the producer's own change; return receipt fields."""
        return {}

    def check_remote(self, root, base, remote, path, produced, source):
        """Classify one concurrent remote change: 'keep' | 'rerender'; raise to refuse."""
        raise PublicationRefused("Unknown concurrent path: " + path, "UNKNOWN_PATH")

    def rerender(self, root):
        raise PublicationRefused("Policy cannot re-render derived views", "RERENDER_FAILED")

    def verify_equivalent(self, root, remote):
        """Before accepting 'already published': is the remote's derived state coherent too?"""
        return True

    def verify_candidate(self, root, remote, candidate, produced):
        """Final check of the exact tree that will be pushed."""

    def failure_diagnostics(self, root, base, source):
        """Extra operational fields for a failed publication (e.g. Telegram receipts at risk)."""
        return {}


# ------------------------------------------------------------------ receipt
def emit(policy, path, document):
    print(policy.name + "_PUBLISH_RECEIPT", json.dumps(document, sort_keys=True))
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def classify_remote(policy, root, base, remote, produced, source):
    """Every concurrent path must be classified; collect all refusals, report the primary one."""
    changes = changed_paths(root, base, remote)
    actions, refusals = {}, []
    for path in sorted(changes):
        if path in produced and blob(root, remote, path) == blob(root, source, path):
            actions[path] = "equal"
            continue
        try:
            actions[path] = policy.check_remote(root, base, remote, path, produced, source)
        except PublicationRefused as exc:
            refusals.append(exc)
    if refusals:
        order = {"INCOMPATIBLE_PROGRAM": 0, "CONCURRENT_OWNER_WRITE": 1, "INTEGRITY": 2,
                 "DEPENDENCY_CHANGED": 3, "UNKNOWN_PATH": 9,
                 "SUPERSEDED_BY_NEWER_INPUTS": 20}   # any real refusal outranks a supersession
        refusals.sort(key=lambda e: order.get(e.kind, 5))
        first = refusals[0]
        more = "" if len(refusals) == 1 else " | %d refused paths: %s" % (
            len(refusals), "; ".join(str(e)[:100] for e in refusals[1:8]))
        if isinstance(first, Superseded) and all(isinstance(e, Superseded) for e in refusals):
            raise Superseded(str(first) + more)
        raise PublicationRefused(str(first) + more, first.kind)
    if any(a not in ("keep", "rerender", "equal") for a in actions.values()):
        raise PublicationRefused("Policy returned an invalid action", "GIT_ERROR")
    return changes, actions


# ------------------------------------------------------------------ publish
def publish(root, *, base, policy, receipt=None, bundle=None, max_attempts=6,
            max_transport_failures=3, sleep=time.sleep, push=default_push, branch="main"):
    root = Path(root)
    trace = {"attempts": 0, "remote_heads": [], "push_failures": [], "source": None}
    try:
        return _publish(root, base, policy, receipt, trace, max_attempts,
                        max_transport_failures, sleep, push, branch)
    except PublicationRefused as exc:
        status = exc.kind if exc.kind in ("RETRY_EXHAUSTED", "OUTCOME_UNRESOLVED", "PUSH_REFUSED",
                                          "SUPERSEDED_BY_NEWER_INPUTS") else "REFUSED"
        failure_class = {"RETRY_EXHAUSTED": "TRANSIENT_CONTENTION",
                         "OUTCOME_UNRESOLVED": "TRANSPORT",
                         "PUSH_REFUSED": "PUSH_REFUSED",
                         "SUPERSEDED_BY_NEWER_INPUTS": "SUPERSEDED_SAFE_SKIP"}.get(
                             status, "PERSISTENT_INCOMPATIBILITY")
        source = trace["source"]
        bundle_path = None
        extra = {}
        if source:
            run(root, "reset", "-q", "--hard", source, check=False)
            if bundle:
                made = run(root, "bundle", "create", str(bundle), "HEAD", "^" + base, check=False)
                bundle_path = str(bundle) if made.returncode == 0 else None
                if made.returncode:
                    print(policy.name + "_BUNDLE_FAILED",
                          made.stderr.decode("utf-8", "replace")[-200:])
            try:
                extra = policy.failure_diagnostics(root, base, source)
            except Exception as diag:  # diagnostics must never hide the primary failure
                extra = {"diagnostics_error": type(diag).__name__}
        emit(policy, receipt, {
            "status": status, "reason_kind": exc.kind, "failure_class": failure_class,
            "reason": str(exc)[:600], "base": base, "source_commit": source,
            "published_commit": None, "attempts": trace["attempts"],
            "remote_heads": trace["remote_heads"], "push_failures": trace["push_failures"],
            "bundle": bundle_path, "provider_requeries": 0, "telegram_requests": 0,
            "run_id": os.environ.get("GITHUB_RUN_ID"), **extra})
        raise


def _publish(root, base, policy, receipt, trace, max_attempts, max_transport_failures,
             sleep, push, branch):
    if not SHA.fullmatch(base or "") or not 1 <= max_attempts <= 10 \
            or not 0 <= max_transport_failures <= 5:
        raise PublicationRefused("Invalid base or retry bound", "INVALID_INPUT")
    source = sha(root, "HEAD")
    trace["source"] = source
    if sha(root, "HEAD^") != base:
        raise PublicationRefused("Producer commit is not based on the pinned checkout",
                                 "INVALID_INPUT")
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise PublicationRefused("Producer checkout is not clean", "INVALID_INPUT")
    produced = changed_paths(root, base, source)
    foreign = sorted(p for p in produced if not policy.owns(p))
    if not produced or foreign:
        raise PublicationRefused("Producer commit touches paths it does not own: %r"
                                 % foreign[:8], "NOT_OWNER")
    own = policy.verify_own(root, base, source, produced) or {}
    doc = {"base": base, "source_commit": source, "produced_paths": len(produced),
           "provider_requeries": 0, "telegram_requests": 0,
           "run_id": os.environ.get("GITHUB_RUN_ID"), **own}
    compare = produced - policy.rerender_paths or produced
    transport_failures, cas = 0, 0
    for attempt in range(1, max_attempts + 1):
        trace["attempts"] = attempt
        remote = outcome.remote_head(root, branch, sleep=sleep)
        if remote is None:
            raise OutcomeUnresolved("Remote main unreadable before publication")
        trace["remote_heads"].append(remote)
        if run(root, "merge-base", "--is-ancestor", base, remote, check=False).returncode:
            raise PublicationRefused("Remote main no longer descends from the producer base",
                                     "HISTORY_DIVERGED")
        if remote != base and outcome.same_paths(root, source, remote, compare) \
                and policy.verify_equivalent(root, remote):
            run(root, "reset", "-q", "--hard", remote)
            emit(policy, receipt, {**doc, "status": "ALREADY_PUBLISHED_EQUIVALENT",
                                   "path": "EQUIVALENT_ALREADY_ON_REMOTE", "attempt": attempt,
                                   "published_commit": remote, "cas_retries": cas,
                                   "transport_failures": transport_failures})
            return remote
        changes, actions = classify_remote(policy, root, base, remote, produced, source)
        rerender = any(a == "rerender" for a in actions.values()) and \
            bool(produced & policy.rerender_paths)
        if remote == base:
            candidate = source
        else:
            moved = produced - (policy.rerender_paths if rerender else frozenset())
            candidate = transport(root, remote, source, moved, policy.message)
        run(root, "reset", "-q", "--hard", candidate)
        if rerender:
            policy.rerender(root)
            dirty = git(root, "status", "--porcelain", "--untracked-files=no").strip()
            if dirty:
                run(root, "add", "--", *sorted(produced & policy.rerender_paths))
                run(root, "commit", "-q", "--amend", "--no-edit")
                candidate = sha(root, "HEAD")
        extra = changed_paths(root, remote, candidate) - produced
        if extra:
            raise PublicationRefused("Candidate touches non-owned paths: %r" % sorted(extra)[:8],
                                     "NOT_OWNER")
        policy.verify_candidate(root, remote, candidate, produced)
        result = push(root, candidate, branch)
        if result.returncode == 0:
            path = "FIRST_ATTEMPT" if attempt == 1 else \
                "AFTER_TRANSPORT" if transport_failures else "AFTER_CAS"
            emit(policy, receipt, {**doc, "status": "PUBLISHED", "path": path, "attempt": attempt,
                                   "published_commit": candidate, "remote_base": remote,
                                   "concurrent_paths": len(changes), "rerendered": rerender,
                                   "cas_retries": cas, "transport_failures": transport_failures,
                                   "remote_heads": trace["remote_heads"]})
            return candidate
        err = result.stderr.decode("utf-8", "replace")
        kind = outcome.classify_push_failure(err, branch)
        trace["push_failures"].append(kind)
        print(policy.name + "_PUSH_FAILURE", json.dumps({
            "attempt": attempt, "kind": kind, "candidate": candidate,
            "remote_before_push": remote}, sort_keys=True))
        if kind == outcome.CAS_REJECTED:
            cas += 1
            continue
        if kind in (outcome.UNCERTAIN, outcome.TRANSIENT):
            transport_failures += 1
            state, now = outcome.probe_remote(root, candidate, branch, sleep=sleep)
            if state == outcome.PUBLISHED:
                emit(policy, receipt, {**doc, "status": "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR",
                                       "path": "CONFIRMED_AFTER_TRANSPORT_ERROR",
                                       "attempt": attempt, "published_commit": candidate,
                                       "remote_after": now, "cas_retries": cas,
                                       "transport_failures": transport_failures,
                                       "remote_heads": trace["remote_heads"]})
                return candidate
            if state == outcome.UNRESOLVED:
                raise OutcomeUnresolved("Push outcome unknown and remote unreadable: " + err[-200:])
            if transport_failures > max_transport_failures:
                raise OutcomeUnresolved("Transport failed %d times; candidate not on remote: %s"
                                        % (transport_failures, err[-200:]))
            sleep(outcome.transport_backoff(transport_failures))
            continue
        if kind != outcome.AUTH:
            # An unclassified refusal is not proof that nothing was published: read the remote
            # once (read only, no retry) so the receipt never reports a published commit as lost.
            state, now = outcome.probe_remote(root, candidate, branch, sleep=sleep)
            if state == outcome.PUBLISHED:
                emit(policy, receipt, {**doc, "status": "PUBLISHED_CONFIRMED_AFTER_TRANSPORT_ERROR",
                                       "path": "CONFIRMED_AFTER_TRANSPORT_ERROR",
                                       "attempt": attempt, "published_commit": candidate,
                                       "remote_after": now, "cas_retries": cas,
                                       "transport_failures": transport_failures,
                                       "unclassified_push_error": kind,
                                       "remote_heads": trace["remote_heads"]})
                return candidate
        raise PushRefused("Push refused (%s): %s" % (kind, err[-300:]))
    raise RetryExhausted("Remote advanced during all %d bounded publication attempts" % max_attempts)

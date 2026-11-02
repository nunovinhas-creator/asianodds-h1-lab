"""Classify a failed ``git push`` and resolve uncertain outcomes against the remote.

Shared by the FT and H1 publishers. It never calls a sports provider, never
force-pushes and never rewrites history. Its only network actions are
``git fetch`` (read) of the remote branch.

Push outcome states (see docs/audit/publication-push-outcome-2026-11-02.md):

``PUBLISHED``          the remote branch contains the candidate commit.
``CAS_REJECTED``       the remote refused the update because the branch moved
                       (non-fast-forward or GitHub's "cannot lock ref" race);
                       the candidate was provably NOT accepted.
``UNCERTAIN``          transport failed after the pack may have been sent
                       (HTTP 408/5xx, RPC failed, unexpected disconnect, remote
                       hung up, ``[remote rejected] ... (Internal Server Error)``). Acceptance is unknown until the remote is read.
``AUTH``               authentication/authorisation/branch-protection refusal.
                       Never retried.
``TRANSIENT``          transport failed before anything could reach the
                       remote (DNS, connection refused, TLS handshake).
``INCOMPATIBLE``       decided by the caller: a concurrent remote change that
                       may not be transported (code, same-path writes).

HTTP 408 does NOT prove that nothing was published: GitHub may have applied the
ref update and only the response was lost. ``probe_remote`` therefore reads the
remote before any further attempt.
"""
from __future__ import annotations

import re
import subprocess
import time

PUBLISHED = "PUBLISHED"
CAS_REJECTED = "CAS_REJECTED"
UNCERTAIN = "UNCERTAIN"
AUTH = "AUTH"
TRANSIENT = "TRANSIENT"
INCOMPATIBLE = "INCOMPATIBLE"
NOT_ACCEPTED = "NOT_ACCEPTED"
UNRESOLVED = "UNRESOLVED"

_CAS = re.compile(
    r"cannot lock ref 'refs/heads/(?P<ref>[A-Za-z0-9._/-]+)': is at [a-f0-9]{40} "
    r"but expected [a-f0-9]{40}(?![a-f0-9])")
_AUTH_MARKERS = (
    "authentication failed", "http 401", "http 403", "error: 401", "error: 403",
    "returned error: 401", "returned error: 403", "permission to ", "permission denied",
    "denied to ", "protected branch", "gh006", "gh013", "refusing to allow",
    "invalid username or password", "could not read username", "write access to repository not granted",
)
_UNCERTAIN_MARKERS = (
    "rpc failed", "http 408", "returned error: 408", "http 500", "http 502", "http 503",
    "http 504", "returned error: 5", "unexpected disconnect", "remote end hung up",
    "early eof", "connection reset", "operation timed out", "timed out", "broken pipe",
    "the remote end hung up unexpectedly", "sideband packet", "gnutls_handshake",
    "unexpected eof",
    # GitHub server-side failure reported on the ref line, e.g.
    # "! [remote rejected] <sha> -> main (Internal Server Error)". The ref update may or
    # may not have been applied, so the remote is read before any retry.
    "(internal server error)", "(bad gateway)", "(service unavailable)",
    "(gateway timeout)", "(failed to update ref)",
)
_TRANSIENT_MARKERS = (
    "could not resolve host", "failed to connect", "connection refused",
    "couldn't connect to server", "network is unreachable", "temporary failure in name resolution",
)


def classify_push_failure(stderr: str, branch: str = "main") -> str:
    """Return one of CAS_REJECTED, AUTH, UNCERTAIN, TRANSIENT or ``"UNKNOWN"``.

    Order matters: an authorisation refusal is never retried even when the
    transport also reported a disconnect; a ref race is only a race for the
    exact branch being published.
    """
    text = stderr.lower()
    if any(marker in text for marker in _AUTH_MARKERS):
        return AUTH
    match = _CAS.search(stderr)
    if match:
        return CAS_REJECTED if match.group("ref") == branch else "UNKNOWN"
    if "cannot lock ref" in text:
        return "UNKNOWN"
    if any(x in text for x in ("non-fast-forward", "fetch first", "stale info")):
        return CAS_REJECTED
    if any(marker in text for marker in _UNCERTAIN_MARKERS):
        return UNCERTAIN
    if any(marker in text for marker in _TRANSIENT_MARKERS):
        return TRANSIENT
    return "UNKNOWN"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def remote_head(root, branch="main", *, fetch=None, attempts=3, sleep=time.sleep,
                backoff=(2, 4, 8)):
    """Read the remote branch head with a bounded number of fetches.

    Returns the SHA or ``None`` when the remote could not be read at all.
    """
    fetch = fetch or (lambda: _git(root, "fetch", "--no-tags", "origin", branch))
    for attempt in range(attempts):
        proc = fetch()
        if proc.returncode == 0:
            head = _git(root, "rev-parse", "--verify", "FETCH_HEAD")
            value = head.stdout.decode().strip()
            if head.returncode == 0 and re.fullmatch(r"[a-f0-9]{40}", value):
                return value
        if attempt + 1 < attempts:
            sleep(backoff[min(attempt, len(backoff) - 1)])
    return None


def contains(root, ancestor, descendant) -> bool:
    if ancestor == descendant:
        return True
    return _git(root, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def probe_remote(root, candidate, branch="main", **kwargs):
    """Resolve an uncertain push: (PUBLISHED|NOT_ACCEPTED|UNRESOLVED, remote_sha)."""
    remote = remote_head(root, branch, **kwargs)
    if remote is None:
        return UNRESOLVED, None
    if contains(root, candidate, remote):
        return PUBLISHED, remote
    return NOT_ACCEPTED, remote


def same_paths(root, left, right, paths) -> bool:
    """True when every path has the identical Git entry (mode+blob, or absence) in both commits."""
    for path in sorted(paths):
        a = _git(root, "ls-tree", left, "--", path).stdout
        b = _git(root, "ls-tree", right, "--", path).stdout
        if a != b:
            return False
    return True

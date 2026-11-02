"""Deterministic bare-Git fixture shared by the publication concurrency tests.

A local bare repository plays GitHub. Every writer is a separate clone. Fault
injection (CAS race, HTTP 408 before/after acceptance, auth refusal, unreadable
remote) happens at explicit points through a ``push`` hook, never through
thread timing, so every run takes the same path.
"""
import json
import subprocess
import tempfile
from pathlib import Path

HTTP_408 = (b"error: RPC failed; HTTP 408 curl 22 The requested URL returned error: 408\n"
            b"send-pack: unexpected disconnect while reading sideband packet\n"
            b"fatal: the remote end hung up unexpectedly\n")
AUTH_403 = (b"remote: Permission to x/y.git denied to github-actions[bot].\n"
            b"fatal: unable to access 'https://github.com/x/y/': The requested URL returned error: 403\n")


def cas(actual, expected):
    return ("error: cannot lock ref 'refs/heads/main': is at %s but expected %s\n"
            "! [remote rejected] HEAD -> main (failed to update ref)\n" % (actual, expected)).encode()


def git(root, *args, check=True):
    proc = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
    if check and proc.returncode:
        raise AssertionError("git %s failed: %s" % (" ".join(args), proc.stderr.decode()))
    return proc.stdout.decode().strip()


def write(root, name, content):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content, indent=2,
                                                                       sort_keys=True) + "\n")


def jline(**row):
    return json.dumps(row, sort_keys=True) + "\n"


# ---------------------------------------------------------------- realistic baseline files
def state(last_id=100, alerts=("c:1",), home="A"):
    rows = [{"event_id": e, "match_key": "2026-11-03,%s" % e.split(":")[1], "home": home,
             "away": "B" + e.split(":")[1], "kickoff_utc": "2026-11-03T19:00:00+00:00",
             "competition": "X"} for e in alerts]
    return {"last_id": last_id, "alerts": rows, "signals": [], "tickets": [], "diagnostics": []}


def ledger(rule="THREE_V4_INDEPENDENT_TOTAL_MOVES_20261031", **entries):
    return {"schema_version": 1, "rule_version": rule, "activated_at": "2026-10-31T00:00:00+00:00",
            "entries": {k.replace("_", ","): v for k, v in entries.items()}}


SENT_OLD = {"status": "sent", "telegram_message_id": 10, "kickoff_utc": "2026-11-01T16:00:00+00:00",
            "at": "2026-11-01T10:00:00+00:00", "attempts": 1}
SENT_NEW = {"status": "sent", "telegram_message_id": 777, "kickoff_utc": "2026-11-03T19:00:00+00:00",
            "at": "2026-11-02T07:01:00+00:00", "attempts": 1}

BASELINE = {
    "data/state.json": state(),
    "docs/data.json": None,
    "data/three-total-moves-notifications.json": ledger(**{"2026-11-01_1_2": SENT_OLD}),
    "data/two-up-total-notifications.json": ledger(rule="TWO_UP"),
    "data/pattern-notifications.json": {"schema_version": 1, "entries": {}},
    "data/lab/markets-2026-11.jsonl": jline(event_id="c:1", observed_at="2026-11-02T06:00:00+00:00"),
    "data/lab/formats-2026-11.jsonl": jline(event_id="c:1", observed_at="2026-11-02T06:00:00+00:00"),
    "data/lab/v4-revisions-2026-11.jsonl": jline(event_id="c:1", sha256="a" * 64),
    "data/results.csv": "match_key,status,home_goals,away_goals,source\n\"2026-11-01,1,2\",final,1,0,x\n",
    "data/result_audit.json": {"2026-11-01,1,2": {"status": "settled"}},
    "data/health/h1-results.json": {"status": "CYCLE_COMPLETED", "n": 1},
    "data/lab/ft-ledger.json": {"schema_version": 1, "matches": {
        "2026-11-01,1,2": {"status": "FINAL", "result": {"home_goals": 1, "away_goals": 0}}}},
    "data/lab/v6-forecasts-2026-11.jsonl": jline(forecast="f1"),
    "data/lab/v6-ft-events-2026-11.jsonl": jline(ft="e1"),
    "data/lab/v4-runchecks.jsonl": jline(run=1),
    "docs/lab/v4-audit.json": {"source_commit": "unknown", "n": 1},
    "docs/lab/ft-results.json": {"final": 1},
    "h1lab/core.py": "# program\n",
}


def view(alerts, results):
    """Rendered dashboard (docs/data.json) with realistic distance between fields."""
    return {"alerts": alerts, "generated_at": "fixed", "h1": {"roi": 0}, "lab": [],
            "results": results}


BASELINE["docs/data.json"] = view(1, 1)


class BareGitFixture:
    """One bare 'GitHub' + named writer clones that all start from the same main."""

    def __init__(self, files=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.remote = self.home / "github.git"
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(self.remote)], check=True)
        seed = self.clone("seed")
        for name, content in (files or BASELINE).items():
            write(seed, name, content)
        git(seed, "add", "-A")
        git(seed, "commit", "-qm", "baseline")
        git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")
        self.base = git(seed, "rev-parse", "HEAD")

    def cleanup(self):
        self.tmp.cleanup()

    def clone(self, name):
        root = self.home / name
        if not root.exists():
            subprocess.run(["git", "clone", "-q", str(self.remote), str(root)], check=True,
                           stderr=subprocess.DEVNULL)
            git(root, "config", "user.name", name)
            git(root, "config", "user.email", name + "@example.invalid")
            git(root, "checkout", "-q", "-B", "main")
        return root

    def main(self):
        return git(self.remote, "rev-parse", "refs/heads/main")

    def show(self, path, ref=None):
        proc = subprocess.run(["git", "-C", str(self.remote), "show", (ref or "refs/heads/main")
                               + ":" + path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return None if proc.returncode else proc.stdout.decode()

    def json(self, path, ref=None):
        raw = self.show(path, ref)
        return None if raw is None else json.loads(raw)

    def plain_commit(self, name, changes, message, deletions=()):
        """Another writer publishes an ordinary fast-forward commit on the current main."""
        root = self.clone(name)
        git(root, "fetch", "-q", "origin", "main")
        git(root, "reset", "-q", "--hard", "origin/main")
        for path, content in changes.items():
            write(root, path, content)
        for path in deletions:
            git(root, "rm", "-q", path)
        git(root, "add", "-A")
        git(root, "commit", "-qm", message)
        git(root, "push", "-q", "origin", "HEAD:refs/heads/main")
        return git(root, "rev-parse", "HEAD")


class PushHook:
    """Deterministic fault injection around the real push: ``script[n]`` handles push n (1-based)."""

    def __init__(self, script=None):
        self.script = script or {}
        self.calls = []

    def __call__(self, root, candidate, branch="main"):
        self.calls.append(candidate)
        n = len(self.calls)
        real = lambda: subprocess.run(["git", "-C", str(root), "push", "origin",
                                       candidate + ":refs/heads/" + branch],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        action = self.script.get(n)
        if action is None:
            return real()
        return action(real, candidate)


def fail(stderr):
    return lambda real, candidate: subprocess.CompletedProcess(["git", "push"], 128, b"", stderr)


def accept_then_fail(stderr):
    def action(real, candidate):
        done = real()
        assert done.returncode == 0, done.stderr
        return subprocess.CompletedProcess(["git", "push"], 128, b"", stderr)
    return action


def race(fixture, writer, changes, message):
    """Another writer lands first; the server answers our push with GitHub's CAS text."""
    def action(real, candidate):
        before = fixture.main()
        fixture.plain_commit(writer, changes, message)
        return subprocess.CompletedProcess(["git", "push"], 1, b"", cas(fixture.main(), before))
    return action

"""Publish an already sealed FT commit across unrelated H1/V4 Git activity.

Use only AFTER the FT producers, immutable-FINAL guard, segment staging and
publication seal have succeeded. No provider calls, blind retries, rebases,
force pushes or rewrites of concurrent FT artifacts.

The original FT commit is transplanted byte-for-byte over the current remote
tree with an isolated Git index. The new tree is *fully* verified before an
ordinary fast-forward Git push. Changed FT files, mutated identities, rewritten
journals, code, or unknown remote paths always abort.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from scripts import publication_guard
from scripts.lab_discovery_authoritative_release import main as discovery_verify
from h1lab.lab_ft_final_guard import verify_files

SHA = re.compile(r"[a-f0-9]{40}\Z")
JOURNAL = re.compile(r"data/lab/(?:markets|formats|v4-revisions|v4-runchecks)-\d{4}-\d{2}\.jsonl\Z")
V4_REPORT = re.compile(
    r"docs/lab/(?:v4-audit|v4-revisions|golden-candidates|golden-report|"
    r"golden-priority|v6-shadow|v6-readiness|v6-price-quality|"
    r"v6-feature-coverage|v6-memory|v6-falsification|"
    r"match-trajectories|trajectory-research|outcome-readiness|"
    r"v6-scientific-radar|v6-weekly-drift|v6-archive-health|"
    r"v6-p0-null-simulation|v6-p0-gates)\.json\Z"
)
V4_ARCHIVE = re.compile(
    r"data/lab/(?:v6-forecasts-\d{4}-\d{2}|v6-memory-(?:observations|patterns)-\d{4}-\d{2}|v6-memory-\d{4}-\d{2}|"
    r"v6-hypotheses|v6-weekly-snapshots|v4-runchecks(?:-\d{4}-\d{2})?)\.jsonl\Z"
)
LLM_SHADOW = re.compile(
    r"docs/lab/(?:llm-discovery-plan|llm-investigator-index|"
    r"llm-investigator-runs/\d+)\.json\Z"
)

# Known H1 Telegram receipts are independent of FT evidence.
H1_NOTIFICATION_RECEIPTS = frozenset({
    "data/three-total-moves-notifications.json",
    "data/two-up-total-notifications.json",
    "data/e4-notifications.json",
    "data/strategy-notifications.json",
    "data/pattern-notifications.json",
    "data/t05-notifications.json",
})
H1_RESULT_OUTPUTS = frozenset({
    "data/results.csv", "data/result_audit.json", "data/health/h1-results.json",
})


class UnsafeFTPublication(ValueError):
    pass


def run(root, *args, env=None, input_bytes=None, check=True):
    proc = subprocess.run(["git", "-C", str(root), *args], input=input_bytes,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if check and proc.returncode:
        raise UnsafeFTPublication(
            "Git operation failed: " + " ".join(args[:2])
            + " (" + proc.stderr.decode("utf-8", "replace")[-350:] + ")")
    return proc


def git(root, *args, env=None):
    return run(root, *args, env=env).stdout


def sha(root, ref):
    value = git(root, "rev-parse", "--verify", ref).decode().strip()
    if not SHA.fullmatch(value):
        raise UnsafeFTPublication("Invalid Git revision " + ref)
    return value


def changed_paths(root, base, target):
    result = git(root, "diff", "--name-only", "-z", base, target)
    names = set(p.decode("utf-8") for p in result.split(b"\0") if p)
    if any(not name or name.startswith("/") or "\\x00" in name
           for name in names):
        raise UnsafeFTPublication("Malformed Git paths")
    return names


def blob_or_none(root, ref, path):
    proc = run(root, "show", ref + ":" + path, check=False)
    if proc.returncode:
        return None
    return proc.stdout


def stable_fixtures(before, after):
    """H1 odds can change, but shared match identities may never change."""
    try:
        a, b = json.loads(before), json.loads(after)
        if not isinstance(a, dict) or not isinstance(b, dict):
            return False
        def ids(state):
            result = {}
            for field in ("alerts", "signals"):
                rows = state.get(field, [])
                if not isinstance(rows, list):
                    raise ValueError("Invalid H1 events")
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError("Invalid H1 observation")
                    key = row.get("match_key")
                    if not isinstance(key, str) or not key:
                        continue
                    identity = (row.get("home"), row.get("away"),
                                row.get("kickoff_utc"), row.get("competition"))
                    if any(not isinstance(v, str) or not v for v in identity[:3]):
                        raise ValueError("Missing fixture identity")
                    result.setdefault(key, set()).add(identity[:3])
            return result
        previous, current = ids(a), ids(b)
        return all(previous[key] == current[key]
                   for key in previous.keys() & current.keys())
    except (ValueError, TypeError):
        return False


def append_only_jsonl(previous, current):
    if previous is None:
        previous = b""
    if not current.startswith(previous) or (previous and not previous.endswith(b"\n")):
        return False
    extra = current[len(previous):]
    if extra and not extra.endswith(b"\n"):
        return False
    try:
        return all(isinstance(json.loads(line), dict)
                   for line in extra.splitlines() if line)
    except (ValueError, UnicodeDecodeError):
        return False



def valid_notification_update(previous, current):
    """Accept only retained, schema-valid receipts; never discard H1 history."""
    if previous is None or current is None:
        return False
    try:
        old, new = json.loads(previous), json.loads(current)
        if not isinstance(old, dict) or not isinstance(new, dict):
            return False
        if old.get("schema_version") != 1 or new.get("schema_version") != 1:
            return False
        before, after = old.get("entries"), new.get("entries")
        if not isinstance(before, dict) or not isinstance(after, dict):
            return False
        if any(not isinstance(key, str) or not isinstance(row, dict)
               for key, row in after.items()):
            return False
        if not before.keys() <= after.keys():
            return False
        for key, prior in before.items():
            if not isinstance(prior, dict):
                return False
            updated = after[key]
            # Withdrawals may change status; fixture identity never changes.
            for field in ("match_key", "kickoff_utc"):
                if field in prior and prior[field] != updated.get(field):
                    return False
        return True
    except (ValueError, UnicodeDecodeError, TypeError):
        return False



# This is a derived read-only H1/Telegram diagnostic, not an FT dependency.
# It may be regenerated between FT checkout and FT publication.
TELEGRAM_ELIGIBILITY_REPORT = "docs/lab/telegram-eligibility.json"


def _eligibility_timestamp(value):
    from datetime import datetime, timezone
    if not isinstance(value, str):
        raise ValueError("Invalid UTC eligibility timestamp")
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None or moment.utcoffset().total_seconds() != 0:
        raise ValueError("Eligibility timestamp must be UTC")
    return moment.astimezone(timezone.utc)


def _valid_eligibility_report(raw):
    """Validate the independent report without treating it as FT evidence.

    Its visible game window can legitimately rotate. Cross-version validation
    therefore protects identities of shared games, never requires key growth.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 512_000:
        return None
    try:
        from h1lab import telegram_eligibility as eligibility
        from h1lab import three_moves_notify, two_up_notify
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise ValueError("Duplicate JSON key")
                out[key] = value
            return out
        def reject_constant(value):
            raise ValueError("Nonfinite JSON number")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=reject_constant)
        if not isinstance(data, dict) or data.get("schema_version") != eligibility.SCHEMA:
            return None
        if data.get("status") != "READ_ONLY_PARITY_VERIFIED_NOT_DELIVERY_PROOF":
            return None
        if data.get("rules") != {
                "three": three_moves_notify.RULE_VERSION,
                "two": two_up_notify.RULE_VERSION}:
            return None
        _eligibility_timestamp(data.get("generated_at"))
        if (not isinstance(data.get("source_commit"), str)
                or data["source_commit"] != "unknown"
                and not SHA.fullmatch(data["source_commit"])):
            return None
        if not isinstance(data.get("limitations"), str) or not data["limitations"]:
            return None
        games, summary = data.get("games"), data.get("summary")
        if not isinstance(games, dict) or not isinstance(summary, dict):
            return None
        fields = (
            "future_three_eligible", "future_two_eligible", "visible_games",
            "future_visible_exclusions", "review_possible_false_negative",
            "v4_source_errors",
        )
        if any(type(summary.get(field)) is not int or summary[field] < 0
               for field in fields):
            return None
        if summary["visible_games"] != len(games):
            return None
        reviews = 0
        for key, game in games.items():
            if (not isinstance(key, str) or not key
                    or not isinstance(game, dict)
                    or game.get("match_key") != key
                    or not isinstance(game.get("match_label"), str)
                    or not game["match_label"]):
                return None
            kickoff = game.get("kickoff_utc")
            if kickoff is not None:
                _eligibility_timestamp(kickoff)
            for field in ("three_eligible", "two_eligible", "v4_down_observed",
                          "review_possible_false_negative"):
                if type(game.get(field)) is not bool:
                    return None
            for field in ("observed_messages", "v4_moves_observed",
                          "valid_three_moves", "v4_up_observed", "valid_up_moves"):
                if type(game.get(field)) is not int or game[field] < 0:
                    return None
            if (not isinstance(game.get("net_up"), (int, float))
                    or isinstance(game["net_up"], bool)):
                return None
            # json.loads rejects NaN and infinity through parse_constant.
            if (not isinstance(game.get("rejects"), dict)
                    or any(not isinstance(k, str) or not k or
                           type(v) is not int or v < 0
                           for k, v in game["rejects"].items())):
                return None
            if not isinstance(game.get("reason"), str):
                return None
            if game.get("review_note") is not None and not isinstance(game["review_note"], str):
                return None
            receipts = game.get("receipts")
            if (not isinstance(receipts, dict)
                    or any(kind not in ("three", "two") for kind in receipts)):
                return None
            for entry in receipts.values():
                if (not isinstance(entry, dict)
                        or entry.get("status") not in (
                            "sent", "delivery_uncertain_manual_review")
                        or (entry.get("telegram_message_id") is not None and
                            (type(entry["telegram_message_id"]) is not int or
                             entry["telegram_message_id"] < 0))):
                    return None
            reviews += int(game["review_possible_false_negative"])
        if summary["review_possible_false_negative"] != reviews:
            return None
        return data
    except (ValueError, TypeError, UnicodeDecodeError, OverflowError, KeyError):
        return None


def valid_telegram_eligibility_update(previous, current):
    """Allow only a newer valid read-only report; never overwrite remote H1.

    A rotating visible-games window is allowed. Overlapping fixture identity
    and observed Telegram receipts are immutable, while eligibility flags can
    naturally change with incoming observations and kickoff.
    """
    old = _valid_eligibility_report(previous)
    new = _valid_eligibility_report(current)
    if old is None or new is None:
        return False
    try:
        if (_eligibility_timestamp(new["generated_at"]) <
                _eligibility_timestamp(old["generated_at"])):
            return False
        for key in old["games"].keys() & new["games"].keys():
            before, after = old["games"][key], new["games"][key]
            if any(before.get(field) != after.get(field)
                   for field in ("match_key", "match_label", "kickoff_utc")):
                return False
            for rule, receipt in before["receipts"].items():
                if after["receipts"].get(rule) != receipt:
                    return False
        return True
    except (KeyError, ValueError, TypeError):
        return False


def allowed_remote_changes(root, base, remote, protected, produced):
    remote_changes = changed_paths(root, base, remote)
    overlap = remote_changes & (protected | produced)
    if overlap:
        raise UnsafeFTPublication(
            "Concurrent FT/sealed artifact changed: " + ", ".join(sorted(overlap)[:8]))
    for path in sorted(remote_changes):
        if (path.startswith(("h1lab/", "scripts/", ".github/", "tests/"))
                or path.startswith(("data/lab/discovery-segmented/",
                                    "docs/lab/discovery-pages/"))
                or path.startswith(("data/lab/ft-", "docs/lab/ft-",
                                    "data/lab/discovery-events-"))
                or path.startswith(("docs/lab/pattern-", "data/lab/pattern-"))):
            raise UnsafeFTPublication("FT dependency or program changed: " + path)
        if path == "data/state.json":
            previous = blob_or_none(root, base, path)
            current = blob_or_none(root, remote, path)
            if previous is None or current is None or not stable_fixtures(previous, current):
                raise UnsafeFTPublication("H1 fixture identity changed: " + path)
        elif path in ("docs/data.json", "data/results.json"):
            if blob_or_none(root, remote, path) is None:
                raise UnsafeFTPublication("H1 artifact deleted: " + path)
        elif path in H1_RESULT_OUTPUTS:
            # H1 results have a separate producer; keep their exact remote blobs.
            if blob_or_none(root, remote, path) is None:
                raise UnsafeFTPublication("H1 result output deleted: " + path)
        elif path == TELEGRAM_ELIGIBILITY_REPORT:
            # Independent report from another H1/Telegram producer. The FT
            # isolated-index transport retains the exact REMOTE blob.
            if not valid_telegram_eligibility_update(
                    blob_or_none(root, base, path),
                    blob_or_none(root, remote, path)):
                raise UnsafeFTPublication("Telegram eligibility report invalid: " + path)
        elif path in H1_NOTIFICATION_RECEIPTS:
            if not valid_notification_update(
                    blob_or_none(root, base, path),
                    blob_or_none(root, remote, path)):
                raise UnsafeFTPublication("H1 notification receipt invalid: " + path)
        elif JOURNAL.fullmatch(path) or V4_ARCHIVE.fullmatch(path):
            if not append_only_jsonl(blob_or_none(root, base, path),
                                     blob_or_none(root, remote, path) or b""):
                raise UnsafeFTPublication("V4/H1 journal rewritten: " + path)
        elif V4_REPORT.fullmatch(path) or LLM_SHADOW.fullmatch(path):
            if blob_or_none(root, remote, path) is None:
                raise UnsafeFTPublication("Concurrent report deleted: " + path)
        elif path == "data/lab/v6-archive-index.json":
            # Archive index changes can invalidate V4 origin provenance.
            raise UnsafeFTPublication("V4 source archive index changed")
        else:
            raise UnsafeFTPublication("Unknown concurrent path: " + path)
    return sorted(remote_changes)


def tree_entry(root, source, path):
    raw = git(root, "ls-tree", "-z", source, "--", path)
    if not raw:
        return None
    items = [item for item in raw.split(b"\0") if item]
    if len(items) != 1:
        raise UnsafeFTPublication("Ambiguous FT tree entry: " + path)
    header, filename = items[0].split(b"\t", 1)
    mode, kind, item_sha = header.decode("ascii").split()
    if filename.decode() != path or kind != "blob" or mode != "100644" or not SHA.fullmatch(item_sha):
        raise UnsafeFTPublication("Unsafe FT tree entry: " + path)
    return mode, item_sha


def assemble(root, remote, source, produced):
    """Use a separate Git index: never mix collector changes with FT outputs."""
    with tempfile.TemporaryDirectory(prefix="ft-git-index-") as d:
        idx = Path(d) / "index"
        env = {**os.environ, "GIT_INDEX_FILE": str(idx)}
        git(root, "read-tree", remote, env=env)
        for path in sorted(produced):
            row = tree_entry(root, source, path)
            if row is None:
                git(root, "update-index", "--force-remove", "--", path, env=env)
            else:
                mode, obj_sha = row
                git(root, "update-index", "--add", "--cacheinfo",
                    mode + "," + obj_sha + "," + path, env=env)
        newtree = git(root, "write-tree", env=env).decode().strip()
        if not SHA.fullmatch(newtree):
            raise UnsafeFTPublication("Invalid candidate Git tree")
        message = ("data(lab): publish verified FT snapshot over unrelated H1/V4 updates "
                   "[skip ci]")
        candidate = git(root, "commit-tree", newtree, "-p", remote,
                        "-m", message, env=env).decode().strip()
        if not SHA.fullmatch(candidate):
            raise UnsafeFTPublication("Invalid candidate FT commit")
        return candidate


def publish(root, *, base, manifest, baseline, max_attempts=6):
    root, manifest, baseline = Path(root), Path(manifest), Path(baseline)
    if not SHA.fullmatch(base) or not 1 <= max_attempts <= 10:
        raise UnsafeFTPublication("Invalid original run base or bounded retry count")
    source = sha(root, "HEAD")
    if sha(root, "HEAD^") != base:
        raise UnsafeFTPublication("FT source commit is not based on the pinned checkout")
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise UnsafeFTPublication("FT checkout is not clean")
    proof = json.loads(manifest.read_text(encoding="utf-8"))
    if proof.get("pipeline") != "ft" or not proof.get("segmented"):
        raise UnsafeFTPublication("Missing authoritative FT publication seal")
    sealed = set(proof["sha256"])
    produced = changed_paths(root, base, source)
    live_produced = {name for name in produced
                     if tree_entry(root, source, name) is not None}
    deleted = produced - live_produced
    # Old immutable generations disappear from HEAD once no longer reachable
    # through CURRENT/PREVIOUS. The segmented Git seal already proves those
    # are unreachable; deleted files are *not* live members in its hashes.
    retired = re.compile(
        r"data/lab/discovery-segmented/[a-f0-9]{64}/"
        r"(?:manifest\.json|legacy\.json\.gz|state-[0-9]{4}\.json)\Z"
    )
    if (not live_produced or not live_produced <= sealed
            or any(not retired.fullmatch(name) for name in deleted)):
        raise UnsafeFTPublication(
            "Unsealed FT output changes or unsafe deletions: "
            + repr(sorted((live_produced - sealed)
                          | {name for name in deleted if not retired.fullmatch(name)})[:8]))
    # The source payload is completely valid and immutable from this point on.
    publication_guard.verify(manifest)
    verify_files(baseline, root / "data/lab/ft-ledger.json")
    last_remote = None
    for attempt in range(1, max_attempts+1):
        git(root, "fetch", "--no-tags", "origin", "main")
        remote = sha(root, "FETCH_HEAD")
        if run(root, "merge-base", "--is-ancestor", base, remote, check=False).returncode:
            raise UnsafeFTPublication("Remote main no longer descends from the FT input base")
        allowed = allowed_remote_changes(root, base, remote, sealed, produced)
        if remote == base:
            candidate = source
        else:
            candidate = assemble(root, remote, source, produced)
        # Worktree reset is local only. A failing proof can NEVER be pushed.
        git(root, "reset", "--hard", candidate)
        publication_guard.verify(manifest)
        verify_files(baseline, root / "data/lab/ft-ledger.json")
        discovery_verify(["verify", "--root", str(root)])
        result = run(root, "push", "origin", "HEAD:refs/heads/main", check=False)
        if result.returncode == 0:
            print("FT_ATOMIC_PUBLISHED", json.dumps({
                "attempt": attempt, "remote_base": remote,
                "source_commit": source, "published_commit": candidate,
                "unrelated_paths": len(allowed), "sealed_files": len(sealed),
                "provider_requeries": 0}, sort_keys=True))
            return candidate
        last_remote = remote
        # Only an ordinary non-fast-forward race is retried. Other push errors
        # (auth, protection, hooks) are never silently hidden.
        err = result.stderr.decode("utf-8", "replace")
        if not any(x in err for x in ("non-fast-forward", "fetch first", "stale info")):
            raise UnsafeFTPublication("Push failed for reason other than a Git race: " + err[-300:])
        print("FT_REMOTE_RACE_RECHECK", attempt, "after", last_remote)
    raise UnsafeFTPublication("Remote advanced during all bounded FT publication attempts")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=6)
    args = parser.parse_args(argv)
    publish(args.root, base=args.base, manifest=args.manifest,
            baseline=args.baseline, max_attempts=args.max_attempts)


if __name__ == "__main__":
    main()

"""Telegram delivery state machine shared by the three-move and two-up notifiers.

States stored in a notification ledger entry (``entries[match_key]``):

  sent                              SENT_CONFIRMED - API returned a valid message_id. Terminal; never resent.
  delivery_uncertain_manual_review  DELIVERY_UNCERTAIN - network/timeout/5xx/no message_id, or a run that
                                    ended after the send started. Terminal; NEVER resent automatically.
  delivery_rejected                 DEFINITELY_REJECTED (retryable) - explicit 429/401/403. Waits for
                                    ``retry_not_before``; bounded attempts; only before kickoff.
  delivery_rejected_final           DEFINITELY_REJECTED (not retryable) - other 4xx, or attempts exhausted.
  expired_not_sent                  EXPIRED_NOT_SENT - the safe retry time is at/after kickoff, or the game
                                    started while the alert was suspended.
  send_in_progress                  Intent persisted before the HTTP call. Found by a later run it means the
                                    process ended mid-send: converted to uncertain, never resent.

Delivery guarantees (honest):
  * Default (workflow commits the ledger only at the end of the job): AT-LEAST-ONCE across jobs. If the
    job dies after Telegram accepted a message and before the ledger commit, the next job can resend.
  * With TG_DURABLE_INTENT=1 (opt-in; a push of the ledger BEFORE each send, a handful of tiny commits
    per day): AT-MOST-ONCE. A crash can lose an alert (flagged uncertain for manual review) but cannot
    duplicate it. Exactly-once is not claimable: Telegram offers no idempotency key.

The 429/401/403 pause lives in the shared ``telegram_block`` file, not in a ledger, so every notifier
that sends through ``bot.send_message`` honours it. Eligibility rules are not touched here.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from .bot import BotBlockedError, BotDeliveryError, BotRejectedError
from .telegram_block import BlockStore

SENT = "sent"
UNCERTAIN = "delivery_uncertain_manual_review"
IN_PROGRESS = "send_in_progress"
REJECTED = "delivery_rejected"
REJECTED_FINAL = "delivery_rejected_final"
EXPIRED = "expired_not_sent"

TERMINAL_RECEIPT_STATUSES = (SENT, UNCERTAIN, REJECTED_FINAL, EXPIRED)
MAX_FLOOD_ATTEMPTS = 6
MAX_AUTH_ATTEMPTS = 2
AUTH_PROBE_INTERVAL = timedelta(hours=24)
BACKOFF_BASE = timedelta(minutes=5)
BACKOFF_CAP = timedelta(hours=1)
RETRY_MARGIN = timedelta(seconds=1)
AUTH_DIAGNOSIS = "AUTH_REJECTED_CHECK_TG_BOT_TOKEN_AND_TG_CHAT_ID"


class IntentNotDurable(RuntimeError):
    """The pre-send intent could not be made durable; nothing was sent."""


def _utc(value):
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _bump(stats, name, n=1):
    stats[name] = stats.get(name, 0) + n


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def default_store():
    return BlockStore()


def blocked(store, moment):
    return store.active(moment)


def gate(ledger, key, kickoff, moment, stats):
    """Decide what to do with a game that may already have an entry: 'send' or 'skip'."""
    entry = ledger["entries"].get(key)
    if entry is None:
        return "send"
    status = entry.get("status")
    if status == IN_PROGRESS:
        ledger["entries"][key] = {**entry, "status": UNCERTAIN, "reason": "process_ended_during_send"}
        _bump(stats, "uncertain")
        return "skip"
    if status == REJECTED:
        if kickoff <= moment:
            ledger["entries"][key] = {**entry, "status": EXPIRED, "expired_at": _iso(moment),
                                      "reason": "game_started_before_safe_retry"}
            _bump(stats, "expired_not_sent")
            return "skip"
        due = _utc(entry.get("retry_not_before"))
        if due is not None and moment >= due:
            return "send"
        _bump(stats, "rejected_waiting")
        return "skip"
    _bump(stats, "already_notified")
    return "skip"


def sweep(ledger, moment, stats):
    """Close entries whose game is no longer a candidate: stale intents and expired retries."""
    for key, entry in list(ledger["entries"].items()):
        status = entry.get("status")
        if status == IN_PROGRESS:
            ledger["entries"][key] = {**entry, "status": UNCERTAIN, "reason": "process_ended_during_send"}
            _bump(stats, "uncertain")
        elif status == REJECTED:
            kickoff = _utc(entry.get("kickoff_utc"))
            if kickoff is None or kickoff <= moment:
                ledger["entries"][key] = {**entry, "status": EXPIRED, "expired_at": _iso(moment),
                                          "reason": "game_started_before_safe_retry"}
                _bump(stats, "expired_not_sent")


def _wait_for(exc, attempts):
    if exc.http_status == 429:
        if exc.retry_after is not None:
            return timedelta(seconds=exc.retry_after) + RETRY_MARGIN, "FLOOD_WAIT_RETRY_AFTER"
        wait = min(BACKOFF_BASE * (2 ** max(0, attempts - 1)), BACKOFF_CAP)
        return wait, "FLOOD_WAIT_CONSERVATIVE_BACKOFF"
    if exc.http_status in (401, 403):
        return AUTH_PROBE_INTERVAL, AUTH_DIAGNOSIS
    return None, None


def _after(persist, ledger, stats):
    """Post-outcome persistence: a publication failure is diagnosed loudly but never loses the
    in-memory outcome (the job's final commit step still stores it)."""
    if persist is None:
        return
    try:
        persist(ledger)
    except IntentNotDurable as exc:
        _bump(stats, "publish_failed")
        print("TELEGRAM_PUBLISH_FAILED", str(exc)[:160], file=sys.stderr)


def deliver(ledger, key, sender, message, base, sent_fields, clock, persist, stats, store=None):
    """Send at most once. Returns 'sent', 'continue' or 'stop' (shared block raised / intent failed)."""
    store = store or default_store()
    previous = ledger["entries"].get(key)
    attempts = int((previous or {}).get("attempts", 0)) + 1
    started = clock()
    # Persist the intent first: from here on a dead process can only yield UNCERTAIN, never a resend.
    ledger["entries"][key] = {**base, "status": IN_PROGRESS, "at": _iso(started), "attempts": attempts}
    if persist is not None:
        try:
            persist(ledger)
        except Exception as exc:
            if previous is None:
                ledger["entries"].pop(key, None)
            else:
                ledger["entries"][key] = previous
            _bump(stats, "intent_not_durable")
            print("TELEGRAM_INTENT_NOT_DURABLE", type(exc).__name__, str(exc)[:160], file=sys.stderr)
            return "stop"  # fail closed: never send what could not be recorded durably
    try:
        mid = sender(message)
        if isinstance(mid, bool) or not isinstance(mid, int):
            raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN: missing message ID")
    except BotRejectedError as exc:
        moment = clock()
        wait, diagnosis = _wait_for(exc, attempts)
        entry = {**base, "at": _iso(moment), "attempts": attempts, "http_status": exc.http_status}
        stop = False
        if wait is not None:
            store.record(moment + wait, exc.http_status, moment, diagnosis)
            stop = True
            entry["diagnosis"] = diagnosis
        limit = MAX_FLOOD_ATTEMPTS if exc.http_status == 429 else MAX_AUTH_ATTEMPTS
        kickoff = _utc(base.get("kickoff_utc"))
        if wait is None:
            entry.update(status=REJECTED_FINAL, reason="http_4xx_not_retryable")
        elif attempts >= limit:
            entry.update(status=REJECTED_FINAL, reason="attempts_exhausted")
        elif kickoff is not None and moment + wait >= kickoff:
            entry.update(status=EXPIRED, expired_at=_iso(moment), reason="retry_not_before_kickoff",
                         retry_not_before=_iso(moment + wait))
            _bump(stats, "expired_not_sent")
        else:
            entry.update(status=REJECTED, retry_not_before=_iso(moment + wait))
        ledger["entries"][key] = entry
        _bump(stats, "rejected")
        _after(persist, ledger, stats)
        return "stop" if stop else "continue"
    except BotBlockedError:
        # The shared pause was raised BEFORE any HTTP request: nothing is uncertain. Restore the state.
        if previous is None:
            ledger["entries"].pop(key, None)
        else:
            ledger["entries"][key] = previous
        _bump(stats, "blocked_before_http")
        _after(persist, ledger, stats)
        return "stop"
    except BotDeliveryError:
        ledger["entries"][key] = {**base, "status": UNCERTAIN, "at": _iso(clock()), "attempts": attempts}
        _bump(stats, "uncertain")
        _after(persist, ledger, stats)
        return "continue"
    ledger["entries"][key] = {**base, **sent_fields, "status": SENT, "telegram_message_id": mid,
                              "at": _iso(started), "attempts": attempts}
    _bump(stats, "sent")
    try:  # a confirmed send proves recovery: drop an EXPIRED pause record (never shorten an active one)
        if store.read() is not None and store.active(clock()) is None:
            store.clear()
    except ValueError:
        pass
    _after(persist, ledger, stats)
    return "sent"


def has_intent(ledger):
    return any(isinstance(e, dict) and e.get("status") == IN_PROGRESS for e in ledger.get("entries", {}).values())


def claim_guard(root, ledger_relpath):
    """Guard for git_publisher: refuse to publish an intent for a key the remote already holds.

    Two runs that both decide to alert the same game must not both send: whoever pushes the
    intent first owns the claim; the other sees the key on the remote and stops (fail closed).
    """
    import json
    from pathlib import Path

    def guard(remote_text):
        if not remote_text:
            return
        try:
            remote = json.loads(remote_text).get("entries", {})
            local = json.loads((Path(root) / ledger_relpath).read_text(encoding="utf-8")).get("entries", {})
        except (ValueError, OSError, AttributeError) as exc:
            raise IntentNotDurable("claim check unreadable: " + type(exc).__name__) from exc
        for key, entry in local.items():
            if not (isinstance(entry, dict) and entry.get("status") == IN_PROGRESS and key in remote):
                continue
            held = remote[key].get("status") if isinstance(remote[key], dict) else None
            if held != REJECTED:     # a retryable rejection is the legitimate predecessor of a retry
                raise IntentNotDurable("alert already claimed by another run: " + str(key)[:80])
    return guard


def git_publisher(root, relpaths, *, branch=None, retries=3, git=None, guard=None, guard_path=None,
                  message="data: telegram delivery state [skip ci]"):
    """Return ``publish()`` that commits+pushes the given paths (opt-in durable mode).

    `relpaths` is a list or a callable returning the paths to publish (a deleted block file is
    published as a deletion). Only those paths are committed (``commit -- paths``), so unrelated
    uncommitted work of the job (e.g. data/state.json) is never swept in. With `guard`, the remote
    copy of `guard_path` is fetched and checked before the first push and after every rejection
    (claim check). On a rejected push: fetch + ``rebase --autostash`` + push, bounded. Any failure
    raises IntentNotDurable.
    """
    def run(*args):
        if git is not None:
            return git(root, *args)
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout

    def remote_text(target):
        run("fetch", "origin", target)
        try:
            return run("show", "origin/%s:%s" % (target, guard_path))
        except subprocess.CalledProcessError:
            return ""

    def publish():
        paths = [str(x) for x in (relpaths() if callable(relpaths) else relpaths)]
        try:
            target = branch or run("rev-parse", "--abbrev-ref", "HEAD").strip()
            # Only paths that exist or are tracked (a deleted block file is a tracked deletion);
            # `git add` on a never-seen missing path would otherwise fail the whole publication.
            paths = [path for path in paths
                     if (os.path.exists(os.path.join(str(root), path)) or run("ls-files", "--", path).strip())]
            if not paths:
                return
            for path in paths:
                run("add", "-A", "--", path)
            if not run("diff", "--cached", "--name-only", "--", *paths).strip():
                return
            if guard is not None:
                guard(remote_text(target))
            run("-c", "user.name=github-actions[bot]",
                "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit", "-m", message, "--", *paths)
            for _ in range(retries):
                try:
                    run("push", "origin", "HEAD:refs/heads/" + target)
                    return
                except subprocess.CalledProcessError:
                    text = remote_text(target)
                    if guard is not None:
                        guard(text)
                    run("rebase", "--autostash", "origin/" + target)
            raise IntentNotDurable("push rejected after %d attempts" % retries)
        except subprocess.CalledProcessError as exc:
            raise IntentNotDurable("git failed: " + " ".join(str(exc.cmd[1:3]))) from exc
    return publish


def git_intent_publisher(root, relpath, **kwargs):
    """Backward-compatible alias: publish a single ledger path."""
    return git_publisher(root, [relpath], **kwargs)


def durable_paths(root, ledger_relpath):
    """Ledger plus the shared pause file (when it exists or was deleted and is tracked)."""
    paths = [str(ledger_relpath)]
    try:
        block = BlockStore().path.resolve().relative_to(os.path.realpath(root))
        paths.append(str(block))
    except ValueError:
        pass  # block file lives outside the checkout (tests): nothing to publish
    return paths


def durable_enabled():
    return os.environ.get("TG_DURABLE_INTENT") == "1"

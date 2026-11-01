"""Telegram delivery state machine shared by the three-move and two-up notifiers.

States stored in a notification ledger entry (``entries[match_key]``):

  sent                              SENT_CONFIRMED - API returned a valid message_id. Terminal; never resent.
  delivery_uncertain_manual_review  DELIVERY_UNCERTAIN - network/timeout/5xx/no message_id, or a crash after
                                    the send started. Terminal; NEVER resent automatically (duplicate guard).
  delivery_rejected                 DEFINITELY_REJECTED (retryable) - explicit 429/401/403. Waits for
                                    ``retry_not_before``; bounded by MAX_REJECTED_ATTEMPTS and by kickoff.
  delivery_rejected_final           DEFINITELY_REJECTED (not retryable) - other 4xx, or attempts exhausted.
  expired_not_sent                  EXPIRED_NOT_SENT - a rejected alert whose game started before a safe retry.
  send_in_progress                  Intent persisted just before the HTTP call. Found on a later run it means
                                    the process died mid-send: it is converted to uncertain, never resent.

A ``delivery_block`` object at ledger level pauses every send after 429 (retry_after) or 401/403.
Eligibility rules are not touched here. Transient states are not published as receipts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .bot import BotDeliveryError, BotRejectedError

SENT = "sent"
UNCERTAIN = "delivery_uncertain_manual_review"
IN_PROGRESS = "send_in_progress"
REJECTED = "delivery_rejected"
REJECTED_FINAL = "delivery_rejected_final"
EXPIRED = "expired_not_sent"

TERMINAL_RECEIPT_STATUSES = (SENT, UNCERTAIN, REJECTED_FINAL, EXPIRED)
MAX_REJECTED_ATTEMPTS = 3
AUTH_BLOCK = timedelta(hours=6)
DEFAULT_RETRY_AFTER = timedelta(minutes=5)
MAX_RETRY_AFTER = timedelta(hours=6)


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


def blocked(ledger, moment):
    block = ledger.get("delivery_block")
    until = _utc(block.get("until")) if isinstance(block, dict) else None
    return block if until is not None and moment < until else None


def gate(ledger, key, kickoff, moment, stats):
    """Decide what to do with a game that may already have an entry.

    Returns 'send' (go on), or 'skip'. May rewrite a stale entry in place.
    """
    entry = ledger["entries"].get(key)
    if entry is None:
        return "send"
    status = entry.get("status")
    if status == IN_PROGRESS:
        ledger["entries"][key] = {**entry, "status": UNCERTAIN,
                                  "reason": "process_ended_during_send"}
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


def deliver(ledger, key, sender, message, base, sent_fields, clock, persist, stats):
    """Send once. Returns 'sent', 'continue' or 'stop' (global block raised)."""
    previous = ledger["entries"].get(key) or {}
    attempts = int(previous.get("attempts", 0)) + 1
    started = clock()
    # Persist the intent first: a crash from here on can only yield UNCERTAIN, never a resend.
    ledger["entries"][key] = {**base, "status": IN_PROGRESS, "at": _iso(started), "attempts": attempts}
    if persist is not None:
        persist(ledger)
    try:
        mid = sender(message)
        if isinstance(mid, bool) or not isinstance(mid, int):
            raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN: missing message ID")
    except BotRejectedError as exc:
        moment = clock()
        retryable = exc.http_status in (429, 401, 403) and attempts < MAX_REJECTED_ATTEMPTS
        entry = {**base, "at": _iso(moment), "attempts": attempts, "http_status": exc.http_status}
        if exc.http_status == 429:
            wait = timedelta(seconds=exc.retry_after) if exc.retry_after is not None else DEFAULT_RETRY_AFTER
            wait = min(wait, MAX_RETRY_AFTER)
        elif exc.http_status in (401, 403):
            wait = AUTH_BLOCK
        else:
            wait = None
        if exc.http_status in (429, 401, 403) and wait is not None:
            ledger["delivery_block"] = {"until": _iso(moment + wait), "http_status": exc.http_status,
                                        "set_at": _iso(moment)}
        if retryable:
            entry.update(status=REJECTED, retry_not_before=_iso(moment + wait))
        else:
            entry.update(status=REJECTED_FINAL,
                         reason="attempts_exhausted" if exc.http_status in (429, 401, 403) else "http_4xx_not_retryable")
        ledger["entries"][key] = entry
        _bump(stats, "rejected")
        if persist is not None:
            persist(ledger)
        return "stop" if exc.http_status in (429, 401, 403) else "continue"
    except BotDeliveryError:
        ledger["entries"][key] = {**base, "status": UNCERTAIN, "at": _iso(clock()), "attempts": attempts}
        _bump(stats, "uncertain")
        if persist is not None:
            persist(ledger)
        return "continue"
    ledger["entries"][key] = {**base, **sent_fields, "status": SENT, "telegram_message_id": mid,
                              "at": _iso(started), "attempts": attempts}
    ledger.pop("delivery_block", None)  # a confirmed send proves the credentials/limit recovered
    _bump(stats, "sent")
    if persist is not None:
        persist(ledger)
    return "sent"

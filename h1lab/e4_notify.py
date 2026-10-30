"""Telegram-only E4 watch: isolated versus combined with other V5 signals.

Reuses the unchanged V5 evidence and 12-hour pre-kickoff eligibility engine.
No other strategy generates a Telegram notification or a receipt here.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .bot import BotDeliveryError, configured, send_message
from .strategy_notify import (
    MAX_ALERT_LOOKAHEAD, ROOT, RESEARCH, STRATEGIES, _exit_reason,
    _short_history, _write, candidate_matches,
)
from .timeline import collect_timelines, read_sources, utc

LEDGER = Path("data/e4-notifications.json")
SCHEMA_VERSION = 1
RULE_VERSION = "E4_SOLO_COMBINED_20261030"
E4 = next(s for s in STRATEGIES if s["number"] == 4)


def classification(row):
    """One E4 result only, with *other* V5 rules used solely as context."""
    e4 = next((r for r in row["rules"] if r["number"] == 4), None)
    if e4 is None:
        return None
    partners = sorted(r["number"] for r in row["rules"] if r["number"] != 4)
    return {"kind": "COMBINADA" if partners else "ISOLADA",
            "partners": partners, "rule": e4}


def message_for_game(row, current, action, reason=None):
    kickoff = utc(row["kickoff_utc"])
    if kickoff is None or not row.get("match_label"):
        raise ValueError("invalid E4 Telegram game")
    when = kickoff.astimezone(ZoneInfo("Europe/Lisbon")).strftime("%d/%m %H:%M")
    if action == "withdrawn":
        lines = ["❌ SAIU DA E4 · OVER 2,5", "⚽ " + row["match_label"],
                 "🕒 " + when + " (Portugal)",
                 "🔎 " + (reason or "sinal E4 retirado com nova evidência")]
    else:
        kind = current["kind"]
        symbol = "🟢" if kind == "ISOLADA" else "🟣"
        title = symbol + " E4 " + kind + " · OVER 2,5"
        if action == "changed":
            title = "🔄 AGORA " + title
        elif action == "reentered":
            title = "↩️ REGRESSOU " + title
        lines = [title, "⚽ " + row["match_label"],
                 "🕒 " + when + " (Portugal)",
                 "🔎 Total ≥3,25; sem enfraquecimento do último episódio"]
        if current["partners"]:
            lines.append("➕ Também detetadas: " +
                         ", ".join("E" + str(n) for n in current["partners"]))
        lines.append("📊 " + _short_history(current["rule"]).removeprefix("📊 "))
        lines.append("🧪 29/10, amostra pequena: " +
                     ("5/6 isolada" if kind == "ISOLADA" else "1/1 combinada"))
    msg = "\n".join(lines)
    if len(msg.encode("utf-8")) > 4096:
        raise ValueError("E4 Telegram message exceeds 4096 bytes")
    return msg


def empty_ledger(now):
    return {"schema_version": SCHEMA_VERSION, "rule_version": RULE_VERSION,
            "activated_at": now.isoformat(timespec="seconds"), "entries": {}}


def _pending_action(row, receipt):
    current = classification(row)
    status = receipt.get("status") if isinstance(receipt, dict) else None
    if current:
        if status is None:
            return "entered", current, None
        if status == "withdrawn":
            return "reentered", current, None
        if status == "sent" and receipt.get("kind") != current["kind"]:
            return "changed", current, None
        # An uncertain delivery must be checked manually, never resent by cron.
        return None, current, None
    if status == "sent":
        reason = _exit_reason(row, E4, receipt)
        if reason:
            return "withdrawn", None, reason
    return None, None, None


def process(rows, ledger, now, sender, enabled, pace=None, clock=None):
    if (not isinstance(ledger, dict) or
            ledger.get("schema_version") != SCHEMA_VERSION or
            ledger.get("rule_version") != RULE_VERSION or
            not isinstance(ledger.get("entries"), dict)):
        raise ValueError("invalid E4 receipt ledger: no Telegram messages sent")
    stats = {"e4_eligible_12h": 0, "e4_isolated": 0, "e4_combined": 0,
             "games_sent": 0, "withdrawals_sent": 0, "category_changes_sent": 0,
             "already_notified": 0, "unconfigured": 0, "failed": 0, "expired": 0}
    attempts = 0
    for row in sorted(rows, key=lambda r: (r["kickoff_utc"], r["match_key"])):
        kickoff = utc(row.get("kickoff_utc"))
        if kickoff is None or kickoff <= now:
            continue
        if kickoff > now + MAX_ALERT_LOOKAHEAD:
            continue
        key = row["match_key"] + "|4"
        receipt = ledger["entries"].get(key)
        action, current, reason = _pending_action(row, receipt)
        if current:
            stats["e4_eligible_12h"] += 1
            stats["e4_isolated" if current["kind"] == "ISOLADA" else "e4_combined"] += 1
        if action is None:
            if current:
                stats["already_notified"] += 1
            continue
        if not enabled:
            stats["unconfigured"] += 1
            continue
        if clock is not None and kickoff <= clock():
            stats["expired"] += 1
            continue
        if attempts and pace is not None:
            pace()  # Unlimited matches; pace against Telegram rate limits.
        if clock is not None and kickoff <= clock():
            stats["expired"] += 1
            continue
        msg = message_for_game(row, current, action, reason)
        attempts += 1
        stamp = now.isoformat(timespec="seconds")
        try:
            mid = sender(msg)
            if isinstance(mid, bool) or not isinstance(mid, int):
                raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN: missing message ID")
        except BotDeliveryError:
            # Prevent unbounded duplicate retries if Telegram may have accepted it.
            item = receipt.copy() if isinstance(receipt, dict) else {}
            item.update({"status": "delivery_uncertain_manual_review",
                         "last_attempt_at": stamp, "attempted_action": action})
            ledger["entries"][key] = item
            stats["failed"] += 1
            continue
        item = receipt.copy() if isinstance(receipt, dict) else {}
        item.update({"status": "withdrawn" if action == "withdrawn" else "sent",
                     "kind": current["kind"] if current else item.get("kind"),
                     "partners": current["partners"] if current else item.get("partners", []),
                     "observed_through": row["observed_through"],
                     "match_key": row["match_key"], "kickoff_utc": row["kickoff_utc"],
                     "rule_id": E4["id"], "rule_version": RULE_VERSION,
                     "telegram_message_id": mid, "last_action_at": stamp})
        item.setdefault("transitions", []).append(
            {"action": action, "at": stamp, "telegram_message_id": mid,
             **({"reason": reason} if reason else {})})
        ledger["entries"][key] = item
        stats["games_sent"] += 1
        if action == "withdrawn":
            stats["withdrawals_sent"] += 1
        if action == "changed":
            stats["category_changes_sent"] += 1
    return ledger, stats


def _rows(root, now):
    research = json.loads((root / RESEARCH).read_text(encoding="utf-8"))
    alerts, markets, errors = read_sources(root)
    alerts = [a for a in alerts if utc(a.get("observed_at")) and utc(a["observed_at"]) <= now]
    markets = [a for a in markets if utc(a.get("observed_at")) and utc(a["observed_at"]) <= now]
    timelines, issues, excluded = collect_timelines(alerts, markets, source_errors=errors)
    return candidate_matches(timelines, now, research, include_all=True), len(issues), len(excluded)


def run(root=ROOT, now=None, sender=send_message, bot_enabled=None):
    root = Path(root)
    real_clock = now is None
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows, issues, excluded = _rows(root, now)
    path = root / LEDGER
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_ledger(now)
    ledger, stats = process(rows, ledger, now, sender,
                            configured() if bot_enabled is None else bot_enabled,
                            pace=lambda: time.sleep(1.2),
                            clock=lambda: datetime.now(timezone.utc) if real_clock else now)
    _write(path, ledger)
    print("MASTER_BRAIN_E4_ONLY_NOTIFY", stats, "timeline_issues", issues,
          "excluded_observations", excluded, "receipts", len(ledger["entries"]))
    return ledger


def preview(root=ROOT, now=None):
    root = Path(root)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows, issues, excluded = _rows(root, now)
    path = root / LEDGER
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_ledger(now)
    eligible = [r for r in rows if classification(r) and
                now < utc(r["kickoff_utc"]) <= now + MAX_ALERT_LOOKAHEAD]
    pending = []
    for r in eligible:
        action, current, _ = _pending_action(r, ledger["entries"].get(r["match_key"] + "|4"))
        if action:
            pending.append((r, current, action))
    print("MASTER_BRAIN_E4_ONLY_DRY_RUN", "eligible_12h", len(eligible),
          "pending_12h", len(pending), "timeline_issues", issues, "excluded", excluded)
    for row, current, action in pending:
        print("MATCH", row["match_label"], row["kickoff_utc"],
              current["kind"] if current else action,
              "partners", current["partners"] if current else [])
    return eligible


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="no messages, no receipts")
    args = parser.parse_args()
    if args.dry_run:
        preview()
    else:
        run()

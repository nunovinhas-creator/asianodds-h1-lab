"""Send prospective MASTER BRAIN observations, never H1 tickets or betting picks.

Only the strict pre-kickoff V5 watch condition qualifies. This delivery ledger is
separate from the immutable Pattern Watch first-seen research registry.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .bot import BotDeliveryError, configured, send_message
from .pattern_watch import inspect, utc
from .timeline import collect_timelines, read_sources

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("data/pattern-notifications.json")
RESEARCH_HISTORY = Path("data/lab/pattern-watch-first-seen.json")
SCHEMA = 1

CATEGORY_LABELS = {
    "RISING_EACH_EPISODE": "golos implícitos a subir em todos os episódios",
    "RISING_WITH_FLAT": "subidas e estabilidade sem queda significativa",
    "FLAT_EACH_EPISODE": "golos implícitos sem variação significativa",
}


def _total_line(value):
    """Format the real Asian Total line in Portuguese; do not estimate it."""
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or abs(value * 4 - round(value * 4)) > 1e-7):
        raise ValueError("missing or invalid Total line in the observed snapshot")
    return ("%0.2f" % value).rstrip("0").rstrip(".").replace(".", ",")


def message_for_pattern(row):
    """Describe observed movements and latest O/U line; not an Over 2.5 pick."""
    if not row.get("strict_condition") or row.get("category") not in CATEGORY_LABELS:
        raise ValueError("not a strict prospective pattern")
    last_line = _total_line(row.get("total_line_after"))
    previous_line = _total_line(row.get("total_line_before"))
    movement = ("🔁 Último movimento da linha: " + previous_line + " → " + last_line
                if previous_line != last_line else "🔁 Linha inalterada no último alerta")
    kickoff = utc(row["kickoff_utc"])
    deltas = ["%+.3f" % obs["delta_lambda"] for obs in row["observations"]]
    return "\n".join([
        "🧠 MASTER BRAIN — PADRÃO EM OBSERVAÇÃO",
        "⚽ " + row["match_label"],
        "🕒 Início: " + kickoff.strftime("%d/%m/%Y %H:%M UTC"),
        "⚽ Linha de golos Total (Over/Under): " + last_line + " (último alerta observado)",
        movement,
        "🔎 Múltiplos alertas sem qualquer queda significativa (exclui Δλ ≤ −0,05).",
        "📊 " + str(row["messages"]) + " alertas / " + str(row["episodes"]) + " episódios independentes",
        "📈 " + CATEGORY_LABELS[row["category"]],
        "Δλ observados: " + ", ".join(deltas),
        "🧪 Hipótese exploratória relativa a Over 2,5. NÃO validada; não é uma aposta nem recomendação.",
        "🔗 https://nunovinhas-creator.github.io/asianodds-h1-lab/lab-pattern-watch.html",
    ])


def new_ledger(rows, past_keys, now):
    """Baseline existing candidates/history so activation never spams old matches."""
    suppressed = set(past_keys) | {r["match_key"] for r in rows}
    return {
        "schema_version": SCHEMA,
        "bootstrapped_at": now.isoformat(timespec="seconds"),
        "entries": {key: {"status": "suppressed_at_activation"} for key in sorted(suppressed)},
    }


def process(rows, ledger, now, sender, enabled):
    """One first alert per match, no retry after uncertain delivery.

    'enabled=False' (missing bot configuration) never consumes a fresh match.
    """
    if ledger.get("schema_version") != SCHEMA or not isinstance(ledger.get("entries"), dict):
        raise ValueError("invalid MASTER BRAIN Telegram receipt ledger")
    baseline = utc(ledger.get("bootstrapped_at"))
    if baseline is None:
        raise ValueError("invalid MASTER BRAIN Telegram activation timestamp")
    stats = {"eligible": len(rows), "sent": 0, "failed": 0, "skipped": 0, "unconfigured": 0}
    for row in sorted(rows, key=lambda r: (r["kickoff_utc"], r["match_key"])):
        key = row["match_key"]
        # Restrict to events known only after activation, before kickoff.
        if key in ledger["entries"] or utc(row["last_alert_at"]) <= baseline:
            stats["skipped"] += 1
            continue
        if not enabled:
            stats["unconfigured"] += 1
            continue
        # Never send a pattern alert if its actual Total line is absent or malformed.
        # Keep it eligible for a later cycle instead of fabricating a price/line.
        try:
            message = message_for_pattern(row)
        except ValueError:
            stats.setdefault("missing_total_line", 0)
            stats["missing_total_line"] += 1
            continue
        detail = {
            "status": "delivery_uncertain", "detected_at": now.isoformat(timespec="seconds"),
            "kickoff_utc": row["kickoff_utc"], "category": row["category"],
            "observed_through": row["last_alert_at"], "episodes": row["episodes"],
            "event_ids": [o["event_id"] for o in row["observations"]],
            "rule": "PATTERN_WATCH_STRICT_V1",
        }
        # Mark in-memory before sending. The workflow commits after delivery.
        ledger["entries"][key] = detail
        try:
            message_id = sender(message)
            if not isinstance(message_id, int) or isinstance(message_id, bool):
                raise BotDeliveryError("TELEGRAM_DELIVERY_UNCERTAIN: missing message ID")
            detail["status"] = "sent"
            detail["telegram_message_id"] = message_id
            stats["sent"] += 1
        except BotDeliveryError:
            # Unknown delivery => manual review; no automatic duplicate sends.
            detail["status"] = "delivery_uncertain_manual_review"
            stats["failed"] += 1
    return ledger, stats


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def run(root=ROOT, now=None, sender=send_message, bot_enabled=None):
    root = Path(root)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    alerts, markets, errors = read_sources(root)
    timelines, issues, excluded = collect_timelines(alerts, markets, source_errors=errors)
    rows = [row for timeline in timelines if (row := inspect(timeline, now)) and row["strict_condition"]]
    path = root / LEDGER
    if not path.exists():
        history_path = root / RESEARCH_HISTORY
        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {}
        prior_keys = [e["match_key"] for e in history.get("entries", [])]
        ledger = new_ledger(rows, prior_keys, now)
        _write(path, ledger)
        print("MASTER_BRAIN_NOTIFY_BOOTSTRAPPED", "suppressed_existing", len(ledger["entries"]))
        return ledger
    ledger = json.loads(path.read_text(encoding="utf-8"))
    ledger, stats = process(rows, ledger, now, sender, configured() if bot_enabled is None else bot_enabled)
    _write(path, ledger)
    print("MASTER_BRAIN_PATTERN_NOTIFY", stats, "timeline_issues", len(issues),
          "excluded_observations", len(excluded))
    return ledger


if __name__ == "__main__":
    run()

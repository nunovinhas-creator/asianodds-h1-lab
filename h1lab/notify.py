"""Notify H1 triples to an explicitly configured Telegram bot chat.

Receiving channel uses a separate read account (TG_SESSION); delivery is via
TG_BOT_TOKEN and TG_CHAT_ID only. No automatic Saved Messages fallback.
"""
import os
from datetime import datetime, timezone

from .bot import configured, send_message
from .cli import read_state, save


def message_for_ticket(ticket, signals):
    lines = ["🧪 ASIANODDS H1 — TRIPLA SIMULADA", ticket["ticket_id"]]
    for i, signal in enumerate(signals, 1):
        lines.extend([
            str(i) + ". " + signal["home"] + " – " + signal["away"],
            "Under " + str(signal["line"]) + " | odd " + str(signal["under_odds"])
            + " | início " + signal["kickoff_utc"][:16].replace("T", " ") + " UTC",
        ])
    lines += [
        "Odd teórica da tripla: " + str(ticket["theoretical_odds"]),
        "Simulação, não é uma aposta executada. Odds não confirmadas em tempo real.",
    ]
    return "\n".join(lines)


def run():
    state = read_state()
    # A legacy receipt for Telegram Saved Messages is not a bot-chat receipt.
    pending = [t for t in state["tickets"] if not t.get("bot_notified_at")]
    if not pending:
        print("No pending bot-chat triple notifications")
        return
    if not configured():
        print("NOTIFY_SETUP_REQUIRED: configure TG_BOT_TOKEN and TG_CHAT_ID "
              "for bot-chat notifications; existing tickets remain pending.")
        return
    signals = {s["signal_id"]: s for s in state["signals"]}
    for ticket in pending:
        legs = [signals[sid] for sid in ticket["signal_ids"]]
        if min(datetime.fromisoformat(s["kickoff_utc"]) for s in legs) <= datetime.now(timezone.utc):
            ticket["bot_notified_at"] = "EXPIRED"
            ticket["bot_notification_status"] = "expired_before_delivery"
            save(state)
            print("Expired bot-chat triple before delivery", ticket["ticket_id"])
            continue
        message_id = send_message(message_for_ticket(ticket, legs))
        ticket["bot_message_id"] = message_id
        ticket["bot_notified_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ticket["bot_notification_status"] = "sent"
        save(state)
        print("BOT_SENT", ticket["ticket_id"])


if __name__ == "__main__":
    run()

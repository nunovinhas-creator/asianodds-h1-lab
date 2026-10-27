"""Send each new triple to the account's own Saved Messages; no bot required."""
import asyncio
import os
from datetime import datetime, timezone
from .cli import read_state,save

async def run():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    state=read_state()
    pending=[t for t in state["tickets"] if not t.get("notified_at")]
    if not pending:
        print("No pending triple notifications")
        return
    keys=("TG_API_ID","TG_API_HASH","TG_SESSION")
    if any(not os.environ.get(k) for k in keys):
        print("SETUP_REQUIRED: Telegram account not configured")
        return
    signals={s["signal_id"]:s for s in state["signals"]}
    target=os.getenv("TG_OUTPUT_CHAT","me")
    async with TelegramClient(StringSession(os.environ["TG_SESSION"]),
                              int(os.environ["TG_API_ID"]),os.environ["TG_API_HASH"]) as client:
        for t in pending:
            ss=[signals[x] for x in t["signal_ids"]]
            # Never send a late "new triple" after one of its matches has started.
            if min(datetime.fromisoformat(s["kickoff_utc"]) for s in ss)<=datetime.now(timezone.utc):
                t["notified_at"]="EXPIRED"
                t["notification_status"]="missed_before_delivery"
                save(state)
                print("Expired without alert",t["ticket_id"])
                continue
            lines=["🧪 ASIANODDS H1 — TRIPLA SIMULADA",t["ticket_id"]]
            for i,s in enumerate(ss,1):
                lines.extend([str(i)+". "+s["home"]+" – "+s["away"],
                     "Under "+str(s["line"])+" | odd "+str(s["under_odds"])+
                     " | início "+s["kickoff_utc"][:16].replace("T"," ")+" UTC"])
            lines.extend(["Odd teórica da tripla: "+str(t["theoretical_odds"]),
                           "Simulação, não é uma aposta executada. Odds não confirmadas em tempo real."])
            await client.send_message(target,"\n".join(lines),link_preview=False)
            t["notified_at"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
            save(state)
            print("Sent",t["ticket_id"])

if __name__=="__main__": asyncio.run(run())

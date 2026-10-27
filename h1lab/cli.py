"""Poll an already-subscribed Telegram channel; commit structured market observations."""
import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .core import empty_state,parse_alert,classify_message,incorporate,public_data,load_results,dump_json

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/"data/state.json"

def read_state():
    if not STATE.exists(): return empty_state()
    value=json.loads(STATE.read_text(encoding="utf-8"))
    for k,v in empty_state().items(): value.setdefault(k,v)
    return value

def save(state):
    dump_json(STATE,state)
    dump_json(ROOT/"docs/data.json",public_data(state,load_results(ROOT/"data/results.csv"),datetime.now(timezone.utc)))

def observe_shadow(text, when, message_id, channel_id, legacy_parsed, rows, market_rows=None, legacy_event=None):
    """Nonfatal observer; never changes H1 decisions."""
    try:
        from .shadow_formats import inspect
        rows.append(inspect(text, when, message_id, channel_id, legacy_parsed))
    except Exception as exc:
        print("LAB_SHADOW_INSPECT_FAILED:", type(exc).__name__)

def observe_market_v4(text, when, message_id, channel_id, legacy_event, market_rows):
    """Independent parser; any failure is confined to shadow mode."""
    try:
        from .market_v4 import parse
        result=parse(text,when,message_id,channel_id,legacy_event)
        if result: market_rows.append(result)
    except Exception as exc:
        print("LAB_MARKET_V4_INSPECT_FAILED:",type(exc).__name__)

def persist_market_v4(rows):
    try:
        from .market_v4 import store
        store(ROOT, rows)
    except Exception as exc:
        print("LAB_MARKET_V4_STORE_FAILED:",type(exc).__name__)

def persist_shadow(rows):
    """Nonfatal persistence; failures cannot interrupt Telegram collection."""
    try:
        from .shadow_formats import store
        store(ROOT, rows)
    except Exception as exc:
        print("LAB_SHADOW_STORE_FAILED:", type(exc).__name__)

async def poll(state):
    from telethon import TelegramClient
    from .session import load_telegram_session
    async with TelegramClient(load_telegram_session(),
                               int(os.environ["TG_API_ID"]),os.environ["TG_API_HASH"],
                               receive_updates=False) as client:
        wanted=os.environ["TG_CHANNEL"].strip()
        if wanted.startswith("@"):
            entity=await client.get_entity(wanted)
        else:
            dialogs=[d async for d in client.iter_dialogs()]
            matches=[d.entity for d in dialogs if str(d.id)==wanted or d.name==wanted]
            if len(matches)!=1: raise RuntimeError("TG_CHANNEL is not an unambiguous subscribed channel")
            entity=matches[0]
        allowed_triggers={"manual","push","github-schedule","cloudflare-cron","workflow_dispatch"}
        trigger=os.environ.get("COLLECT_TRIGGER","unknown")
        if trigger not in allowed_triggers:
            trigger="unknown"
        print("COLLECT_TRIGGER:",trigger)
        last=int(state["last_id"])
        if last==0 and not state["alerts"]:
            # At deployment do NOT replay historical messages into prospective bets.
            newest=await client.get_messages(entity,limit=1)
            state["last_id"]=newest[0].id if newest else 0
            state["collector"]={"last_poll_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "last_batch_new_messages":0,"batch_limit_hit":False,"trigger_source":trigger}
            save(state)
            print("BOOTSTRAPPED: monitoring new messages after ID",state["last_id"])
            return
        original_last=last
        previous_tickets=len(state["tickets"])
        diagnostics=state.setdefault("diagnostics",[])
        diagnosed={d["message_id"] for d in diagnostics}
        parsed=[]
        shadow_rows=[]
        market_v4_rows=[]
        inspected=0
        new_messages=0
        fresh_diagnostics=[]
        batch_limit=1500
        # Revisit exactly the previous checkpoint, which may have been
        # skipped by an older parser. Keep duplicate protection in incorporate.
        async for msg in client.iter_messages(entity,min_id=max(0,last-1),reverse=True,limit=batch_limit):
            inspected+=1
            if msg.id>original_last:
                new_messages+=1
            last=max(last,msg.id)
            raw_text=msg.raw_text or ""
            # AsianOdds links are often Telegram text-url entities, not visible text.
            links=[getattr(item,"url","") for item in (msg.entities or [])]
            links=[url for url in links if url and "asianodds.com" in url]
            combined=raw_text+"\n"+"\n".join(links)
            event=parse_alert(combined,msg.date,msg.id,str(entity.id))
            observe_shadow(combined,msg.date,msg.id,str(entity.id),event is not None,shadow_rows)
            observe_market_v4(combined,msg.date,msg.id,str(entity.id),event,market_v4_rows)
            if event:
                parsed.append(event)
            elif msg.id not in diagnosed:
                reason=classify_message(combined)
                diagnostic={"message_id":msg.id,"seen_at":msg.date.isoformat(),"reason":reason}
                diagnostics.append(diagnostic)
                fresh_diagnostics.append(diagnostic)
                diagnosed.add(msg.id)
        # Shadow persistence is best effort and never affects H1 state/checkpoints.
        persist_shadow(shadow_rows)
        persist_market_v4(market_v4_rows)
        # Remove obsolete parse errors for messages now successfully recovered.
        recovered_ids={event["message_id"] for event in parsed}
        if recovered_ids:
            diagnostics[:]=[d for d in diagnostics if d["message_id"] not in recovered_ids]
            diagnosed.difference_update(recovered_ids)
        state["diagnostics"]=diagnostics[-200:]
        now=datetime.now(timezone.utc)
        added=incorporate(state,parsed,now)
        state["last_id"]=last
        last_saved_poll=state.get("collector",{}).get("last_poll_at")
        heartbeat_due=(not last_saved_poll or
            datetime.fromisoformat(last_saved_poll)<now-timedelta(minutes=45))
        batch_limit_hit=inspected>=batch_limit
        if new_messages or heartbeat_due or batch_limit_hit:
            state["collector"]={
                "last_poll_at":now.isoformat(timespec="seconds"),
                "last_batch_new_messages":new_messages,
                "last_batch_parsed":added,
                "trigger_source":trigger,
                "batch_limit_hit":batch_limit_hit,
                "telegram_last_id":last}
        if last!=original_last or len(state["tickets"])!=previous_tickets or fresh_diagnostics or recovered_ids or added or heartbeat_due:
            save(state)
        print("Inspected:",inspected,"new Telegram messages:",new_messages,
              "new structured alerts:",added,
              "new unparsed diagnostics:",len(fresh_diagnostics),
              "H1 signals:",len(state["signals"]),"triples:",len(state["tickets"]))
        if batch_limit_hit:
            print("BACKLOG: batch limit reached; subsequent polls resume from Telegram ID",last)
        for diagnostic in fresh_diagnostics:
            print("UNPARSED id=",diagnostic["message_id"],
                  "reason=",diagnostic["reason"])

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("collect","render"))
    args=p.parse_args()
    state=read_state()
    if args.action=="collect":
        names=("TG_API_ID","TG_API_HASH","TG_SESSION","TG_CHANNEL")
        missing=[name for name in names if not os.environ.get(name)]
        if missing:
            print("SETUP_REQUIRED: configure "+", ".join(missing))
            return
        asyncio.run(poll(state))
    else: save(state)

if __name__=="__main__": main()

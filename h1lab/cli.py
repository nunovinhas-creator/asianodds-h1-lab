"""Poll an already-subscribed Telegram channel; commit structured market observations."""
import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from .core import empty_state,parse_alert,incorporate,public_data,load_results,dump_json

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

async def poll(state):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    async with TelegramClient(StringSession(os.environ["TG_SESSION"]),
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
        last=state["last_id"]
        parsed=[];seen=0
        async for msg in client.iter_messages(entity,min_id=last,reverse=True,limit=500):
            seen+=1;last=max(last,msg.id)
            if msg.raw_text:
                ev=parse_alert(msg.raw_text,msg.date,msg.id,str(entity.id))
                if ev: parsed.append(ev)
        added=incorporate(state,parsed,datetime.now(timezone.utc))
        state["last_id"]=last
        save(state)
        print("Read:",seen,"new structured alerts:",added,
              "H1 signals:",len(state["signals"]),"triples:",len(state["tickets"]))

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
            save(state)
            return
        asyncio.run(poll(state))
    else: save(state)

if __name__=="__main__": main()

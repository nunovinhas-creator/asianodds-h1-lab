"""AsianOdds H1: structured parsing, frozen picks, Asian settlement and ROI."""
import csv
import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

UTC=timezone.utc
NUM=r"[+-]?\d+(?:[.,]\d+)?"
# Source posts may attach move indicators directly to a number (e.g. 1.79🔴).
# Match Was/Now on whole lines, then extract exactly 3 numeric columns.
ROW=re.compile(r"(?m)^[ \t]*(Was|Now)[ \t]+([^\r\n]+)",re.I)

def odds_rows(text):
    values=[]
    for label, tail in ROW.findall(text):
        tokens=re.findall(NUM,tail)
        if len(tokens)!=3:
            continue
        nums=[float(token.replace(",",".")) for token in tokens]
        values.append((label.lower(),*nums))
    return values
KICK=re.compile(r"🕒\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2}:\d{2})\s+UTC",re.I)
MONTHS={m:i+1 for i,m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}

def iso(t):
    return t.astimezone(UTC).isoformat(timespec="seconds")

def kickoff(text,observed):
    m=KICK.search(text)
    if not m or m.group(2).title() not in MONTHS:
        return None
    hr,mi=map(int,m.group(3).split(":"))
    opts=[]
    for y in (observed.year-1,observed.year,observed.year+1):
        try: opts.append(datetime(y,MONTHS[m.group(2).title()],int(m.group(1)),hr,mi,tzinfo=UTC))
        except ValueError: pass
    return min(opts,key=lambda t:abs((t-observed).total_seconds())) if opts else None

def parse_alert(text,when,msg_id,channel_id="asianodds"):
    when=when.astimezone(UTC)
    line=next((s.strip() for s in text.splitlines() if " vs " in s),"")
    if not line: return None
    line=re.sub(r"^.*?Dropping Odds:\s*","",line)
    line=re.sub(r"^[^\w]+","",line)
    home,away=[s.strip() for s in line.split(" vs ",1)]
    if not home or not away: return None
    ko=kickoff(text,when)
    if not ko: return None
    r=re.search(r"🏆\s*([^\n]+)",text)
    comp=r.group(1).strip() if r else ""
    u=re.search(r"https?://(?:www\.)?asianodds\.com/[^\s)]+",text)
    url=u.group(0).rstrip(".,") if u else ""
    fixture=parse_qs(urlparse(url).query).get("match",[None])[0] if url else None
    key=fixture or ko.strftime("%Y-%m-%d")+"|"+home.casefold()+"|"+away.casefold()
    market="total" if re.search(r"\bTotal:\s*"+NUM+r"\s*[↑↓]\s*"+NUM,text) else "1x2" if "1x2" in text else "unknown"
    rows=odds_rows(text)
    # The last table is always Total, also in 1x2 channel messages.
    w=next((x for x in reversed(rows) if x[0]=="was"),None)
    n=next((x for x in reversed(rows) if x[0]=="now"),None)
    if not w or not n: return None
    ev={"event_id":str(channel_id)+":"+str(msg_id),"message_id":msg_id,
        "observed_at":iso(when),"kickoff_utc":iso(ko),"match_key":key,
        "home":home,"away":away,"competition":comp,"market":market,
        "source_url":url,"total_before":w[1],"over_before":w[2],"under_before":w[3],
        "total_after":n[1],"over_after":n[2],"under_after":n[3]}
    if market=="1x2":
        selections={}
        for label in ("1","X","2"):
            mm=re.search(r"(?m)^\s*"+label+r"\s+("+NUM+r"|[-–])\s*→\s*("+NUM+r"|[-–])",text)
            if mm:
                selections[label]={"before":None if mm.group(1) in ("-","–") else float(mm.group(1).replace(",",".")),
                                   "after":None if mm.group(2) in ("-","–") else float(mm.group(2).replace(",","."))}
        ev["one_x_two"]=selections
        if len(rows)>=4:
            ah_before,ah_after=rows[0],rows[1]
            ev["asian_handicap"]={"before":{"line":ah_before[1],"home_odds":ah_before[2],"away_odds":ah_before[3]},
                                 "after":{"line":ah_after[1],"home_odds":ah_after[2],"away_odds":ah_after[3]}}
    ev["h1"]=market=="total" and n[1]-w[1]>=0.24999 and n[2]>w[2]+1e-9
    return ev

def classify_message(text):
    """Return a safe diagnostic reason; never persist the source text."""
    if not text or not text.strip():
        return "empty"
    if " vs " not in text:
        return "other_channel_message"
    if not KICK.search(text):
        return "missing_kickoff"
    rows=odds_rows(text)
    if not any(k=="was" for k,*_ in rows):
        return "missing_was_row"
    if not any(k=="now" for k,*_ in rows):
        return "missing_now_row"
    return "unrecognized_alert_format"


def empty_state():
    return {"last_id":0,"alerts":[],"signals":[],"tickets":[],"diagnostics":[]}

def incorporate(state,events,now,min_lead=10):
    seen={a["event_id"] for a in state["alerts"]}
    matched={s["match_key"] for s in state["signals"]}
    count=0
    for a in sorted(events,key=lambda x:(x["observed_at"],x["message_id"])):
        if a["event_id"] in seen: continue
        seen.add(a["event_id"]); state["alerts"].append(a); count+=1
        if a["h1"] and a["match_key"] not in matched:
            state["signals"].append({"signal_id":a["event_id"],"match_key":a["match_key"],
              "home":a["home"],"away":a["away"],"competition":a["competition"],
              "observed_at":a["observed_at"],"kickoff_utc":a["kickoff_utc"],
              "line":a["total_after"],"under_odds":a["under_after"],"source_url":a["source_url"]})
            matched.add(a["match_key"])
    make_triples(state,now,min_lead)
    return count

def make_triples(state,now,min_lead=10):
    cutoff=now.astimezone(UTC)+timedelta(minutes=min_lead)
    used={sid for t in state["tickets"] for sid in t["signal_ids"]}
    pending=sorted((s for s in state["signals"] if s["signal_id"] not in used and
                    datetime.fromisoformat(s["kickoff_utc"])>cutoff and
                    datetime.fromisoformat(s["observed_at"])<=now.astimezone(UTC)),
                   key=lambda s:(s["observed_at"],s["signal_id"]))
    for i in range(0,len(pending)-2,3):
        group=pending[i:i+3]
        ids=[s["signal_id"] for s in group]
        ticket="T-"+hashlib.sha256("|".join(ids).encode()).hexdigest()[:12]
        state["tickets"].append({"ticket_id":ticket,"created_at":iso(now),
           "signal_ids":ids,"match_keys":[s["match_key"] for s in group],
           "odds":[s["under_odds"] for s in group],"lines":[s["line"] for s in group],
           "theoretical_odds":round(math.prod(s["under_odds"] for s in group),4),
           "notified_at":None})

def asian_under(line,odd,goals):
    q=round(line*4)
    if not math.isclose(line*4,q,abs_tol=1e-7): raise ValueError("Non-Asian line")
    if q%2:
        a=math.floor(line*2)/2
        return (asian_under(a,odd,goals)+asian_under(a+0.5,odd,goals))/2
    return float(odd) if goals<line else 1.0 if goals==line else 0.0

def load_results(path):
    found={}
    if not Path(path).exists(): return found
    with open(path,encoding="utf-8",newline="") as f:
        for row in csv.DictReader(f):
            k=row.get("match_key","").strip()
            if not k or row.get("status","").strip().lower()!="final": continue
            try:
                h,a=int(row["home_goals"]),int(row["away_goals"])
                if min(h,a)<0: continue
            except (ValueError,KeyError): continue
            found[k]={"home_goals":h,"away_goals":a,"source":row.get("source","")}
    return found

def public_data(state,results,now):
    singles=[]
    for s in state["signals"]:
        r=results.get(s["match_key"])
        gross=asian_under(s["line"],s["under_odds"],r["home_goals"]+r["away_goals"]) if r else None
        singles.append({**s,"result":r,"gross_return":gross,
                        "profit":round(gross-1,6) if gross is not None else None})
    lookup={s["signal_id"]:s for s in singles}
    triples=[]
    for t in state["tickets"]:
        legs=[lookup[sid] for sid in t["signal_ids"]]
        complete=all(s["gross_return"] is not None for s in legs)
        gross=math.prod(s["gross_return"] for s in legs) if complete else None
        triples.append({**t,"legs":[{"name":s["home"]+" – "+s["away"],
                  "line":s["line"],"odds":s["under_odds"],"profit":s["profit"]} for s in legs],
                  "gross_return":round(gross,6) if complete else None,
                  "profit":round(gross-1,6) if complete else None})
    def summary(items):
        p=[x["profit"] for x in items if x["profit"] is not None]
        return {"total":len(items),"settled":len(p),"pending":len(items)-len(p),
            "profit_units":round(sum(p),4),
            "roi_pct":round(100*sum(p)/len(p),2) if p else None,
            "green":sum(x>1e-7 for x in p),"red":sum(x< -1e-7 for x in p),
            "push":sum(abs(x)<=1e-7 for x in p)}
    return {"generated_at":iso(now),"alert_count":len(state["alerts"]),
      "singles":summary(singles),"triples":summary(triples),
      "signals":singles,"tickets":triples}

def dump_json(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")

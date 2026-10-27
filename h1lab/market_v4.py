"""Independent, conservative Telegram multi-market shadow parser.

Never produces picks. Parses only explicit rows and verified headings; does not
assume all Telegram visual decoration is present in msg.raw_text.
"""
import json
import re
from datetime import timezone
from pathlib import Path

NUM=r"[+-]?\d+(?:[.,]\d+)?"
PAIR=re.compile(r"(?im)^\s*(Was|Now)\s+("+NUM+r")\s+("+NUM+r")\s+("+NUM+r")(?=\s|[🔴🔵]|$)")
PICK=re.compile(r"(?im)^\s*([1X2])\s+("+NUM+r")\s*(?:→|➡|->)\s*("+NUM+r")")
TOTAL=re.compile(r"(?i)\bTotal\s*:\s*("+NUM+r")\s*([↑↓])\s*("+NUM+r")")
ONE=re.compile(r"(?i)\b1x2\s*\(([1X2])\)\s*:\s*("+NUM+r")\s*[↓↑]\s*("+NUM+r")\s*\(([+-]?\d+(?:[.,]\d+)?)%\)")
HDR_AH=re.compile(r"(?i)\bLine\s+H\s+A\b")
HDR_TOTAL=re.compile(r"(?i)\bLine\s+O\s+U\b")
ODDS_THRESHOLD=1.0

def number(s):
    return float(s.replace(",","."))

def valid_price(x):
    return x is not None and 1 < x < 1000

def rows_between(text,start,end):
    segment=text[start:end]
    rows={}
    for match in PAIR.finditer(segment):
        label=match.group(1).lower()
        if label in rows: return None
        vals=[number(match.group(k)) for k in (2,3,4)]
        if abs(vals[0]*4-round(vals[0]*4))>1e-7 or not all(valid_price(v) for v in vals[1:]):
            return None
        rows[label]=vals
    return rows if "was" in rows and "now" in rows else None

def snapshot(rows,types):
    before,after=rows["was"],rows["now"]
    return {"before":dict(zip(types,before)),"after":dict(zip(types,after)),
            "line_changed":before[0]!=after[0],
            "cross_line_prices_comparable":before[0]==after[0]}

def parse(text,when,message_id,channel_id,legacy_event=None):
    """Return structured observations from a real source text, or None.

    Some markets can be absent; never manufacture prices or results.
    """
    event_id=str(channel_id)+":"+str(message_id)
    ah_headers=list(HDR_AH.finditer(text))
    total_headers=list(HDR_TOTAL.finditer(text))
    header_positions=sorted([(m.start(),"ah",m.end()) for m in ah_headers]+
                            [(m.start(),"total",m.end()) for m in total_headers])
    markets={}
    for i,(start,kind,body_start) in enumerate(header_positions):
        body_end=header_positions[i+1][0] if i+1<len(header_positions) else len(text)
        r=rows_between(text,body_start,body_end)
        if r:
            names=("line","home_price","away_price") if kind=="ah" else ("line","over_price","under_price")
            markets["asian_handicap" if kind=="ah" else "total"]=snapshot(r,names)
    header=TOTAL.search(text)
    if header and "total" not in markets:
        # Only unambiguous single-table Total alerts; never assign the last
        # table of an unknown multi-market notification.
        all_rows=list(PAIR.finditer(text))
        if len(all_rows)==2 and not ah_headers and not total_headers:
            rows=rows_between(text,0,len(text))
            if rows: markets["total"]=snapshot(rows,("line","over_price","under_price"))
    selections={}
    for match in PICK.finditer(text):
        selection=match.group(1).upper()
        if selection in selections:
            selections={};break
        before,after=number(match.group(2)),number(match.group(3))
        if valid_price(before) and valid_price(after):
            selections[selection]={"before":before,"after":after}
    if len(selections)==3: markets["one_x_two"]=selections
    if not markets: return None
    observed=when.astimezone(timezone.utc).isoformat(timespec="seconds")
    return {"schema_version":4,"parser":"telegram_multimarket_shadow",
            "event_id":event_id,"observed_at":observed,
            "trigger_market":"total" if header else "1x2" if ONE.search(text) else "unknown",
            "markets":markets,
            "match_key":legacy_event.get("match_key") if isinstance(legacy_event,dict) else None,
            "kickoff_utc":legacy_event.get("kickoff_utc") if isinstance(legacy_event,dict) else None,
            "source":"telegram_explicit_rows","unverified_fields":["btts","full_market_depth"]}

def store(root,records):
    """Write per-month shadow snapshots by event ID. Never touches H1."""
    months={}
    for item in records:
        if not item:continue
        months.setdefault(item["observed_at"][:7],[]).append(item)
    for month,items in months.items():
        if not re.fullmatch(r"\d{4}-\d{2}",month):continue
        dest=Path(root)/"data"/"lab"/("markets-"+month+".jsonl")
        dest.parent.mkdir(parents=True,exist_ok=True)
        prior={}
        if dest.exists():
            for line in dest.read_text(encoding="utf-8",errors="replace").splitlines():
                try:
                    value=json.loads(line)
                    if isinstance(value,dict) and value.get("event_id"):
                        prior[value["event_id"]]=value
                except ValueError:continue
        for item in items:prior[item["event_id"]]=item
        temp=dest.with_suffix(".tmp")
        temp.write_text("".join(json.dumps(v,ensure_ascii=False,sort_keys=True)+"\n" for v in
                                sorted(prior.values(),key=lambda x:(x["observed_at"],x["event_id"]))),
                        encoding="utf-8")
        temp.replace(dest)

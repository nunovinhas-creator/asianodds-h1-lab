"""Independent, conservative Telegram multi-market shadow parser.

Never produces picks. Parses only explicit rows and verified headings; does not
assume all Telegram visual decoration is present in msg.raw_text.
"""
import json
import functools
import re
import subprocess
from datetime import timezone, datetime
from urllib.parse import urlparse, parse_qs
from pathlib import Path

NUM=r"[+-]?\d+(?:[.,]\d+)?"
PAIR=re.compile(r"(?im)^[ \t]*(Was|Now)[ \t]+("+NUM+r")[ \t]+("+NUM+r")(?:[ \t]*[🔴🔵]\ufe0f?)?[ \t]+("+NUM+r")(?:[ \t]*[🔴🔵]\ufe0f?)?[ \t]*$")
PICK=re.compile(r"(?im)^[ \t]*([1X2])[ \t]+("+NUM+r")[ \t]*(?:→|➡\ufe0f?|->)[ \t]*("+NUM+r")(?:[ \t]*[🔴🔵]\ufe0f?)?[ \t]*$")
TOTAL=re.compile(r"(?i)\bTotal\s*:\s*("+NUM+r")\s*([↑↓])\s*("+NUM+r")")
ONE=re.compile(r"(?i)\b1x2\s*\(([1X2])\)\s*:\s*("+NUM+r")\s*[↓↑]\s*("+NUM+r")\s*\(([+-]?\d+(?:[.,]\d+)?)%\)")
HDR_AH=re.compile(r"(?i)\bLine\s+H\s+A\b")
HDR_TOTAL=re.compile(r"(?i)\bLine\s+O\s+U\b")
WINDOW=re.compile(r"(?i)\blast\s+(\d{1,3})\s+min\b")
KICK=re.compile(r"🕒\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2}:\d{2})\s+UTC",re.I)
MONTHS={m:i+1 for i,m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
URL=re.compile(r"https?://(?:www\.)?asianodds\.com/[^\s)]+",re.I)

@functools.lru_cache(maxsize=1)
def running_parser_commit():
    """Actual checkout HEAD; the Actions event GITHUB_SHA may be stale."""
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"],
                                cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, check=True, timeout=2)
        sha = result.stdout.strip()
        return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


@functools.lru_cache(maxsize=1)
def parser_source_digest():
    """SHA-256 of this parser's own source: identifies the parser *code*.

    parser_commit is the collector checkout HEAD, which changes with every data
    commit; this digest changes only when the parser file changes.
    """
    try:
        import hashlib
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return None


def identity(text,when,legacy_event):
    link=URL.search(text)
    match=parse_qs(urlparse(link.group(0)).query).get("match",[None])[0] if link else None
    ko=None
    m=KICK.search(text)
    if m and m.group(2).title() in MONTHS:
        hour,minute=map(int,m.group(3).split(":"))
        candidates=[]
        for year in (when.year-1,when.year,when.year+1):
            try: candidates.append(datetime(year,MONTHS[m.group(2).title()],int(m.group(1)),hour,minute,tzinfo=timezone.utc))
            except ValueError: pass
        if candidates: ko=min(candidates,key=lambda x:abs((x-when).total_seconds()))
    key=match
    if not key and ko:
        vs=next((line.strip() for line in text.splitlines() if " vs " in line),"")
        vs=re.sub(r"^[^\w]+","",vs)
        teams=vs.split(" vs ",1)
        if len(teams)==2 and all(teams):
            key=ko.strftime("%Y-%m-%d")+"|"+teams[0].casefold()+"|"+teams[1].casefold()
    fallback=legacy_event if isinstance(legacy_event,dict) else {}
    independent_key=key is not None
    independent_kickoff=ko is not None
    return (key or fallback.get("match_key"),
            ko.isoformat(timespec="seconds") if ko else fallback.get("kickoff_utc"),
            {"match_key": "url_match" if match else "telegram_teams_kickoff" if independent_key
             else "legacy_fallback" if fallback.get("match_key") else "missing",
             "kickoff_utc": "telegram_clock" if independent_kickoff else
             "legacy_fallback" if fallback.get("kickoff_utc") else "missing"})


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
    match_key,kickoff_utc,identity_source=identity(text,when,legacy_event)
    trigger=None
    if header:
        trigger={"market":"total","selection":None,"before":number(header.group(1)),
                 "after":number(header.group(3)),"pct":None}
    else:
        h=ONE.search(text)
        if h:
            trigger={"market":"1x2","selection":h.group(1).upper(),
                     "before":number(h.group(2)),"after":number(h.group(3)),
                     "pct":number(h.group(4))}
    window=WINDOW.search(text)
    return {"schema_version":4,"parser":"telegram_multimarket_shadow",
            "event_id":event_id,"observed_at":observed,
            "trigger_market":trigger["market"] if trigger else "unknown",
            "trigger":trigger,"window_minutes":int(window.group(1)) if window else None,
            "markets":markets,
            "match_key":match_key,
            "kickoff_utc":kickoff_utc,
            "identity_source":identity_source,
            "field_source": "telegram_explicit_rows",
            "parser_revision": "v4-provenance-1",
            "parser_commit": running_parser_commit(),
            "parser_source_sha256": parser_source_digest(),
            "source":"telegram_explicit_rows",
            "unverified_fields":["btts","full_market_depth","trigger_pct"]}

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

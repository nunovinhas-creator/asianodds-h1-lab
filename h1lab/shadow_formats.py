"""Shadow-only format inventory. No raw Telegram message content is persisted."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

VERSION=3
PATTERNS=(
 ("total",re.compile(r"(?i)\bTotal\s*:")),
 ("1x2",re.compile(r"(?i)\b1x2\b")),
 ("handicap",re.compile(r"(?i)\b(?:handicap|asian handicap|\bAH\b)")),
 ("btts",re.compile(r"(?i)\b(?:btts|both teams to score)\b")),
)
ROWS=re.compile(r"(?i)^\s*(Was|Now)\s+(.+)$")
NUM=re.compile(r"[+-]?\d+(?:[.,]\d+)?")
def line_class(line):
    """Classify syntax only; never save arbitrary channel text."""
    value=line.strip()
    if not value:
        return None
    if re.search(r"https?://|asianodds\.com", value, re.I):
        return "URL"
    if re.search(r"\bvs\b",value,re.I):
        return "VS"
    if "🏆" in value:
        return "TROPHY"
    if "🕒" in value:
        return "CLOCK"
    row=ROWS.match(value)
    if row:
        count=min(len(NUM.findall(row.group(2))),20)
        return row.group(1).upper()+":"+str(count)
    if re.match(r"^[12Xx]\s+[^\r\n]*[→➡]",value):
        return "ARROW_ROW"
    if re.search(r"\bTotal\s*:",value,re.I):
        arrow="UP" if "↑" in value else "DOWN" if "↓" in value else "OTHER"
        return "HDR_TOTAL_"+arrow
    if re.search(r"\b1x2\b",value,re.I):
        return "HDR_1X2"
    if re.search(r"\b(?:Asian Handicap|Handicap|AH)\b",value,re.I):
        return "HDR_AH"
    if re.search(r"\b(?:BTTS|both teams to score)\b",value,re.I):
        return "HDR_BTTS"
    if "🔴" in value or "🔵" in value:
        return "EMOJI"
    return "OTHER"

def other_signature(line):
    """Closed vocabulary of non-identifying syntactic features."""
    value=line.strip()
    tokens=NUM.findall(value)
    n=len(tokens)
    numbers=[float(token.replace(",",".")) for token in tokens[:6]]
    return {
        "numeric_tokens":min(n,20),
        "numeric_values":numbers,
        "numeric_values_truncated":n>6,
        "has_percentage":bool(re.search(r"\d\s*%",value)),
        "has_arrow":any(ch in value for ch in "↑↓→➡"),
        "has_red": "🔴" in value,
        "has_blue": "🔵" in value,
        "starts_symbol": bool(value) and not (value[0].isalnum() or value[0] in "+-."),
        "has_colon": ":" in value,
        "short_length_bucket": "short" if len(value)<20 else "medium" if len(value)<80 else "long",
    }

def inspect(text,when,message_id,channel_id,legacy_parsed):
    """Persist only a restricted structural signature, never original content."""
    labels=[]
    other_features=[]
    for line in text.splitlines():
        kind=line_class(line)
        if kind:
            labels.append(kind)
            if kind=="OTHER" and len(labels)<=80:
                other_features.append({"line_position":len(labels)-1,**other_signature(line)})
    # Cap shape size without silently discarding that truncation occurred.
    shape_labels=labels[:80]+(["TRUNCATED"] if len(labels)>80 else [])
    found=[key for key,pattern in PATTERNS if pattern.search(text)]
    fingerprint=hashlib.sha256("|".join(shape_labels).encode("utf-8")).hexdigest()[:16]
    family_labels=["HDR_TOTAL" if x in ("HDR_TOTAL_UP","HDR_TOTAL_DOWN","HDR_TOTAL_OTHER") else x for x in shape_labels]
    family_id=hashlib.sha256("|".join(family_labels).encode("utf-8")).hexdigest()[:16]
    return {"schema_version":VERSION,"event_id":str(channel_id)+":"+str(message_id),
        "observed_at":when.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "format_id":fingerprint,"format_family_id":family_id,"markets_mentioned":found,
        "line_classes":shape_labels,"other_features":other_features,"table_shapes":[x.lower() for x in shape_labels if x.startswith(("WAS:","NOW:"))],
        "legacy_parsed":bool(legacy_parsed)}

def store(root,records):
    """Merge by event_id; rewrite bounded current-month inventory, nonfatal to caller."""
    by_month={}
    for item in records:
        month=item["observed_at"][:7]
        if not re.fullmatch(r"\d{4}-\d{2}",month): continue
        by_month.setdefault(month,[]).append(item)
    for month,items in by_month.items():
        path=Path(root)/"data"/"lab"/("formats-"+month+".jsonl")
        path.parent.mkdir(parents=True,exist_ok=True)
        existing={}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row=json.loads(line)
                    if row.get("event_id"): existing[row["event_id"]]=row
                except (ValueError,TypeError,AttributeError): continue
        for item in items: existing[item["event_id"]]=item
        ordered=sorted(existing.values(),key=lambda x:(x["observed_at"],x["event_id"]))
        temp=path.with_suffix(".tmp")
        temp.write_text("".join(json.dumps(v,sort_keys=True)+"\n" for v in ordered),encoding="utf-8")
        temp.replace(path)

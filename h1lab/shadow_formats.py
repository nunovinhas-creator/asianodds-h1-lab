"""Shadow-only format inventory. No raw Telegram message content is persisted."""
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

VERSION=1
PATTERNS=(
 ("total",re.compile(r"(?i)\bTotal\s*:")),
 ("1x2",re.compile(r"(?i)\b1x2\b")),
 ("handicap",re.compile(r"(?i)\b(?:handicap|asian handicap|\bAH\b)")),
 ("btts",re.compile(r"(?i)\b(?:btts|both teams to score)\b")),
)
ROWS=re.compile(r"(?i)^\s*(Was|Now)\s+(.+)$")
NUM=re.compile(r"[+-]?\d+(?:[.,]\d+)?")
def inspect(text,when,message_id,channel_id,legacy_parsed):
    """Fingerprint structure only. Never persist source text, teams or links."""
    labels=[]
    for line in text.splitlines():
        m=ROWS.match(line)
        if m:
            count=len(NUM.findall(m.group(2)))
            labels.append(m.group(1).lower()+":"+str(min(count,20)))
    found=[key for key,pattern in PATTERNS if pattern.search(text)]
    shape="|".join(sorted(found))+"#"+",".join(labels[:20])
    fingerprint=hashlib.sha256(shape.encode("utf-8")).hexdigest()[:16]
    return {"schema_version":VERSION,"event_id":str(channel_id)+":"+str(message_id),
        "observed_at":when.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "format_id":fingerprint,"markets_mentioned":found,"table_shapes":labels[:20],
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

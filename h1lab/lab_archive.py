"""V6.2 P2#14 — lossless monthly LAB journals, size bounds and seal verification.

Append-only journals retain their existing bytes and row SHA links. If a month
reaches 20,000,000 bytes, subsequent rows go into numbered parts for the SAME
UTC month. Latest-view projections are mutable and are repartitioned separately.
This module never modifies H1, Telegram, FT ledgers, frozen observations or hashes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 20_000_000
VERSION = 1
INDEX = "data/lab/v6-archive-index.json"
PUBLIC = "docs/lab/v6-archive-health.json"
APPEND_ONLY = (
    "v4-revisions", "v6-forecasts", "v6-ft-events",
    "v6-memory-observations", "v6-memory-patterns", "v6-memory-hypotheses",
    "v6-memory-evidence", "v6-memory-decisions", "discovery-events",
    "v6-weekly-snapshots",
)
LATEST_VIEWS = ("markets", "formats")
MONTHLY = APPEND_ONLY + LATEST_VIEWS


def _month(month):
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Invalid archive month: " + repr(month))
    datetime.strptime(month, "%Y-%m")
    return month


def monthly_paths(root, prefix):
    """Chronological base file followed by sequential parts; gaps fail closed."""
    if prefix not in MONTHLY:
        raise ValueError("Unknown archive stream " + prefix)
    base = Path(root) / "data/lab"
    match = re.compile(r"^" + re.escape(prefix) +
                       r"-(\d{4}-\d{2})(?:-part(\d{4}))?\.jsonl$")
    found = []
    for path in base.glob(prefix + "-*.jsonl"):
        m = match.fullmatch(path.name)
        if not m:
            raise ValueError("Unknown monthly archive filename " + path.name)
        month = _month(m[1])
        part = int(m[2]) if m[2] is not None else 0
        if m[2] is not None and part < 1:
            raise ValueError("Invalid archive part number")
        found.append((month, part, path))
    found.sort(key=lambda row: (row[0], row[1]))
    groups = {}
    for month, part, path in found:
        groups.setdefault(month, []).append(part)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("LAB_FILE_OVER_20_MB: " + str(path))
    for month, parts in groups.items():
        if parts != list(range(len(parts))):
            raise ValueError("Missing/duplicated monthly archive part: " + prefix + "-" + month)
    return [path for _, _, path in found]


def _serialize_row(row):
    if isinstance(row, bytes):
        data = row
    elif isinstance(row, str):
        data = row.encode("utf-8")
    else:
        raise TypeError("Append requires pre-serialized JSON text")
    if not data.endswith(b"\n") or data.count(b"\n") != 1 or len(data) > MAX_BYTES:
        raise ValueError("Invalid or oversized individual JSONL record")
    if not isinstance(json.loads(data), dict):
        raise ValueError("JSONL rows must be objects")
    return data


def append_monthly(root, prefix, month, rows):
    """Bounded append without rewriting existing JSONL or changing any row hash."""
    if prefix not in APPEND_ONLY:
        raise ValueError("Cannot append as a journal to a mutable projection")
    month = _month(month)
    data = [_serialize_row(row) for row in rows]
    if not data:
        return []
    root = Path(root)
    directory = root / "data/lab"
    directory.mkdir(parents=True, exist_ok=True)
    paths = monthly_paths(root, prefix)
    if any(p.name[len(prefix)+1:len(prefix)+8] > month for p in paths):
        raise ValueError("Cannot append earlier than a later monthly journal")
    current = [p for p in paths if p.name[len(prefix)+1:len(prefix)+8] == month]
    part = len(current) - 1
    active = current[-1] if current else directory / (prefix + "-" + month + ".jsonl")
    size = active.stat().st_size if active.exists() else 0
    result = []
    for item in data:
        if size + len(item) > MAX_BYTES:
            part += 1
            if part > 9999:
                raise ValueError("Too many monthly archive parts")
            active = directory / (prefix + "-" + month + "-part%04d.jsonl" % part)
            if active.exists():
                raise ValueError("Unexpected archive part collision")
            size = 0
        # Never put a valid JSON line after a truncated/incomplete row.
        if active.exists() and size:
            with active.open("rb") as handle:
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    raise ValueError("Truncated JSONL archive tail")
        with active.open("ab") as handle:
            handle.write(item)
        size += len(item)
        result.append(active)
    monthly_paths(root, prefix)
    return result


def write_monthly_view(root, prefix, month, lines):
    """Atomically replace mutable latest-view partitions, never SHA journals."""
    if prefix not in LATEST_VIEWS:
        raise ValueError("Only the mutable views can be repartitioned")
    month = _month(month)
    root = Path(root)
    directory = root / "data/lab"
    directory.mkdir(parents=True, exist_ok=True)
    chunks = [[]]
    length = 0
    for row in lines:
        raw = _serialize_row(row)
        if length + len(raw) > MAX_BYTES:
            chunks.append([])
            length = 0
        chunks[-1].append(raw)
        length += len(raw)
    old = [p for p in monthly_paths(root, prefix)
           if p.name[len(prefix)+1:len(prefix)+8] == month]
    names = [directory / (prefix + "-" + month + (
        "" if i == 0 else "-part%04d" % i) + ".jsonl")
        for i in range(len(chunks))]
    # Write every new partition to a temporary path first; malformed row
    # errors never replace the original view. The Git commit is the atomic
    # publication boundary, not individual filesystem renames.
    temp = []
    try:
        for path, chunk in zip(names, chunks):
            tmp = path.with_name(path.name + ".archive-tmp")
            tmp.write_bytes(b"".join(chunk))
            temp.append((tmp, path))
        for tmp, path in temp:
            tmp.replace(path)
        for path in old:
            if path not in names:
                path.unlink()
    finally:
        for tmp, _ in temp:
            if tmp.exists():
                tmp.unlink()
    monthly_paths(root, prefix)
    return names


def _file_entry(path, root):
    content = path.read_bytes()
    if len(content) > MAX_BYTES:
        raise ValueError("LAB_FILE_OVER_20_MB: " + str(path))
    if not content.endswith(b"\n"):
        raise ValueError("Incomplete archived JSONL " + str(path))
    lines = content.splitlines()
    if not lines:
        raise ValueError("Empty closed archive " + str(path))
    for line in lines:
        if not isinstance(json.loads(line), dict):
            raise ValueError("Corrupt archived JSONL object")
    return {"path": path.relative_to(root).as_posix(), "bytes": len(content),
            "rows": len(lines), "sha256_bytes": hashlib.sha256(content).hexdigest()}


def _replay(root):
    """Cross-file SHA chains and V4/FT history are checked independently."""
    from .v4_revisions import read_events as v4_revisions
    from .v6_ft_events import read_events as ft_events
    from .v6_shadow import read_journal as forecasts
    from .v6_science_memory import KINDS, read_stream
    from scripts.lab_v6_weekly_monitor import read_snapshots
    return {"v4_revisions": len(v4_revisions(root)),
            "v6_forecasts": len(forecasts(root)),
            "v6_ft_events": len(ft_events(root)),
            "v6_memories": {kind: len(read_stream(root, kind)) for kind in KINDS},
            "weekly_snapshots": len(read_snapshots(root))}


def build(root, now, *, verify_only=False):
    root = Path(root)
    if now.tzinfo is None:
        raise ValueError("Archive timestamp must be timezone aware")
    month = now.astimezone(timezone.utc).strftime("%Y-%m")
    lab = root / "data/lab"
    old_path = root / INDEX
    old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.is_file() else None
    if old and old.get("schema_version") != VERSION:
        raise ValueError("Archive index version changed")
    # Every LAB file, including mutable state, is checked. The mutable views
    # are NOT sealed, because Telegram can later reveal historical edits.
    all_files = sorted(x for x in lab.rglob("*") if x.is_file() and x != old_path and
                       not x.name.endswith((".tmp", ".archive-tmp")))
    for path in all_files:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("LAB_FILE_OVER_20_MB: " + str(path))
    files = []
    closed = []
    for prefix in MONTHLY:
        paths = monthly_paths(root, prefix)
        for path in paths:
            name_month = path.name[len(prefix)+1:len(prefix)+8]
            files.append(path)
            if prefix in APPEND_ONLY and name_month < month:
                closed.append(_file_entry(path, root))
    closed.sort(key=lambda x: x["path"])
    known = {x["path"]: x for x in (old or {}).get("sealed", [])}
    new = {x["path"]: x for x in closed}
    for path, previous in known.items():
        if new.get(path) != previous:
            raise ValueError("SEALED_MONTH_MUTATED_OR_MISSING: " + path)
    # All closed pieces must have been indexed before accepting verify-only.
    index = {"schema_version": VERSION, "status": "V6_LAB_MONTHLY_ARCHIVE_SEALED",
             "max_file_bytes": MAX_BYTES, "sealed": closed}
    replay = _replay(root)
    report = {
        "schema_version": VERSION, "status": "V6_LAB_ARCHIVE_INTEGRITY_SHADOW",
        "scientific_state": "INCONCLUSIVO",
        "max_file_bytes": MAX_BYTES,
        "lab_files_checked": len(all_files),
        "largest_file_bytes": max((x.stat().st_size for x in all_files), default=0),
        "monthly_parts": len(files),
        "sealed_parts": len(closed),
        "replay": replay,
        "sealed_index_digest": hashlib.sha256(json.dumps(
            index, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "limitations": ["Current-month journals remain append-only, not sealed until month end.",
                        "Market and format files are mutable latest-view projections.",
                        "FT ledger and cached states remain mutable; full SHA history is in separate journals.",
                        "Integrity/size checks do not establish market coverage, model validity, edge or ROI."]}
    out = root / PUBLIC
    if verify_only:
        if not old or old != index:
            raise ValueError("Archive index is out of sync or missing")
        if not out.is_file() or json.loads(out.read_text(encoding="utf-8")) != report:
            raise ValueError("Archive health report replay mismatch")
        return report
    old_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_index = json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if not old_path.is_file() or old_path.read_text(encoding="utf-8") != rendered_index:
        old_path.write_text(rendered_index, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if not out.is_file() or out.read_text(encoding="utf-8") != rendered:
        out.write_text(rendered, encoding="utf-8")
    return report

"""Materialize incremental V5 discovery history and prospective FT without API calls.

Invoked AFTER pattern research and pattern watch in the existing LAB FT workflow.
H1, Telegram, schedule, odds and existing result ledgers are READ ONLY.
"""
from __future__ import annotations
from h1lab.lab_archive import monthly_paths, append_monthly

import argparse
import copy
import json
from pathlib import Path

from h1lab.discovery_timeline import build
from h1lab.discovery_public_pages import paginate, PAGE_LIMIT
from h1lab import lab_discovery_dual_state as dual_state
from h1lab import lab_discovery_store as segmented_store

ROOT = Path(__file__).resolve().parents[1]
STATE = Path("data/lab/discovery-state.json")
PUBLIC = Path("docs/lab/discoveries.json")
MAX_PUBLIC_BYTES = 1_400_000
MAX_STATE_BYTES = 2_000_000


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def serialize(value, limit, path):
    content = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(content.encode("utf-8")) > limit:
        raise ValueError("discovery data exceeded limit: " + str(path))
    return content


def bounded_public(value, limit=MAX_PUBLIC_BYTES):
    """Bound only the web cache; preserve every pattern/latest and durable history."""
    result = copy.deepcopy(value)
    omitted = 0
    while True:
        if omitted:
            result['limitations'] = [line for line in value.get('limitations', [])
                                    if not line.startswith('Últimos 24 pontos')]
            result['limitations'].append(
                'Cache pública reduzida pelo limite de bytes; pontos antigos preservados no estado e arquivos Git.')
            result['public_cache'] = {
                'older_points_omitted': omitted,
                'history_preserved_in': 'data/lab/discovery-state.json and discovery-events monthly archives',
            }
        try:
            serialize(result, limit, PUBLIC)
            return result
        except ValueError:
            # Drop the oldest cached point of each series, retaining at least
            # its newest point. Never remove patterns, latest evidence or FT.
            removable = [row for row in result['patterns'].values()
                         if len(row.get('points', [])) > 1]
            if not removable:
                raise
            for row in removable:
                row['points'] = row['points'][1:]
                omitted += 1


def put(path, value, limit):
    content = serialize(value, limit, path)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--state-backend", choices=("legacy", "dual", "segmented"), default="legacy",
                        help="Dual requires preexisting verified segment store; no auto-bootstrap")
    args = parser.parse_args(argv)
    root = args.root
    report = read(root / "docs/lab/pattern-research.json")
    first = read(root / "data/lab/pattern-watch-first-seen.json", {"entries": []})
    ledger = read(root / "data/lab/ft-ledger.json", {"matches": {}})
    if not isinstance(report, dict) or not isinstance(first, dict) or not isinstance(ledger, dict):
        raise ValueError("missing or malformed discovery inputs")
    # Existing production and historical replay use legacy by default.
    # Dual is an explicit, unconfigured CLI mode for isolated validation.
    prior = (read(root / STATE) if args.state_backend == "legacy" else
             dual_state.load(root, format=args.state_backend))
    expected_generation = (dual_state.current_generation(root)
                           if args.state_backend != "legacy" else None)
    state, full_public, events = build(report, first, ledger, prior)
    # All public pattern points are preserved in immutable content-addressed
    # pages. Only the small manifest remains in discoveries.json.
    public, pages = paginate(full_public, root_limit=MAX_PUBLIC_BYTES)
    # Preflight the complete root/page set before ANY journal/state writes.
    if args.state_backend == "segmented":
        if len(segmented_store.encode(state)) > segmented_store.STATE_LIMIT:
            raise ValueError("Segmented discovery safety limit reached")
    else:
        serialize(state, MAX_STATE_BYTES, STATE)
    serialize(public, MAX_PUBLIC_BYTES, PUBLIC)
    if args.state_backend != "legacy":
        # Preflight shard/member constraints BEFORE touching event journals.
        segmented_store.partition(state)

    # Archive immutable data FIRST; abort on any conflicting event ID. JSONL
    # is partitioned by UTC month. No event is dropped when the frontend cache rolls.
    by_month = {}
    for e in events:
        month = e["at_utc"][:7]
        if len(month) != 7 or month[4] != "-":
            raise ValueError("invalid event month")
        by_month.setdefault(month, []).append(e)
    for month, additions in by_month.items():
        known = {}
        for part in monthly_paths(root, "discovery-events"):
            if part.name[len("discovery-events")+1:len("discovery-events")+8] != month:
                continue
            for line in part.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row["event_id"] in known and known[row["event_id"]] != row:
                    raise ValueError("history duplicate with different content")
                known[row["event_id"]] = row
        fresh = []
        for item in additions:
            if item["event_id"] in known:
                if item != known[item["event_id"]]:
                    raise ValueError("immutable event changed")
            else:
                fresh.append(item)
                known[item["event_id"]] = item
        if fresh:
            append_monthly(root, "discovery-events", month, [
                json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
                for item in fresh])

    # Write all immutable pages before publishing their manifest. The FT
    # publication guard additionally seals all reachable page bytes in Git.
    for relative, raw in sorted(pages.items()):
        put(root / "docs/lab" / relative, json.loads(raw), PAGE_LIMIT)
    if args.state_backend == "dual":
        result = dual_state.write_dual(root, state, expected_generation=expected_generation)
        a = result["changed"]
    elif args.state_backend == "segmented":
        result = dual_state.write_segmented(root, state, expected_generation=expected_generation)
        a = result["changed"]
    else:
        a = put(root / STATE, state, MAX_STATE_BYTES)
    b = put(root / PUBLIC, public, MAX_PUBLIC_BYTES)
    print("MASTER_BRAIN_DISCOVERY", "baseline", prior is None,
          "events_new", len(events), "published_patterns", len(state["patterns"]),
          "prospective_ft", len(state["prospective_settled"]),
          "state_changed", a, "public_changed", b, "public_pages", len(pages),
          "state_backend", args.state_backend)
    return public


if __name__ == "__main__":
    main()

"""Immutable, content-addressed pages for MASTER BRAIN public discovery patterns.

The root discoveries.json retains all non-pattern fields. Pages preserve complete
per-pattern evidence; no point is discarded to satisfy the public root limit.
The existing durable discovery-state and monthly event archives are untouched.
"""
import copy
import hashlib
import json
import re

PAGE_LIMIT = 256_000
ROOT_LIMIT = 1_400_000
PAGE_DIRECTORY = "discovery-pages"


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def paginate(public, *, page_limit=PAGE_LIMIT, root_limit=ROOT_LIMIT):
    if not isinstance(public, dict) or not isinstance(public.get("patterns"), dict):
        raise ValueError("Invalid discovery publication")
    original = public["patterns"]
    root = copy.deepcopy({k: v for k, v in public.items() if k != "patterns"})
    root["patterns"] = {}
    root["pattern_count"] = len(original)
    root["pattern_pages"] = []
    root["public_cache"] = {
        "layout": "CONTENT_ADDRESSED_PATTERN_PAGES_V1",
        "history_preserved_in": "data/lab/discovery-state.json and discovery-events monthly archives",
        "points_omitted": 0,
    }
    pages = {}

    def flush(batch):
        if not batch:
            return
        raw = encode({"patterns": batch})
        if len(raw) > page_limit:
            raise ValueError("Oversized discovery page")
        digest = hashlib.sha256(raw).hexdigest()
        relative = PAGE_DIRECTORY + "/" + digest + ".json"
        if relative in pages and pages[relative] != raw:
            raise ValueError("Conflicting content-addressed page")
        pages[relative] = raw
        root["pattern_pages"].append({
            "path": relative, "sha256": digest,
            "bytes": len(raw), "patterns": len(batch)
        })

    batch = {}
    for key in sorted(original):
        if not isinstance(key, str) or not isinstance(original[key], dict):
            raise ValueError("Invalid discovery pattern identity")
        row = {key: original[key]}
        if len(encode({"patterns": row})) > page_limit:
            raise ValueError("Single discovery pattern exceeds page limit")
        candidate = dict(batch)
        candidate[key] = original[key]
        if batch and len(encode({"patterns": candidate})) > page_limit:
            flush(batch)
            batch = {}
        batch[key] = original[key]
    flush(batch)
    if len(encode(root)) > root_limit:
        raise ValueError("Discovery root metadata exceeds public limit")
    verify(root, pages, page_limit=page_limit, root_limit=root_limit)
    return root, pages


def verify(root, pages, *, page_limit=PAGE_LIMIT, root_limit=ROOT_LIMIT):
    if (not isinstance(root, dict) or not isinstance(root.get("patterns"), dict)
            or root["patterns"] or not isinstance(root.get("pattern_pages"), list)
            or type(root.get("pattern_count")) is not int or root["pattern_count"] < 0
            or len(encode(root)) > root_limit):
        raise ValueError("Invalid discovery pagination root")
    if not isinstance(pages, dict):
        raise ValueError("Invalid discovery pages")
    keys = set()
    seen_paths = set()
    total = 0
    for meta in root["pattern_pages"]:
        if not isinstance(meta, dict) or set(meta) != {"path", "sha256", "bytes", "patterns"}:
            raise ValueError("Invalid discovery page descriptor")
        path = meta["path"]
        digest = meta["sha256"]
        if (not isinstance(path, str) or not isinstance(digest, str)
                or not re.fullmatch(PAGE_DIRECTORY + r"/[a-f0-9]{64}\.json", path)
                or path != PAGE_DIRECTORY + "/" + digest + ".json"
                or path in seen_paths):
            raise ValueError("Unsafe or duplicate discovery page")
        seen_paths.add(path)
        raw = pages.get(path)
        if (not isinstance(raw, bytes) or type(meta["bytes"]) is not int
                or len(raw) != meta["bytes"] or len(raw) > page_limit
                or hashlib.sha256(raw).hexdigest() != digest):
            raise ValueError("Missing or corrupted discovery page")
        try:
            obj = json.loads(raw, object_pairs_hook=_distinct_pairs,
                             parse_constant=_reject_constant)
        except (UnicodeError, ValueError, TypeError) as exc:
            raise ValueError("Invalid discovery page JSON") from exc
        if (not isinstance(obj, dict) or set(obj) != {"patterns"}
                or not isinstance(obj["patterns"], dict)
                or type(meta["patterns"]) is not int
                or len(obj["patterns"]) != meta["patterns"] or meta["patterns"] <= 0):
            raise ValueError("Invalid discovery page patterns")
        for key, value in obj["patterns"].items():
            if key in keys or not isinstance(value, dict):
                raise ValueError("Duplicate or malformed public pattern")
            keys.add(key)
        total += len(obj["patterns"])
    if total != root["pattern_count"] or seen_paths != set(pages):
        raise ValueError("Incomplete or orphaned discovery page set")
    return total


def _distinct_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON value: " + value)

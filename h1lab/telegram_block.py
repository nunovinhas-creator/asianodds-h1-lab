"""Shared Telegram delivery block (HTTP 429 retry_after / 401 / 403).

One small JSON file shared by *every* notifier that sends through ``bot.send_message``,
so a flood-wait or an authentication rejection seen by one notifier stops the others
too (a block stored inside one notifier's own ledger would not). The file never
contains tokens or chat ids. It is local to the checkout unless a workflow commits it
(the current workflows do not - see PR notes).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "data" / "telegram-delivery-block.json"
SCHEMA_VERSION = 1


def _utc(value):
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


class BlockStore:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("TG_DELIVERY_BLOCK_FILE") or DEFAULT_PATH)

    def read(self):
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (data.get("schema_version") != SCHEMA_VERSION or _utc(data.get("until")) is None
                    or not isinstance(data.get("http_status"), int)):
                raise ValueError("shape")
        except (ValueError, TypeError, AttributeError, OSError):
            # Fail closed and loud: nothing is sent while the block record is unreadable.
            raise ValueError("invalid Telegram delivery block file; nothing sent")
        return data

    def active(self, moment, ignore_auth=None):
        """The active block, or None. TG_IGNORE_AUTH_BLOCK=1 lifts ONLY a 401/403 block (credentials
        were fixed); a flood-wait (429) is never lifted early."""
        data = self.read()
        if data is None or moment >= _utc(data["until"]):
            return None
        if ignore_auth is None:
            ignore_auth = os.environ.get("TG_IGNORE_AUTH_BLOCK") == "1"
        if ignore_auth and data["http_status"] in (401, 403):
            return None
        return data

    def record(self, until, http_status, moment, diagnosis):
        """Extend, never shorten, an active block."""
        current = self.read()
        if current is not None and _utc(current["until"]) > until:
            return current
        data = {"schema_version": SCHEMA_VERSION, "until": until.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "http_status": http_status,
                "set_at": moment.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "diagnosis": diagnosis}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True)
        os.replace(tmp, self.path)
        return data

    def clear(self):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

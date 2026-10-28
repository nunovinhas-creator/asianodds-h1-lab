"""Read-only Monte-Carlos -> BSD event-ID resolver for LAB-only FT reconciliation.

Monte-Carlos stores *BSD event IDs* in predictions.db and settles directly by
/api/v2/events/{id}/. AsianOdds' match_key values do NOT identify BSD events.

We build an exact ordered home/away + UTC kickoff crosswalk to obtain a *candidate*
BSD ID from the public Monte-Carlos archive. The score must then be fetched
fresh from BSD and validated against the original LAB fixture. Nothing from
the Monte-Carlos database is taken as a final score on its own.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .bsd import ROOT, BSDProviderError, matches_identity, request_json, regulation_result
from .results import norm_team
from .lab_reviewed_bsd_ids import reviewed_bsd_fixture

SOURCE_URL = "https://raw.githubusercontent.com/nunovinhas-creator/Monte-Carlos/main/predictions.db"
MAX_ARCHIVE_BYTES = 4000000
MAX_REDIRECTS = 5
MAX_EVENT_REQUESTS = 18
BACKOFF = (2, 4, 8)
FINAL_ALIASES = {"finished", "ft", "ended", "completed", "complete", "closed", "full-time", "fulltime"}
NOT_PLAYED = {"cancelled", "canceled", "postponed", "abandoned", "suspended", "awarded", "walkover"}


def fetch_archive(url=SOURCE_URL):
    """Download only this owner's public SQLite archive; size capped."""
    if url != SOURCE_URL:
        raise ValueError("Unexpected archive URL")
    req = Request(url, headers={"Accept":"application/octet-stream",
                               "User-Agent":"AsianOdds-LAB-FT-Audit/1.0"})
    try:
        with urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                raise OSError("Archive unavailable")
            raw = resp.read(MAX_ARCHIVE_BYTES + 1)
    except (HTTPError, URLError, OSError, TimeoutError):
        raise OSError("Monte-Carlos archive unavailable") from None
    if len(raw) > MAX_ARCHIVE_BYTES or not raw.startswith(b"SQLite format 3\x00"):
        raise ValueError("Invalid or oversized public database")
    return raw


def exact_catalog(raw):
    """Only valid numeric IDs from an SQLite file opened strictly read-only."""
    if not isinstance(raw, bytes) or len(raw) > MAX_ARCHIVE_BYTES or not raw.startswith(b"SQLite format 3\x00"):
        raise ValueError("Not a valid bounded SQLite payload")
    filename = None
    try:
        with tempfile.NamedTemporaryFile(prefix="lab-monte-bsd-", suffix=".db", delete=False) as f:
            filename = f.name
            f.write(raw)
        # No extensions, no attached databases, no writes. Limit resource usage.
        conn = sqlite3.connect("file:" + filename + "?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            cols = {x[1] for x in conn.execute("PRAGMA table_info(predictions)")}
            required = {"match_id", "home_team", "away_team", "timestamp"}
            if not required <= cols:
                raise ValueError("Missing Monte-Carlos fixture columns")
            result = {}
            for ident, home, away, ts in conn.execute(
                "SELECT match_id,home_team,away_team,timestamp FROM predictions LIMIT 75000"
            ):
                if not isinstance(ident, str) or not re.fullmatch(r"[0-9]{1,14}", ident):
                    continue
                num = int(ident)
                if num <= 0 or not isinstance(home, str) or not isinstance(away, str):
                    continue
                if isinstance(ts, bool) or not isinstance(ts, (int, float)):
                    continue
                try:
                    kickoff = datetime.fromtimestamp(ts, timezone.utc)
                except (ValueError, OverflowError, OSError):
                    continue
                if not (2020 <= kickoff.year <= 2035):
                    continue
                key = (norm_team(home), norm_team(away), kickoff.date().isoformat())
                result.setdefault(key, []).append((num, kickoff))
            return result
        finally:
            conn.close()
    except (sqlite3.DatabaseError, sqlite3.Error) as e:
        raise ValueError("Monte-Carlos database read failed") from None
    finally:
        if filename and os.path.isfile(filename):
            os.unlink(filename)


def _status(data):
    """Monte-Carlos status extraction; do not accept nonregulation ET."""
    for field in ("status", "state", "match_status", "event_status", "time_status"):
        value = data.get(field)
        if isinstance(value, dict):
            for sub in ("type", "code", "name", "short_name", "description"):
                if value.get(sub) is not None:
                    return str(value[sub]).strip().lower()
        elif value is not None:
            return str(value).strip().lower()
    return ""


def _redirect(data):
    value = data.get("replaced_by")
    if isinstance(value, dict):
        value = value.get("id") or value.get("match_id") or value.get("event_id")
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,14}", value) and int(value) > 0:
        return int(value)
    return None


def _unpack(data):
    """Monte-Carlos supports {data:{...}} and {result:{...}} envelopes."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("data"), dict):
        data = data["data"]
    if "status" not in data and isinstance(data.get("result"), dict):
        data = data["result"]
    return data


def _goals(data):
    """Prefer BSD documented regulation home_score/away_score.

    Monte-Carlos extracts nested scores too; only explicitly named FT blocks
    are allowed here. Generic 'score' may contain 120-minute cup results.
    """
    pairs = [("home_score","away_score"), ("home_goals","away_goals"),
             ("ft_home","ft_away")]
    for a,b in pairs:
        h,w = data.get(a),data.get(b)
        if h is not None and w is not None:
            if any(type(x) is bool or not re.fullmatch(r"[0-9]{1,2}",str(x)) for x in (h,w)):
                return None
            return int(h),int(w)
    for field in ("ft_score","full_time_score","scores"):
        part=data.get(field)
        if not isinstance(part,dict):
            continue
        if field=="scores":
            part = part.get("fulltime") or part.get("full_time") or part.get("regulation")
            if not isinstance(part,dict):
                continue
        for a,b in (("home","away"),("home_score","away_score"),
                    ("full_time_home","full_time_away")):
            h,w=part.get(a),part.get(b)
            if h is not None and w is not None:
                if any(type(x) is bool or not re.fullmatch(r"[0-9]{1,2}",str(x)) for x in (h,w)):
                    return None
                return int(h),int(w)
    return None


def validated_result(signal, event):
    """BSD score remains a strict 90-minute score (never an extra-time total)."""
    if not isinstance(event, dict) or not matches_identity(signal,event):
        return None, "monte_bsd_identity_mismatch"
    status = _status(event)
    if status in NOT_PLAYED:
        return None, "monte_bsd_void"
    if status not in FINAL_ALIASES:
        return None, "monte_bsd_not_regulation_final"
    if any(event.get(x) is True for x in ("postponed","cancelled","abandoned")):
        return None, "monte_bsd_not_played"
    score = _goals(event)
    if score is None or type(event.get("id")) is not int or event["id"] <= 0:
        return None, "monte_bsd_invalid_regulation_score"
    normalized = dict(event)
    normalized.update({"status":"finished","home_score":score[0],
                       "away_score":score[1]})
    result, reason = regulation_result(signal,normalized)
    return result, "verified_bsd_ft_from_monte_id" if result else reason


class MonteBSDCrosswalk:
    def __init__(self, *, token, downloader=fetch_archive, fetch=request_json,
                 sleep=time.sleep, max_event_requests=12):
        if not isinstance(max_event_requests,int) or not 0 <= max_event_requests <= MAX_EVENT_REQUESTS:
            raise ValueError("Monte-Carlos BSD request budget exceeded")
        self.token=(token or "").strip()
        self.downloader=downloader
        self.fetch=fetch
        self.sleep=sleep
        self.max_event_requests=max_event_requests
        self.events_requested=0
        self.index=None
        self.archive_hash=None
        self.load_reason="not_loaded"
        self.reasons=Counter()
        self.matched_keys=set()
        self.rate_limited=False

    def _load(self):
        if self.index is not None:
            return
        self.index={}
        if not self.token:
            self.load_reason="bsd_not_configured"
            return
        try:
            raw=self.downloader()
            self.index=exact_catalog(raw)
            self.archive_hash=hashlib.sha256(raw).hexdigest()[:16]
            self.load_reason="read_only_loaded"
        except (OSError,ValueError,sqlite3.DatabaseError):
            self.load_reason="archive_unavailable"

    def _event(self, event_id):
        if not isinstance(event_id,int) or event_id<1:
            return None,"monte_invalid_event_id"
        if self.rate_limited:
            return None,"monte_bsd_rate_limited_run"
        if self.events_requested>=self.max_event_requests:
            return None,"monte_bsd_budget_deferred"
        for delay in (0,)+BACKOFF:
            if delay:
                self.sleep(delay)
            if self.events_requested>=self.max_event_requests:
                return None,"monte_bsd_budget_deferred"
            self.events_requested+=1
            try:
                data = self.fetch(ROOT+str(event_id)+"/",self.token)
                return _unpack(data),"monte_bsd_event_fetched"
            except BSDProviderError as exc:
                if "429" in str(exc):
                    if delay == BACKOFF[-1]:
                        self.rate_limited=True
                        return None,"monte_bsd_rate_limited"
                    continue
                return None,"monte_bsd_provider_unavailable"
        return None,"monte_bsd_provider_unavailable"

    def lookup(self, signal):
        if not self.token:
            return None,"bsd_not_configured"
        reviewed=reviewed_bsd_fixture(signal)
        using_reviewed=reviewed is not None
        if using_reviewed:
            event_id, home, away = reviewed
            # The approved BSD names belong ONLY to the original match_key
            # and original kickoff; they are never general aliases.
            checking_signal={**signal,"home":home,"away":away}
            self.matched_keys.add(signal["match_key"])
        else:
            self._load()
            if self.load_reason!="read_only_loaded":
                return None,"monte_"+self.load_reason
            try:
                kickoff=datetime.fromisoformat(signal["kickoff_utc"].replace("Z","+00:00"))
                if kickoff.tzinfo is None:
                    return None,"monte_invalid_kickoff"
                kickoff=kickoff.astimezone(timezone.utc)
            except (ValueError,TypeError,KeyError):
                return None,"monte_invalid_kickoff"
            key=(norm_team(signal.get("home")),norm_team(signal.get("away")),kickoff.date().isoformat())
            candidates={eid for eid,dt in self.index.get(key,[])
                        if abs((dt-kickoff).total_seconds()) <= 90*60}
            if not candidates:
                self.reasons["no_exact_archive_match"]+=1
                return None,"monte_no_exact_archive_match"
            if len(candidates)!=1:
                self.reasons["ambiguous_archive_match"]+=1
                return None,"monte_ambiguous_archive_match"
            self.matched_keys.add(signal["match_key"])
            event_id=candidates.pop()
            checking_signal=signal
        visited=set()
        for _ in range(MAX_REDIRECTS):
            if event_id in visited:
                return None,"monte_replaced_by_cycle"
            visited.add(event_id)
            data,reason=self._event(event_id)
            if data is None:
                return None,reason
            if type(data.get("id")) is not int or data["id"]!=event_id:
                return None,"monte_bsd_detail_id_mismatch"
            next_id=_redirect(data)
            if next_id and next_id!=event_id:
                event_id=next_id
                continue
            result,reason=validated_result(checking_signal,data)
            if result and using_reviewed:
                reason="verified_bsd_ft_from_reviewed_id"
            self.reasons[reason]+=1
            return result,reason
        return None,"monte_replaced_by_limit"

    def summary(self):
        return {"archive_status":self.load_reason,
                "archive_sha256_prefix":self.archive_hash,
                "catalog_matchday_groups":len(self.index or {}),
                "exact_event_id_candidates":len(self.matched_keys),
                "bsd_direct_event_requests":self.events_requested,
                "verified_in_run":(self.reasons["verified_bsd_ft_from_monte_id"]+
                                   self.reasons["verified_bsd_ft_from_reviewed_id"]),
                "reviewed_bsd_ids_verified":self.reasons["verified_bsd_ft_from_reviewed_id"],
                "rate_limited":self.rate_limited,
                "reason_counts":dict(sorted(self.reasons.items()))}

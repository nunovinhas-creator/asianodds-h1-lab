"""Nonblocking GitHub FT workflow watchdog, run independently of the Telegram read.

No sports API calls here. A failed recent attempt holds the same minimum
spacing, but is explicitly reported and never treated as healthy.
Conservatively dispatch LAB FT only if no real scheduled/manual FT workflow
was created in the preceding 35 minutes. Unauthenticated push runs are ignored.
The GitHub API token stays in the authorization header and is never logged.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OWNER_REPO = "nunovinhas-creator/asianodds-h1-lab"
SOURCE_WORKFLOW = "H1 - Collect Telegram"
TARGET_WORKFLOW = "lab-ft-results.yml"
MIN_AGE = timedelta(minutes=35)
STATUS_SKIPPED = "FT_WATCHDOG_RECENT_RUN"
STATUS_DISPATCHED = "FT_WATCHDOG_DISPATCH_ACCEPTED"


def _utc(x):
    if not isinstance(x,str):
        raise ValueError("Missing GitHub run time")
    dt=datetime.fromisoformat(x.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Naive GitHub timestamp")
    return dt.astimezone(timezone.utc)


def plan(runs, now):
    """Return safe dispatch decision. Invalid/missing fields fail closed."""
    if not isinstance(runs,list) or len(runs)>100 or now.tzinfo is None:
        raise ValueError("Invalid workflow run list or clock")
    candidates=[]
    for entry in runs:
        if not isinstance(entry,dict):
            raise ValueError("Invalid GitHub run entry")
        when=_utc(entry.get("created_at"))
        if when>now+timedelta(minutes=2):
            raise ValueError("GitHub run timestamp in the future")
        event = entry.get("event")
        if event is not None and event not in ("schedule", "workflow_dispatch"):
            continue  # notably push: NO authenticated FT scan
        candidates.append((when, entry.get("status"), entry.get("conclusion")))
    newest = max(candidates, key=lambda row: row[0]) if candidates else None
    when, status, conclusion = newest or (None, None, None)
    age = now - when if when is not None else None
    active = any(status in {"requested", "queued", "pending", "waiting", "in_progress"}
                 for _, status, _ in candidates)
    dispatch = not active and (age is None or age >= MIN_AGE)
    if active:
        reason = "ACTIVE_RUN"
    elif conclusion and conclusion != "success":
        reason = "STALE_FAILED_ATTEMPT" if dispatch else "FAILED_ATTEMPT_COOLDOWN"
    elif dispatch:
        reason = "NO_RECENT_ATTEMPT"
    else:
        reason = "RECENT_ATTEMPT"

    return {
        "dispatch":dispatch,
        "reason":reason,
        "latest_ft_run_at":when.isoformat(timespec="seconds") if when else None,
        "latest_ft_conclusion":conclusion,
        "age_minutes":round(age.total_seconds()/60,2) if age is not None else None,
        "minimum_age_minutes":int(MIN_AGE.total_seconds()/60),
    }


def _json_request(opener, request):
    with opener(request,timeout=10) as resp:
        body=resp.read(2_000_001)
        if len(body)>2_000_000:
            raise ValueError("GitHub run list too large")
        if getattr(resp,"status",200)!=200:
            raise ValueError("Unexpected GitHub response")
        return json.loads(body)


def run(*, env=None, now=None, opener=urlopen):
    e=os.environ if env is None else env
    if (e.get("GITHUB_WORKFLOW")!=SOURCE_WORKFLOW
            or e.get("GITHUB_REF")!="refs/heads/main"
            or e.get("GITHUB_REPOSITORY")!=OWNER_REPO
            or e.get("GITHUB_EVENT_NAME") not in ("workflow_dispatch","schedule","push")):
        return {"status":"FT_WATCHDOG_CONTEXT_SKIP","dispatched":False}
    token=e.get("GITHUB_TOKEN")
    if not token:
        return {"status":"FT_WATCHDOG_NO_TOKEN","dispatched":False}
    now=datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    base="https://api.github.com/repos/"+OWNER_REPO+"/actions/workflows/"+TARGET_WORKFLOW
    headers={
        "Authorization":"Bearer "+token,
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"master-brain-lab-ft-watchdog",
    }
    req=Request(base+"/runs?branch=main&per_page=100",headers=headers)
    try:
        payload=_json_request(opener,req)
        if not isinstance(payload,dict):
            raise ValueError("Invalid GitHub API payload")
        choice=plan(payload.get("workflow_runs"),now)
        if not choice["dispatch"]:
            return {"status":STATUS_SKIPPED,"dispatched":False,**choice}
        body=json.dumps({"ref":"main","inputs":{"trigger_source":"h1-ft-watchdog"}}).encode()
        dispatch=Request(base+"/dispatches",data=body,
                         headers={**headers,"Content-Type":"application/json"},method="POST")
        with opener(dispatch,timeout=10) as response:
            if response.status!=204:
                raise ValueError("GitHub refused workflow dispatch")
        return {"status":STATUS_DISPATCHED,"dispatched":True,**choice}
    except (HTTPError,URLError,OSError,ValueError,KeyError,TypeError):
        # Fail closed. Never print provider keys or GH auth response body.
        return {"status":"FT_WATCHDOG_GITHUB_UNAVAILABLE","dispatched":False}


def main():
    outcome=run()
    if outcome.get("reason") == "FAILED_ATTEMPT_COOLDOWN":
        print("::warning title=FT watchdog::Latest FT attempt failed; bounded retry interval still active.")
    print(outcome["status"],
          "dispatched",outcome["dispatched"],
          "latest_ft_run_at",outcome.get("latest_ft_run_at"),
          "conclusion",outcome.get("latest_ft_conclusion"),
          "reason",outcome.get("reason"))
    return outcome


if __name__=="__main__":
    main()

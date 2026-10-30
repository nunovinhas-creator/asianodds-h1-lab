"""Post-FT read-only integrity gate; records evidence, never certifies uptime.

No API requests, secrets, data writes, H1 mutations or Telegram messages.
"""
from __future__ import annotations
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from scripts.audit_health import check

CRITICAL = frozenset({
    "ft_counts", "ft_journal", "ft_backlog", "ft_publication",
    "ft_backlog_publication", "h1_replay",
})


def evaluate_health(health, *, upstream="not_applicable"):
    """Return a fail-closed assessment for one observation, not a 7-day SLA."""
    checks = {item.get("name"): item.get("status")
              for item in health.get("checks", [])
              if isinstance(item, dict)}
    blocked = sorted(name for name in CRITICAL if checks.get(name) != "OK")
    if upstream not in ("not_applicable", "success"):
        blocked.append("upstream_ft_run_failed")
    failed = health.get("status") == "FAILED" or bool(blocked)
    warnings = sorted(k for k, v in checks.items() if v != "OK")
    return {
        "status": "FAILED" if failed else "DEGRADED" if warnings else "OK",
        "critical_checks": {name: checks.get(name, "MISSING")
                            for name in sorted(CRITICAL)},
        "blocked": blocked,
        "non_ok_checks": warnings,
        "upstream_ft_run": upstream,
        "stable_24h_48h_7d": "NOT_PROVEN_BY_SINGLE_OBSERVATION",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--upstream", default="not_applicable")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    health = check(args.root, now)
    assessment = evaluate_health(health, upstream=args.upstream)
    result = {"schema_version": 1,
              "observed_at_utc": now.isoformat(timespec="seconds"),
              "root_commit": os.environ.get("GITHUB_SHA", "local"),
              "health": health, "assessment": assessment,
              "limitations": [
                  "One observation does not prove 24h, 48h or 7d stability.",
                  "Committed snapshots do not prove external Telegram/Page delivery.",
                  "Provider request quotas and FT evidence remain independently gated.",
              ]}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print("FT_INTEGRITY_GATE", assessment["status"],
          "blocked", ",".join(assessment["blocked"]) or "none",
          "non_ok", ",".join(assessment["non_ok_checks"]) or "none")
    if assessment["status"] == "DEGRADED":
        print("::warning::FT operational evidence is DEGRADED or inconclusive")
    if assessment["status"] == "FAILED":
        print("::error::FT publication, journal or upstream integrity gate failed")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

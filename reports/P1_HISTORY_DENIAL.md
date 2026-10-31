# P1: stop repeating provider-confirmed rejected date lists

Real API-Football error (audit 2026-10-30 22:36:42 UTC): Free plans do not have access to this date, try from 2026-10-29 to 2026-10-31. It rejected date 2026-10-28, but the old regex produced an empty restriction registry. The regression failed before the fix.

Recognize the explicit denial. Restore already-paid-for date refusals from the existing bounded audit before planning HTTP. Offline replay identifies refusals for 2026-10-27 and 2026-10-28 and retains their actual observation timestamps. DAY_ONLY scope; no inferred moving window, ID endpoint ban or restriction from quotas/timeouts. Repeated restore is idempotent.

Risk: provider wording may change; unrecognized text remains unrestricted rather than fabricating missing coverage. Old evidence does not imply global provider absence. Acceptance: authorized normal runs must not request these denied DATE lists again; ID eligibility, daily ceiling and real FT verification unchanged. No results newly certified by this offline test. No H1/Telegram/strategies modified; no merge.

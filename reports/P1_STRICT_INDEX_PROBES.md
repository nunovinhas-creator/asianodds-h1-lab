# P1: reuse complete cached identities for bounded ID requests

The baseline index already contains 28 initial strict pair/time candidates among 191 overdue fixtures (5-minute window); these are locators, not FT proof. With cooldown, collision and source checks, 17 are eligible across the full overdue population at inspection; only the actual next 30 queue slots can be probed.

Previously the unapproved strict identities could only use DATE lookup, including historical dates explicitly rejected by the free plan. This independent change routes exact/CORE_NAME identities from the complete index to one shared ID batch, replacing a date slot. It NEVER manufactures human approvals or uses fuzzy matches. The reviewed and strict IDs share one request/cache; max 20 IDs, max 3 total requests, existing daily ceiling unchanged.

Locks source fixture/team/competition IDs, exact provider names/time, observed identity and complete-day collision proof. Keeps 90-minute ambiguity detection, a stricter 5-minute accepted kickoff bound, 3h grace, 4h operational cooldown, adaptive evidence cooldown and 30-day horizon. Delegates FT score/status checks to unchanged _score; PEN/AET, identity changes and score conflicts rejected. Existing FINAL never planned.

Acceptance: actual free-tier ID endpoint response, new verified FT attributable to baseline keys, shared request count within caps and zero certified history changes. The free plan may reject ID requests too: availability is UNPROVEN until an authorized production run. Simulated successes are not real recovered FT. No new provider or secret, H1, Telegram, strategy or merge.

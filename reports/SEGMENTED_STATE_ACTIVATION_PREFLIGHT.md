# MASTER BRAIN — Segmented discovery-state activation preflight (NOT ACTIVATED)

## Why

The normal productive writer still writes `data/lab/discovery-state.json` with a **2,000,000-byte** cap. The already integrated segmented store (`h1lab/lab_discovery_store.py`) has verified local atomic CAS, shards, legacy-byte recovery and rollback but is **not** imported by the productive producer. Public `discoveries.json` was already paginated by #163 and is a different capacity problem.

## This PR

Adds `python -m scripts.lab_discovery_activation_preflight` (offline, read-only on the repository) and regression tests. It:

1. Reads the actual legacy state and three actual source inputs without network.
2. Publishes a segmented snapshot to an automatically deleted **external temporary directory**.
3. Verifies byte-for-byte legacy reconstruction and object parity.
4. Runs the real `discovery_timeline.build` producer on original versus reconstructed states; requires identical resulting state, public projection and event history.
5. Produces the public page manifest from both projections and checks byte-identical root/pages, hash integrity and full pattern count.
6. Appends **synthetic-only** metadata until the state is over 2.1 MB, proves the segmented store can write and recover it, then performs an explicit pointer-CAS rollback to the baseline and verifies exact recovered bytes.
7. Enumerates path-literal consumers to support a manual producer/reader inventory. The list is **static/heuristic**, not proof that dynamic imports or generated paths are covered.
8. Exits nonzero on discrepancy. Prints `PASS_OFFLINE_NOT_ACTIVATED` only after a successful isolated proof.

No productive imports, legacy data, GitHub Pages data, workflows, H1, strategies, Telegram, FT certification, budgets or schedules are changed. No release flag is exposed.

## Required *separate* activation PR and explicit authorization

- Freeze and hash a normal published baseline, the legacy state, FT ledger, monthly discovery archives and current public manifest/pages. Keep a comparison of all preexisting FINAL `match_key` values, identities and scores.
- Inventory **all** productive discovery consumers, including tests, dashboards, offline monitors, publication guards, shadow workflows and archive-recovery scripts. Migrate all readers to a common strict loader while the legacy source remains a verified mirror; missing/corrupt segmented data must fail closed, not silently fall back.
- Stage and seal `CURRENT.json`, `PREVIOUS.json`, manifests, every referenced shard and compressed legacy recovery bytes as a complete reachability-verified Git bundle; run the publication check both before and after any rebase. Do not publish a pointer before its members. Git remote compare-and-swap/rebase conflict is separate from the local filesystem `flock`.
- Run tests for stale concurrent writers, missing shards, corruption, incomplete Git add, interrupted workflow, ref update conflict and explicit rollback; ensure a failed publication leaves the last complete Git commit untouched.
- Observe one push cycle and successive **normal** watchdog cycles, with Pages byte/hash parity, unchanged previous FINAL records and dashboard compatibility. Only then consider ceasing the legacy mirror in another explicit approval step.
- Prepare a separate versioned policy for unreferenced immutable generations; never delete currently or previously reachable shards as opportunistic cleanup.

This PR produces migration-readiness evidence only, **not** an operationally migrated store or permission to remove the 2 MB guard. Until activation, the legacy state can still reach 2 MB and block the producer. Track remaining margin every normal cycle and escalate before exhaustion. The FT old-cohort recovery mission remains separate and open.

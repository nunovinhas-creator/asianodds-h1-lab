# MASTER BRAIN — opt-in dual state adapter (NOT ACTIVATED)

## Functional scope of this PR

A **real dual state adapter** and a producer CLI integration are prepared to validate byte-identical legacy/segmented snapshots during a controlled transition. The existing productive workflow still invokes `python -m scripts.lab_discoveries` **without any arguments**, which selects the unchanged `legacy` backend. No generated segments, pointers or new files are added to the current FT publication.

- `h1lab/lab_discovery_dual_state.py` exposes `bootstrap(root)`, `load(root, format="legacy"|"dual")`, `current_generation(root)` and `write_dual(root, state, expected_generation)`.
- `scripts/lab_discoveries.py --state-backend dual` is **explicit opt-in**, not controlled by an undocumented environment flag. Dual mode requires an already verified bootstrap and refuses missing/corrupt segment objects. It compares exact legacy bytes with segmented recovery before building the discovery timeline.
- The dual writer requires a generation CAS token, preserves the mandatory 2,000,000-byte mirror limit, writes the segment generation/pointer first and then atomically replaces the legacy mirror. A process crash between those two operations yields a *visible mismatch*, never a silent older-state fallback. An eventual Git publication step must atomically stage and verify all members.
- Legacy mode remains the default, including initially unpopulated discovery state; all existing H1, FT, quotas, Telegram, public JSON pagination and discovery archives remain unchanged.
- Tests build the real producer on isolated legacy and dual roots using actual repository snapshots and compare both public/durable outputs; test bootstrap byte-exactness, stale-writer refusal, pointer corruption, mirror tampering, oversized state, prior-generation retention and explicit rollback mismatch.

## What this does NOT yet provide

**This is NOT authorization to activate migration.** The productive `.github/workflows/lab-ft-results.yml` does not bootstrap/enable dual mode or Git-add the segmented root. The #165 Git integrity seal is offline and NOT wired to `publication_guard`. Remote Git ref CAS/rebase retry, full consumer inventory, reading via a shared loader in every workflow, Git bundle atomicity, monitoring and explicit rollback of the mirror+pointer pair remain separate activation acceptance criteria.

The dual phase is a *migration safety bridge*, not the 2 MB capacity solution: as long as the legacy mirror is mandatory, its limit remains and can block new observations. A later reviewed phase may move to segmented-authoritative storage and retain the byte-exact historical recovery archive, but removal of the live legacy mirror requires a separately authorized, tested change with no silent fallbacks.

## Required review sequence

1. Confirm merge compatibility with #164 and #165, complete green offline/no-network CI and full parity with real snapshots.
2. Prepare a **different controlled activation PR** that inventories every producer/reader, adds only reachable segments to the Git index, seals them with #165, handles remote ref conflicts by recomputation, and tests forced cancellation/recovery. No cutover through a repo variable alone.
3. Freeze source commit and the old FINAL match/score set; verify the full discovery history and all public pages. One authorized cutover commit must include all readers and writable segments. Keep rollback explicit with SHA and no forced pushes.
4. Verify at least one normal FT watchdog and GitHub Pages publication before declaring the dual phase healthy. Do not remove the live legacy mirror or the 2 MB limit without another authorization.

Refs #107, #162, #164, #165. No H1, betting strategies, Telegram or API provider configuration changed.

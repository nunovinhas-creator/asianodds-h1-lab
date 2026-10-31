# P1 — Fail-closed Git publication proof for segmented discovery (OFFLINE)

## Scope

The existing offline `lab_discovery_store` proves atomic generation writes under a POSIX lock. **It does not prove that a GitHub Actions commit or GitHub Pages deployment contains the complete generation.** A remote Git rebase, truncated `git add`, missing legacy mirror or stale pointer could otherwise publish an inconsistent snapshot.

`h1lab/lab_discovery_git_bundle.py` adds a separate, side-effect-free Git proof for future activation:

- `seal(repo, ref="INDEX")` verifies the **Git index**, not untracked working-tree bytes. Requires the existing `data/lab/discovery-state.json` mirror and `data/lab/discovery-segmented/CURRENT.json`, validates pointer and manifest digests, every currently and previously reachable shard and compressed legacy archive, and byte-exact legacy state equality.
- Includes all reachable object names and SHA-256 digests in the proof; rejects partial/stale index, symlinks, malformed shard paths, duplicate/missing content, altered mirror and staged temporary or unreachable files.
- `verify_against_seal(repo, seal, ref="HEAD")` repeats the full proof on committed Git bytes and rejects any change in the generation, manifest, mirror or shards after commit/rebase.
- Stores nothing in production and has no workflow/loader import. Test repos use local git commits only, no remote/network, no secrets, no FT calls.
- The `PREVIOUS.json` generation, when present, must itself be complete and verifiable. It cannot be treated as automatic fallback when CURRENT is corrupt.

## Important limitations

This helper only proves a **complete single local Git index/HEAD snapshot**. It does **not** implement remote Git ref compare-and-swap, prevent a future writer from rebasing an outdated logical generation, or activate a full dual-reader state loader. Those must be implemented and independently regression-tested in the final activation PR.

The existing 2 MB legacy mirror remains mandatory here; a later phase to remove it requires a separate explicit approval, comprehensive reader inventory and rollback protocol. No claim is made that the current production state can grow past 2 MB while the mirror and legacy writer remain active.

**No merge or migration authorization is implied by this PR.**

## Acceptance before productive activation

1. Integrate a read-only activation preflight (#164) and a verified Git-bundle seal (this PR), after approval.
2. Wire the shared state loader, writer, Git stage/publish/verify workflow with a dual-write mirror phase.
3. Validate remote ref conflicts, two different concurrent FT runs, rebase/retry semantics, missing last shard, corrupted PREVIOUS, 2 MB mirror overflow and safe rollback.
4. Confirm every old FINAL score/status and every discovery event is unchanged, normal FT checks and Pages deploy work, H1/strategies/Telegram remain intact.
5. Receive a **new explicit authorization** to merge/activate productive segmentation.

This is strictly a P1 safeguard for issue #107, not an FT certification change.

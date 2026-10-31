# P1 FT — segmented Git publication gate (conditional, NOT activated)

## Why this change exists

#164 demonstrated the existing state can be reconstructed in a segmented temporary store. #165 added a read-only index/HEAD integrity proof. #166 prepared an explicit optional dual writer/reader. **The real FT publication guard still had no linkage to the #165 proof**, so switching the producer without checking the stage could publish a CURRENT pointer while missing a shard or with a mismatched legacy source.

This PR closes **only** that publication-integrity gap. It does not switch the FT producer, bootstrap any segmented state, or stage any new production objects.

## Contract

- On normal legacy-only publication, there are no `data/lab/discovery-segmented/` tracked index entries. The existing `publication_guard seal` and `verify` still apply, with `segmented: null` recorded in the ephemeral seal; no new data generated and no extra network calls.
- Once a future **separately authorized** activation stages CURRENT and generation members, `publication_guard seal` uses `lab_discovery_git_bundle.seal(ref="INDEX")` to require the legacy mirror, CURRENT, optional PREVIOUS, all reachable manifest files, each SHA-verified shard and compressed legacy recovery file. Missing files, malformed paths, staged orphan data, modified scores or legacy/segment parity mismatch abort before commit.
- Every member is included in the existing Git publication seal, so any change during the `git fetch/rebase` cycle must fail. `publication_guard verify` also regenerates a full `HEAD` bundle verification and rejects a segmented generation introduced from outside the original seal.
- A partially staged segmented directory with no CURRENT is always rejected. Old unreachable complete generations may remain, but changed unreachable files cannot ride along in a new segmented commit.

## Proven by local Git tests

- Legacy-only publication remains unchanged.
- Full staged and committed generation contains all reachable files.
- Missing CURRENT, missing shard, mismatched mirror, orphan files, corruption and post-seal changes are rejected.
- CURRENT and PREVIOUS generations both validated, and remote/rebase appearance of a new generation after a legacy seal is rejected.
- All new tests use temporary local Git repositories and synthetic state. Zero HTTP/provider interaction.

## Not implemented here / remaining explicit gates

No production `--state-backend dual`, no bootstrap, no Git-add of segmented paths, no new feature flag or schedules. **The 2 MB legacy hard cap remains**. An activation PR must still include a controlled freeze/complete initial bootstrap, all consumers, explicitly staged generation members, logical CAS of remote Git refs and recomputation on an update conflict, strict rollback of both legacy mirror and pointers, and normal FT/Pages monitoring. Another authorization is required before activation, and another before removing the mirror cap.

No H1, strategies, Telegram, API quotas or FT certificate admission changes. Issue #107.

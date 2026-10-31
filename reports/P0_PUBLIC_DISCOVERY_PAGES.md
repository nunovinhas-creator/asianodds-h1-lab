# P0 — Public discovery pagination (proposed, no production merge)

## Incident and motivation

The previous public `docs/lab/discoveries.json` root was approaching 1,400,000 bytes. Its `bounded_public()` projection can remove old per-pattern points but **cannot remove one mandatory latest point/pattern**. The 1,120-pattern synthetic enlargement previously exceeded the cap even after dropping old points.

This PR prepares a **lossless, content-addressed public pattern layout** while leaving `data/lab/discovery-state.json` and monthly `discovery-events-YYYY-MM.jsonl` archives unchanged.

## Public read contract

- Root remains `docs/lab/discoveries.json`, schema_version 1, with the complete timeline, prospective summary, status and other existing non-pattern fields.
- New `pattern_count`, `pattern_pages` and `public_cache.layout=CONTENT_ADDRESSED_PATTERN_PAGES_V1` announce pagination; the on-disk `patterns` object is empty.
- Each `docs/lab/discovery-pages/<SHA256>.json` contains a non-overlapping subset of complete `patterns` (including all prior public points). A page is <=256,000 bytes, and its descriptor contains exact SHA-256, byte length and pattern count.
- The browser fetches pages with concurrency <=4, checks the full byte digest, rejects duplicate/missing/invalid pages and restores the original `patterns` object before rendering. Legacy non-paginated data still works. Any missing/corrupt page blocks discovery rather than presenting partial evidence.
- No base64 encoding or new external dependency is required. All content remains JSON.

## Publication contract

- Build and validate the entire root/page set before archive or state mutation.
- Produce immutable pages before the root in the local workflow workspace.
- Stage all referenced pages with the root in the same FT Git commit. `publication_guard seal` verifies the manifest against the staged page bytes and includes them in the rebasing integrity seal; `verify` refuses changed committed bytes.
- The current **1.4 MB public root** and **2 MB durable state** caps remain unchanged. Oversized individual patterns or non-pattern root metadata continue to fail closed. No silent truncation or synthetic FT.

## Evidence and limits

The PR includes deterministic growth (1,120 patterns), actual committed public snapshot roundtrip, full actual producer offline replay, missing/modified page rejection, Git publication-seal tampering tests and a Node VM browser loader integrity test.

**Still required before merge**: CI green on the final head, end-to-end normal FT publication in a controlled environment, browser reload under real GitHub Pages, proof of exactly matching root/pages for the published commit and FT history invariants. A PR check does not prove productive delivery. The proposed public format is not activated merely by creating this PR.

Content-addressed old pages are retained; a separately reviewed policy for unreachable-page archival/garbage collection is needed for long-term repository growth. The root can still reach its own fixed limit if non-pattern fields or page descriptors grow excessively; this correction covers the demonstrated pattern-catalogue bottleneck, not unbounded growth of every data type.

## Boundaries

PR #162 is integrated as **offline-only** segmented durable-state preparation. The legacy productive state loader remains active. PR #160 remains unmerged pending independent original-competition identity proof. No modification to H1, odds, strategies, Telegram, FT certificate admission rules, provider calls, quotas or scheduled tasks.

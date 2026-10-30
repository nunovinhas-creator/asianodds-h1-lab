# #149: publication validated; automatic monitor trigger gap

Read-only snapshot: a3c0df69be817809f5f9a36b03869c9799c79ef1.

## Evidence

- Normal watchdog runs 41130414536 (21:21 UTC) and 41135227280 (22:01 UTC) succeeded: 220 -> 234 -> 238 FINAL; bundles of 26 files verified before publication.
- Baseline 255cafa6669b79a048cf6c7311e2d06059da1394: all 220 FINAL results remain identical in the current ledger; zero missing/downgraded/changed results.
- discoveries.json: 1,362,334 / 1,400,000 bytes, margin 37,666. Durable discovery-state.json: 1,427,716 / 2,000,000 bytes, margin 572,284 (28.61%).
- Six critical offline invariants pass. Overall INCONCLUSIVE is intentional: one observation cannot certify uptime or external delivery.
- GitHub workflow 401923792 is active; name matches upstream, default-branch file exists. Latest monitor is 41128356774 (21:05:33, push completion). The two watchdog completions have no monitor run, queued run, cancellation or skipped execution in the workflow-specific run listing.
- A scheduled monitor did run at 20:52:47 (41126678555), substantially later than its :17 cron. Schedule delay is observable separately; waiting for cron does not guarantee monitoring each watchdog completion.

## Diagnosis and independent change

Missing completion trigger, rather than a monitor job failing or being skipped. Watchdogs dispatch with github.token; both FT runs have github-actions[bot] as actor/triggering_actor. GitHub documents suppression of events caused by GITHUB_TOKEN, except dispatch events. This is consistent with the observed distinction between push/schedule and watchdog runs; GitHub's internal event suppression decision is not directly observable. No claim of a proven scheduler-internal root cause.

The FT workflow now calls the read-only monitor as a reusable workflow through an explicit job dependency. `always()` covers successful, failed and skipped reconciliation; the caller result is passed into the fail-closed gate. No secrets inherited, contents:read only, evidence artifact retained on failure. Existing workflow_run/cron/manual fallback monitors remain. No H1, strategies, Telegram, provider quotas or result files changed.

## Capacity and limits

#149 compacts only the public point cache, preserving every pattern/latest FT and at least its latest point. Durable state and monthly archives are untouched. The existing growth regression exercises 100 cycles, plus failure/retry. Mandatory content is not arbitrarily bounded forever: if latest-pattern content alone or durable state reaches its limit, publication still fails closed. Do not promise indefinite capacity from the current margin.

## Acceptance

Unit regression and real snapshot offline gate pass. Production automatic monitor acceptance requires authorized merge of this independent correction and observing the next normal FT cycle with integrity/health in the same run. A separate Actions run ID is not required for a reusable job. No manual dispatch or sports API request used to manufacture evidence. #145, #146, #148, #147 remain unmerged; after that one normal monitored cycle passes, there is no capacity-related reason to prolong their suspension. Overall #107 24h/48h/7d validation remains separate.

# Telegram: proven short-error framing defect; account access still blocked

Refs #107. All timestamps UTC. No credential values, auth-key identifiers,
endpoint addresses or wire payloads are included in this report.

## PR 252 and baseline

[PR 252](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/252) was reviewed
and merged with the owner's explicit authorization at 2026-11-05 23:31:38,
commit `87e29120aa83284d2ae2946b79273668dfbd2526`.
[Its final Python 3.11 CI](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42128959241)
passed on exact head `019abf671dd6d505e89f38ebb82443cce8b05ec5`. Other checks
passed; the conditional research-publication job was skipped as intended.
No required checks were reported by GitHub. The review preserved concurrency,
H1/scientific rules, E5 publication and historical data.

The framing correction is based on main `94f34b027be77f5f820607bd4ed965b6163906ba`.
The audited session/reader files and Telethon 1.45.0 pin were unchanged after the
pause. The production timeout under PR 252 was still `CONNECT`; that label
includes both network establishment and initialization RPCs, not just TCP.

## Phase evidence from GitHub runners

1. [Transport diagnostic 42130390983](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42130390983),
   2026-11-05 23:34:38: configured session metadata was DC4, IPv4, port 443.
   DNS was not applicable because StringSession stores a literal IP. Production's
   default `use_ipv6=False` would not replace this session DC. TCP and an
   unauthenticated `req_pq_multi`/`resPQ` exchange using the default TCP Full mode
   succeeded in 0.338s. This is transport evidence, not account authorization or
   a full new-key negotiation; no new key was generated. No obfuscated fallback
   was needed or adopted.
2. [Initialization diagnostic 42130997122](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42130997122):
   the sender connected with the existing key in ~0.17s, but the exact
   `InvokeWithLayer(InvokeWithoutUpdates(InitConnection(help.getConfig)))` RPC
   timed out at 12s. It stopped before `get_me`, GetState, login or channel access.
   Initial `packets_sent` instrumentation measured queue admission, not a wire
   acknowledgment; the next diagnostic refined that measurement.
3. [Final bounded diagnostic 42131359921](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42131359921),
   23:42:15–23:42:27: sender connection succeeded, one socket drain completed,
   and **four bytes representing the public transport error -404 remained
   buffered**. The TCP socket was still connected. No complete frame reached
   the MTProto decoder, so the RPC expired. Its sanitized receipt records
   `buffered_transport.short_transport_error=AUTH_KEY_NOT_FOUND` and
   `unframed_receive_bytes=4`, not the raw bytes.

These three diagnostic runs used only existing GitHub secrets on the runner.
They did not authenticate/query the account, read the channel, change the session,
collect data, send alerts or call result/LLM providers. Their receipt artifacts
and job logs are attached to the linked runs. Production-data diff checks passed.

## Demonstrated cause and narrow correction

Telethon 1.45.0 `FullPacketCodec.read_packet()` starts with `readexactly(8)`.
A server returning only four bytes for -404 while keeping TCP open therefore
leaves the reader waiting, masking the server error as `TELEGRAM_TIMEOUT CONNECT`.
The exact behavior was reproduced offline with an open StreamReader.

The correction recognizes the four-byte -404 prefix and passes it to Telethon's
existing MTProto decoder. That decoder maps it to **AuthKeyNotFound**. Every other
packet still uses the pinned upstream codec, retaining CRC, length/sequence,
fragmentation, EOF and existing flood-error behavior. It keeps TCP Full, the
same endpoint and the existing key; no retries or authentication bypass are added.

A subsequent cleanup-only change retrieves Telethon's completed `disconnected`
future so the same primary error is not also reported as an unhandled Future.
It never hides the primary error. An unexpected background disconnect failure
after an otherwise successful read still fails without advancing the cursor.

## Exactly one authentication probe after the correction

[Probe 42178954142](https://github.com/nunovinhas-creator/asianodds-h1-lab/actions/runs/42178954142),
2026-11-06, ran corrected code **`490de0c6523683f0c7622c4627659435f795b5e6`**.
It used the existing GitHub secrets without replacing any value. Log:

```text
07:09:14.049  TELEGRAM_PHASE_START CONNECT
07:09:14.220  TELEGRAM_PHASE_START DISCONNECT
07:09:14.220  TELEGRAM_PHASE_OK DISCONNECT
07:09:14.221  TELEGRAM_AUTH_KEY_NOT_FOUND
exit code 1
```

The failure was surfaced in ~0.17s instead of timing out. The live run also showed
Telethon's duplicate unhandled-Future warning; the cleanup-only follow-up is
covered by offline regressions, and **the real probe was not repeated**.

There was **no TELEGRAM_AUTH_PROBE_OK and no AuthKeyUnregisteredError**.
Telethon documents AuthKeyNotFound as potentially temporary or permanent.
The server does not recognize the presented key, but this alone does not prove
session revocation or identify why the key is unknown. **Do not automatically
rotate TG_SESSION.** No normal collection was manually dispatched after this
failed probe; the required two successful cycles remain blocked. Scheduled
production runs were not disabled, cancelled or counted as successful recovery.

## Validation and integrity

- 83 focused offline tests pass: 6 framing, 12 reader, 4 session, 8 workflow,
  53 E5. A real MTProtoSender with a synthetic key verifies the short reply
  becomes AuthKeyNotFound without key generation. Tests also verify primary-error
  preservation, no unhandled disconnect future and no checkpoint after failure.
- Compile and whitespace checks pass; no production-data diff is present.
- The initial full suite ran 1,892 tests and exposed one **baseline** failure:
  `test_audit_health` assumed the real collector was fresh although its checkpoint
  was 19:36:21 and the dashboard had been regenerated at 00:33:50. The identical
  failure was reproduced on unmodified main baseline `94f34b0`. Production health
  correctly reported STALE. The test now accepts truthful real-snapshot health
  and adds a deterministic stale/fresh collector fixture proving that dashboard
  regeneration cannot refresh the collector. All 17 health tests pass. No health
  threshold, production timestamp, historical data or monitoring logic changed.
- [PR 253 checks](https://github.com/nunovinhas-creator/asianodds-h1-lab/pull/253/checks)
  are authoritative for full Python 3.11 CI on the final head. Do not infer
  their final outcome from the focused offline pass.
- Last inspected production snapshot before the final probe: cursor `53069`,
  last poll `2026-11-05T19:36:21+00:00`; E5 has 158 entries (155 sent, 3 existing
  delivery_uncertain_manual_review). State, H1 results CSV, E5 ledger, core rules
  and E5 sender were byte-identical to the PR 252 head at that inspection.
- `llm_live_enabled=false` and `llm_schedule_live_enabled=false`; no live LLM or
  result-provider request was made by these diagnostics or the authentication probe.

## Status

- **MERGED:** PR 252's deadlines, phase diagnostics and failed-read protection.
- **CAUSE PROVEN / FIX ON PR 253:** short -404 framing defect, with live before/after evidence.
- **BLOCKED:** account authentication, channel access, new H1 publication and two
  successful normal cycles. No E5 delivery or real collection recovery is claimed.
- **INCONCLUSIVE:** whether the unrecognized existing key is temporarily unknown,
  permanently invalid, or affected by another session/DC-side condition.

PR 253 does not authorize or perform a secret replacement. The earlier explicit
merge authorization covered PR 252; any further merge must respect the owner's
approval boundary. No scientific, historical, alert or concurrency rule was changed.

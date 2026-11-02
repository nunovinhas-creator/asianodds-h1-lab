"""OFFLINE DEMONSTRATION — non-certified FT observation checkpoint (not wired into any workflow).

Implements the proposal in docs/audit/ft-recovery-after-publication-rejection.md so it can be
reviewed and attacked before any production use. Nothing imports this module from the FT
producers, the publisher or a workflow; enabling it requires a separate, explicit approval.

A checkpoint keeps *raw provider observations* gathered by an FT run whose publication was
refused (incompatible code, transport failure), so a later run can re-derive the same evidence
with its own (current) parser instead of calling the provider again. It never contains ledger
rows and can never make anything FINAL: replay yields ``UncertifiedObservation`` objects that
must still go through the normal certification gates.

Guarantees enforced here:
* identity and provenance immutable: the document is sealed (sha256 of canonical JSON) and written
  once (``O_EXCL``); a second writer of the same run either finds the identical seal (idempotent) or
  is refused;
* original timestamp verifiable: ``observed_at`` is inside the seal and each body is hashed;
* code/config reference: ``code_commit``, ``remote_commit``, ``config_sha256``, ``adapter_version``;
* 24 h window respected: refused when the observation itself was made after kickoff+24 h, or when
  replay happens after kickoff+24 h (the checkpoint never extends the window);
* staleness bound (default 6 h), tamper detection, adapter compatibility (or exact re-derivation by
  the current parser), secret scrubbing check, and storage limits sized for the free plan.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 1
WINDOW = timedelta(hours=24)
MAX_AGE = timedelta(hours=6)
MAX_OBSERVATIONS = 200
MAX_BODY_BYTES = 64 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
SHA = re.compile(r"[a-f0-9]{40}\Z")
SECRET = re.compile(rb"(?i)(api[_-]?key|authorization|bearer\s|x-apisports-key|token=|\b\d{8,10}:[A-Za-z0-9_-]{30,})")


class CheckpointRefused(ValueError):
    pass


@dataclass(frozen=True)
class UncertifiedObservation:
    """Re-derived evidence. Deliberately has no status field and no promotion method."""
    match_key: str
    provider: str
    observed_at: str
    derived: dict
    checkpoint_run_id: str
    certified: bool = False

    def __post_init__(self):
        if self.certified:
            raise CheckpointRefused("A checkpoint observation can never be certified directly")


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise CheckpointRefused("Naive timestamp")
    return parsed.astimezone(timezone.utc)


def _canonical(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def build(*, run_id, code_commit, remote_commit, config_sha256, rejection_reasons, observations,
          created_at):
    if not SHA.fullmatch(code_commit) or (remote_commit and not SHA.fullmatch(remote_commit)):
        raise CheckpointRefused("Invalid code provenance")
    if not re.fullmatch(r"[a-f0-9]{64}", config_sha256 or ""):
        raise CheckpointRefused("Invalid configuration hash")
    if not observations or len(observations) > MAX_OBSERVATIONS:
        raise CheckpointRefused("Observation count outside limits")
    rows = []
    for obs in observations:
        body = obs["body"]
        if not isinstance(body, bytes) or len(body) > MAX_BODY_BYTES:
            raise CheckpointRefused("Observation body outside limits")
        if SECRET.search(body):
            raise CheckpointRefused("Observation body contains a credential-like value")
        kickoff, observed = _utc(obs["kickoff_utc"]), _utc(obs["observed_at"])
        if observed > kickoff + WINDOW:
            raise CheckpointRefused("Observation made after the 24 h window: " + obs["match_key"])
        rows.append({
            "match_key": obs["match_key"], "provider": obs["provider"],
            "kickoff_utc": kickoff.isoformat(), "observed_at": observed.isoformat(),
            "http_status": int(obs["http_status"]), "adapter_version": str(obs["adapter_version"]),
            "endpoint_sha256": hashlib.sha256(obs["endpoint"].encode()).hexdigest(),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_b64": base64.b64encode(body).decode(),
        })
    doc = {"schema": SCHEMA, "kind": "FT_UNCERTIFIED_OBSERVATIONS", "run_id": str(run_id),
           "code_commit": code_commit, "remote_commit": remote_commit,
           "config_sha256": config_sha256, "created_at": _utc(created_at).isoformat(),
           "rejection_reasons": [str(r)[:300] for r in rejection_reasons][:20],
           "observations": sorted(rows, key=lambda r: (r["match_key"], r["provider"]))}
    doc["seal"] = hashlib.sha256(_canonical(doc)).hexdigest()
    raw = _canonical(doc)
    if len(raw) > MAX_FILE_BYTES:
        raise CheckpointRefused("Checkpoint exceeds the free-plan storage budget")
    return doc


def write_once(directory, doc, *, before_rename=None):
    """Atomic, single-writer. Returns the path; identical concurrent writes are idempotent."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ("ft-checkpoint-%s.json" % re.sub(r"[^0-9A-Za-z_-]", "_", doc["run_id"]))
    raw = _canonical(doc)
    tmp = directory / (".%s.%d.tmp" % (target.name, os.getpid()))
    with open(tmp, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if before_rename:
        before_rename()  # test hook: simulate a crash between write and publish
    try:
        os.link(tmp, target)  # fails if target exists: never overwrites
    except FileExistsError:
        os.unlink(tmp)
        existing = json.loads(target.read_bytes())
        if existing.get("seal") != doc["seal"]:
            raise CheckpointRefused("A different checkpoint already exists for run " + doc["run_id"])
        return target
    os.unlink(tmp)
    return target


def load(path):
    raw = Path(path).read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        raise CheckpointRefused("Checkpoint too large")
    doc = json.loads(raw)
    seal = doc.pop("seal", None)
    if seal != hashlib.sha256(_canonical(doc)).hexdigest():
        raise CheckpointRefused("Checkpoint seal mismatch (tampered or truncated)")
    doc["seal"] = seal
    if doc.get("schema") != SCHEMA or doc.get("kind") != "FT_UNCERTIFIED_OBSERVATIONS":
        raise CheckpointRefused("Unknown checkpoint schema")
    return doc


def replay(doc, *, now, parsers, trusted_run_ids, max_age=MAX_AGE):
    """Re-derive evidence with the CURRENT parsers. No network. Returns (reusable, refused).

    ``parsers[provider]`` is ``(adapter_version, parse(body, match_key) -> dict | None)``.
    An observation from another adapter version is reusable only if the current parser
    re-derives exactly what that version's parser would accept (it is simply re-parsed here;
    a ``None`` result refuses it).
    """
    now = _utc(now)
    if doc["run_id"] not in trusted_run_ids:
        raise CheckpointRefused("Checkpoint provenance not verified for run " + doc["run_id"])
    reusable, refused = [], []
    for row in doc["observations"]:
        body = base64.b64decode(row["body_b64"])
        key = row["match_key"]
        kickoff, observed = _utc(row["kickoff_utc"]), _utc(row["observed_at"])
        reason = None
        if hashlib.sha256(body).hexdigest() != row["body_sha256"]:
            reason = "body_hash_mismatch"
        elif observed > now:
            reason = "observed_in_future"
        elif observed > kickoff + WINDOW:
            reason = "observed_after_window"
        elif now > kickoff + WINDOW:
            reason = "window_elapsed_at_replay"
        elif now - observed > max_age:
            reason = "stale_observation"
        elif row["provider"] not in parsers:
            reason = "provider_parser_unavailable"
        elif row["http_status"] != 200:
            reason = "non_200_observation"
        if reason is None:
            version, parse = parsers[row["provider"]]
            derived = parse(body, key)
            if derived is None:
                reason = "not_rederivable_by_current_parser"
                if version != row["adapter_version"]:
                    reason = "adapter_incompatible"
            else:
                reusable.append(UncertifiedObservation(key, row["provider"], row["observed_at"],
                                                       derived, doc["run_id"]))
                continue
        refused.append((key, row["provider"], reason))
    return reusable, refused

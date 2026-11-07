"""Explicit per-file ownership matrix of every writer of ``main``.

One source of truth for the selective publishers (collector, LAB V4, and the
joint concurrency tests). ``owner_of(path)`` returns the producer that is the
ONLY legitimate writer of a path; publishers use it to decide whether a
concurrent remote change can be kept byte-for-byte or must be refused.

Being under ``data/lab/`` says nothing about ownership: the collector owns the
V4 market/format views and the V4 revision journal, LAB V4 owns the V6
forecasts/memories/archive index, FT owns ledgers, discovery state and FT
events. See docs/audit/collector-lab-publication-2026-11-02.md for the full
matrix with writers, readers and conflict policy.
"""
from __future__ import annotations

import re

COLLECTOR = "COLLECTOR"        # .github/workflows/collect.yml   (group asianodds-h1-write)
H1_RESULTS = "H1_RESULTS"      # .github/workflows/results.yml   (group asianodds-h1-write)
LAB_QUALITY = "LAB_QUALITY"    # .github/workflows/lab-quality.yml (group asianodds-h1-write)
FT = "FT"                      # .github/workflows/lab-ft-results.yml (group asianodds-lab-ft-results)
LAB_V4 = "LAB_V4"              # .github/workflows/lab-v4-audit.yml (group asianodds-lab-v4-audit)
LLM = "LLM_SHADOW"             # v6-llm-autonomous / v6-llm-investigator (group v6-llm-global)
OFFLINE_STATS = "OFFLINE_STATS"  # v6-offline-statistics.yml
PROGRAM = "PROGRAM"            # code/config: human merges only
DOCUMENTATION = "DOCUMENTATION"  # non-runtime prose and tests
LEGACY = "LEGACY_FROZEN"       # ledgers of disabled notifiers: nobody may write them
SITE = "SITE"                  # GitHub Pages UI code (docs/*.html|js|css): human merges only
MANUAL_REVIEW = "MANUAL_REVIEW"  # data/lab/golden/** (LAB V4 input), reports/**: human-reviewed

MONTH = r"\d{4}-\d{2}"
PART = r"(?:-part\d{4})?"

# --- collector -----------------------------------------------------------------------------
COLLECT_STATE = "data/state.json"
COLLECT_RENDERED = "docs/data.json"            # derived: state.json + results.csv (H1 re-renders it)
E5_LEDGER = "data/e5-over25-notifications.json"      # the ONLY active Telegram receipt ledger
THREE_LEDGER = "data/three-total-moves-notifications.json"   # retired 2026-11-02: frozen proof
TWO_LEDGER = "data/two-up-total-notifications.json"          # retired 2026-11-02: frozen proof
TELEGRAM_BLOCK = "data/telegram-delivery-block.json"
TELEGRAM_LEDGERS = (E5_LEDGER,)
MARKETS_VIEW = re.compile(r"data/lab/markets-" + MONTH + PART + r"\.jsonl\Z")   # mutable latest view
FORMATS_VIEW = re.compile(r"data/lab/formats-" + MONTH + PART + r"\.jsonl\Z")   # mutable latest view
V4_REVISIONS = re.compile(r"data/lab/v4-revisions-" + MONTH + PART + r"\.jsonl\Z")  # append-only SHA chain

# --- H1 results ----------------------------------------------------------------------------
H1_OWNED = frozenset({"data/results.csv", "data/result_audit.json", "data/health/h1-results.json"})

# --- LAB V4 (shadow audit) -----------------------------------------------------------------
LAB_V4_REPORTS = frozenset("docs/lab/%s.json" % n for n in (
    "v4-audit", "golden-candidates", "golden-report", "golden-priority", "v4-revisions",
    "v6-shadow", "v6-readiness", "v6-price-quality", "v6-feature-coverage", "v6-memory",
    "v6-falsification", "match-trajectories", "telegram-eligibility", "trajectory-research",
    "outcome-readiness", "v6-scientific-radar", "v6-weekly-drift", "v6-archive-health",
    "v6-p0-null-simulation", "v6-p0-gates"))
LAB_V4_ARCHIVE_INDEX = "data/lab/v6-archive-index.json"
LAB_V4_JOURNALS = re.compile(
    r"data/lab/(?:v6-forecasts-" + MONTH + PART +
    r"|v6-memory-(?:observations|patterns|hypotheses|evidence|decisions)-" + MONTH + PART +
    r"|v6-hypotheses|v6-weekly-snapshots|v4-runchecks(?:-" + MONTH + PART + r")?)\.jsonl\Z")

# --- FT ------------------------------------------------------------------------------------
FT_LEDGER = "data/lab/ft-ledger.json"
FT_EVENTS = re.compile(r"data/lab/(?:v6-ft-events|discovery-events)-" + MONTH + PART + r"\.jsonl\Z")
FT_PATTERNS = (
    re.compile(r"data/lab/ft-[a-z0-9-]+\.json\Z"),
    re.compile(r"docs/lab/ft-[a-z0-9-]+\.json\Z"),
    re.compile(r"data/lab/pattern-[a-z0-9-]+\.json\Z"),
    re.compile(r"docs/lab/pattern-[a-z0-9-]+\.json\Z"),
    re.compile(r"data/lab/discovery-state\.json\Z"),
    re.compile(r"docs/lab/discoveries\.json\Z"),
    re.compile(r"docs/lab/discovery-pages/[a-f0-9]{64}\.json\Z"),
    re.compile(r"data/lab/discovery-segmented/[a-f0-9]{64}/[A-Za-z0-9._-]+\Z"),
    re.compile(r"data/lab/discovery-segmented/(?:CURRENT|PREVIOUS)\.json\Z"),
    re.compile(r"data/lab/v6-pruning-(?:selection|catalog)-v\d+\.json\Z"),
    re.compile(r"docs/lab/(?:v6-ft-evidence|v6-pruning|v6-residual-research)\.json\Z"),
)

# --- LLM / statistics / quality --------------------------------------------------------------
LLM_PATTERNS = (re.compile(r"docs/lab/(?:llm-discovery-plan|llm-investigator-index)\.json\Z"),
                re.compile(r"docs/lab/llm-investigator-runs/\d+\.json\Z"),
                # Operational exploratory research (same v6-llm-global workflow slot; no writer
                # until the prepared migration is approved and activated).
                re.compile(r"data/research/memory\.jsonl\Z"),
                re.compile(r"docs/research/autonomous-research\.json\Z"))
OFFLINE_PATTERNS = (re.compile(r"docs/lab/llm-statistics\.json\Z"),
                    re.compile(r"docs/lab/llm-statistics-runs/\d+\.json\Z"))
QUALITY = "docs/lab/quality.json"

LEGACY_LEDGERS = frozenset({
    "data/pattern-notifications.json", "data/e4-notifications.json",
    "data/strategy-notifications.json", "data/t05-notifications.json",
    THREE_LEDGER, TWO_LEDGER})

PROGRAM_PREFIXES = ("h1lab/", "scripts/", ".github/", "config/", "scheduler/", "tools/")
# Seed of the central neuron-quota ledger. The operational ledger lives ONLY on the dedicated
# ``llm-quota-ledger`` branch (h1lab/research_quota.py, CAS writes); on ``main`` this file is an
# immutable human-merged seed, so it is PROGRAM-owned and every main publisher refuses it.
QUOTA_LEDGER_SEED = "data/research/quota-ledger.json"
PROGRAM_FILES = frozenset({"requirements.txt", "requirements-test.txt", ".gitignore",
                           QUOTA_LEDGER_SEED})
DOC_PATTERNS = (re.compile(r"tests/.+\Z"), re.compile(r"(?:docs|reports)/(?:[^/]+/)*[^/]+\.md\Z"),
                re.compile(r"[A-Za-z0-9_-]+\.md\Z"))
SITE_PATTERN = re.compile(r"docs/[A-Za-z0-9_.-]+\.(?:html|js|css)\Z")
# Static, human-merged DEMONSTRATION snapshot of the research panel (never written by a job).
SITE_DEMO_PATTERN = re.compile(r"docs/research/demo/[A-Za-z0-9_.-]+\.(?:json|jsonl)\Z")
MANUAL_PATTERN = re.compile(r"(?:data/lab/golden|reports)/.+\Z")


def is_collector_owned(path):
    return (path in (COLLECT_STATE, COLLECT_RENDERED, TELEGRAM_BLOCK) or path in TELEGRAM_LEDGERS
            or bool(MARKETS_VIEW.fullmatch(path) or FORMATS_VIEW.fullmatch(path)
                    or V4_REVISIONS.fullmatch(path)))


def is_lab_v4_owned(path):
    return path in LAB_V4_REPORTS or path == LAB_V4_ARCHIVE_INDEX or \
        bool(LAB_V4_JOURNALS.fullmatch(path))


# Immutable B1 evidence is human-reviewed material; no automated publisher owns it.
B1_AUDIT_FILES = frozenset({'evidence/b1/README.md', 'evidence/b1/real-plans.json',
                            'evidence/b1/replay.json'})


def owner_of(path):
    """Return the single owner of ``path`` (``docs/data.json`` -> COLLECTOR; H1 re-renders it)."""
    if path in B1_AUDIT_FILES:
        return MANUAL_REVIEW
    if path.startswith(PROGRAM_PREFIXES) or path in PROGRAM_FILES:
        return PROGRAM
    if is_collector_owned(path):
        return COLLECTOR
    if path in H1_OWNED:
        return H1_RESULTS
    if is_lab_v4_owned(path):
        return LAB_V4
    if path == FT_LEDGER or FT_EVENTS.fullmatch(path) or any(p.fullmatch(path) for p in FT_PATTERNS):
        return FT
    if any(p.fullmatch(path) for p in LLM_PATTERNS):
        return LLM
    if any(p.fullmatch(path) for p in OFFLINE_PATTERNS):
        return OFFLINE_STATS
    if path == QUALITY:
        return LAB_QUALITY
    if path in LEGACY_LEDGERS:
        return LEGACY
    if any(p.fullmatch(path) for p in DOC_PATTERNS):
        return DOCUMENTATION
    if SITE_PATTERN.fullmatch(path) or SITE_DEMO_PATTERN.fullmatch(path):
        return SITE
    if MANUAL_PATTERN.fullmatch(path):
        return MANUAL_REVIEW
    return None


def is_append_only(path):
    return bool(V4_REVISIONS.fullmatch(path) or LAB_V4_JOURNALS.fullmatch(path)
                or FT_EVENTS.fullmatch(path))

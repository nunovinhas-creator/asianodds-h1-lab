"""Registry of Telegram emitters. Since 2026-11-02 E5 is the ONLY active emitter.

Every other notifier module stays importable (its tests, its frozen ledger and its historical
receipts remain readable and immutable), but its command-line entry point refuses to send:
``python -m h1lab.<retired>`` exits without any HTTP request and without touching a ledger.
A read-only ``--dry-run`` stays available where the module offers one.
"""
from __future__ import annotations

import sys

ACTIVE = ("h1lab.e5_notify",)
RETIRED = (
    "h1lab.three_moves_notify",   # >= 3 distinct Total movements
    "h1lab.two_up_notify",        # >= 2 distinct Total rises without falls
    "h1lab.strategy_notify",      # E1, E2, E3, E4 (V5 selection) - E5 moved to e5_notify
    "h1lab.e4_notify",            # legacy E4
    "h1lab.t05_notify",           # T05
    "h1lab.pattern_notify",       # Pattern Watch notifier
    "h1lab.notify",               # H1 singles/triples
)


def refuse(module):
    """Entry-point guard of a retired emitter: no Telegram request, no ledger write."""
    print("::warning title=TELEGRAM_EMITTER_RETIRED::%s is retired; the only active Telegram "
          "emitter is %s. Nothing was sent." % (module, ACTIVE[0]))
    raise SystemExit(0)


def main_guard(module, argv=None):
    """Allow only a read-only --dry-run of a retired emitter; refuse anything else."""
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["--dry-run"]:
        refuse(module)

"""What adapters report while they solve, in one shape.

A backend calls `report(on_progress, kind, t, objective, bound)` from its
solver's callback. Infinities and NaNs -- "no answer yet", "no bound yet" --
become None, and nothing a listener does can break the solve it listens to.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


def finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and abs(number) < 1e20 else None


def report(on_progress, kind: str, t, objective, bound) -> None:
    if on_progress is None:
        return
    try:
        on_progress(kind, {"t": round(float(t), 3), "objective": finite(objective), "bound": finite(bound)})
    except Exception:  # pragma: no cover -- a listener's failure is its own
        logger.warning("progress listener failed", exc_info=True)

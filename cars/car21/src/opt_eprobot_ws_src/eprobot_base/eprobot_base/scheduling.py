"""Deadline scheduling shared by the chassis node's rate-limited outputs.

The control loop is sampled by a fixed timer.  A deadline that lands exactly
between two samples can skip a whole slot when the timer jitters by even a few
milliseconds (a 100 Hz timer feeding a 50 Hz deadline produced about 40 Hz).

``next_deadline_if_due`` accepts a small tolerance (normally half the control
period) so a sample close to a deadline still fires it.  When the loop has
fallen more than one whole period behind, the deadline is re-phased instead of
publishing a burst of catch-up messages.
"""

from __future__ import annotations

import math
from typing import Optional


def next_deadline_if_due(
    now: float,
    deadline: float,
    period: float,
    tolerance: float,
) -> Optional[float]:
    """Return the next deadline when ``now`` is due, otherwise ``None``.

    ``tolerance`` may advance a deadline by up to that amount.  A non-finite or
    non-positive period disables the output.  If the caller is more than one
    period late, the returned deadline is re-phased from ``now`` so a delayed
    loop does not emit a burst of back-to-back messages.
    """

    if not math.isfinite(period) or period <= 0.0:
        return None

    tolerance = max(0.0, float(tolerance))
    if now + tolerance < deadline:
        return None

    next_deadline = deadline + period
    if now - next_deadline > period:
        next_deadline = now + period
    return next_deadline

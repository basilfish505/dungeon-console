"""Player experience rewards from monster Elo ratings."""

from __future__ import annotations

import random

XP_BASE = 100
XP_REFERENCE_ELO = 800
XP_ELO_SCALING = 600

PQG_XP_DIVISOR = 10
PQG_VARIANCE = 0.30


def calculate_xp_from_elo(elo: float) -> int:
    """
    XP reward for defeating a monster with the given Elo rating.

    xp = round(XP_BASE * 2 ** ((elo - XP_REFERENCE_ELO) / XP_ELO_SCALING))
    """
    try:
        rating = float(elo)
    except (TypeError, ValueError):
        rating = float(XP_REFERENCE_ELO)
    raw = XP_BASE * (2.0 ** ((rating - XP_REFERENCE_ELO) / XP_ELO_SCALING))
    return round(raw)


def calculate_pqg_from_xp(xp, rng=None) -> int:
    """
    PQG reward from XP earned on a kill.

    base = xp / PQG_XP_DIVISOR
    pqg = round(uniform(base * (1 - PQG_VARIANCE), base * (1 + PQG_VARIANCE)))
    """
    try:
        xp_val = int(xp)
    except (TypeError, ValueError):
        xp_val = 0
    if xp_val <= 0:
        return 0

    base = xp_val / PQG_XP_DIVISOR
    low = base * (1.0 - PQG_VARIANCE)
    high = base * (1.0 + PQG_VARIANCE)
    roll = (rng or random).uniform(low, high)
    return max(0, round(roll))

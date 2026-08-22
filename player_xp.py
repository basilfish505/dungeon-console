"""Player experience rewards from monster Elo ratings."""

from __future__ import annotations

XP_BASE = 100
XP_REFERENCE_ELO = 2500
XP_ELO_SCALING = 800


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

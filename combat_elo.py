"""Live combat Elo updates for players and monsters.

Reuses the same Elo math as the monster tournament / spawn calibration.
"""

from __future__ import annotations

from monster_elo import K_FACTOR, MIN_ELO, update_elo


def rating_of(entity) -> float:
    """Read Elo from a player or monster; missing/invalid → 0."""
    try:
        return float(getattr(entity, 'elo', 0))
    except (TypeError, ValueError):
        return 0.0


def apply_elo_outcome(winner, loser, k: float = K_FACTOR):
    """
    Apply a decisive win for ``winner`` over ``loser``.

    Mutates both entities' ``elo``. Ratings never drop below ``MIN_ELO``.
    Returns (new_winner_elo, new_loser_elo, winner_delta).
    """
    old_w = rating_of(winner)
    old_l = rating_of(loser)
    new_w, new_l = update_elo(old_w, old_l, 1.0, k=k)
    new_w = max(MIN_ELO, new_w)
    new_l = max(MIN_ELO, new_l)
    winner.elo = new_w
    loser.elo = new_l
    return new_w, new_l, new_w - old_w

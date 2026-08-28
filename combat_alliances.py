"""Battle-scoped player alliances and modular reward-split policies.

Alliances are stored as pairwise bonds on the battle dict:

    battle['alliances'] = [['playerA', 'playerB'], ...]

Battle-end checks use the connected component of each participant so that
A-allied-to-B and B-allied-to-C form one alliance group of three. Reward
splitting is pluggable via ``REWARD_POLICY``.
"""

from __future__ import annotations


def _normalize_bond(a, b):
    if a is None or b is None or a == b:
        return None
    return tuple(sorted((str(a), str(b))))


def _bond_list(battle):
    bonds = battle.setdefault('alliances', [])
    if not isinstance(bonds, list):
        battle['alliances'] = []
        return battle['alliances']
    return bonds


def add_bond(battle, a, b):
    """Record a pairwise alliance bond. Returns True if newly added."""
    pair = _normalize_bond(a, b)
    if pair is None:
        return False
    bonds = _bond_list(battle)
    as_list = list(pair)
    for existing in bonds:
        if _normalize_bond(existing[0], existing[1]) == pair:
            return False
    bonds.append(as_list)
    return True


def are_allied(battle, a, b):
    """True if a and b share a direct bond."""
    pair = _normalize_bond(a, b)
    if pair is None:
        return False
    for existing in _bond_list(battle):
        if len(existing) >= 2 and _normalize_bond(existing[0], existing[1]) == pair:
            return True
    return False


def allies_of(battle, pid):
    """Direct allies of ``pid`` (not including ``pid``)."""
    pid = str(pid) if pid is not None else None
    if not pid:
        return []
    result = []
    for existing in _bond_list(battle):
        if len(existing) < 2:
            continue
        a, b = str(existing[0]), str(existing[1])
        if a == pid:
            result.append(b)
        elif b == pid:
            result.append(a)
    return result


def alliance_group(battle, pid):
    """Connected component containing ``pid`` (includes ``pid``)."""
    pid = str(pid) if pid is not None else None
    if not pid:
        return []
    # Adjacency from all bonds
    adj = {}
    for existing in _bond_list(battle):
        if len(existing) < 2:
            continue
        a, b = str(existing[0]), str(existing[1])
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    if pid not in adj:
        return [pid]
    seen = set()
    stack = [pid]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for neigh in adj.get(cur, ()):
            if neigh not in seen:
                stack.append(neigh)
    return sorted(seen)


def remove_player(battle, pid):
    """Drop every bond involving ``pid``."""
    pid = str(pid) if pid is not None else None
    if not pid:
        return
    bonds = _bond_list(battle)
    battle['alliances'] = [
        bond for bond in bonds
        if len(bond) >= 2 and str(bond[0]) != pid and str(bond[1]) != pid
    ]


def merge_alliances(target_battle, source_battle):
    """Fold source battle bonds into the target battle."""
    for bond in list(source_battle.get('alliances') or []):
        if len(bond) >= 2:
            add_bond(target_battle, bond[0], bond[1])


def participants_can_stop_fighting(battle):
    """True when surviving players form at most one alliance component.

    - 0 or 1 participants → True (classic end condition).
    - 2+ participants → True only if every participant is in the same
      connected component (i.e. all mutually allied, possibly transitively).
    """
    participants = list(battle.get('participants') or [])
    if len(participants) <= 1:
        return True
    groups = [frozenset(alliance_group(battle, pid)) for pid in participants]
    # Every participant must be in the same group, and that group must
    # cover every participant.
    first = groups[0]
    if len(first) != len(participants):
        return False
    return all(g == first for g in groups)


def killer_in_alliance(battle, killer_id):
    """True if the killer has at least one living ally in this battle."""
    group = alliance_group(battle, killer_id)
    return len(group) > 1


class EqualSplitRewardPolicy:
    """Pool the allied survivors' pending buckets and split evenly.

    Remainder XP/PQG goes to the lowest player ids for determinism.
    ``grants_elo`` is False — allied survivors receive no Elo.
    """

    grants_elo = False

    def split(self, buckets: dict) -> dict:
        """
        ``buckets``: {player_id: {kills, xp, pqg, elo_opponents}}
        Returns the same shape with evenly split xp/pqg. kills is kept
        per-player (informational); elo_opponents is cleared.
        """
        if not buckets:
            return {}
        player_ids = sorted(str(pid) for pid in buckets.keys())
        n = len(player_ids)
        total_xp = sum(int(b.get('xp', 0) or 0) for b in buckets.values())
        total_pqg = sum(int(b.get('pqg', 0) or 0) for b in buckets.values())
        total_kills = sum(int(b.get('kills', 0) or 0) for b in buckets.values())

        base_xp, rem_xp = divmod(total_xp, n)
        base_pqg, rem_pqg = divmod(total_pqg, n)

        out = {}
        for i, pid in enumerate(player_ids):
            original = buckets.get(pid) or buckets.get(str(pid)) or {}
            out[pid] = {
                'kills': int(original.get('kills', 0) or 0),
                'xp': base_xp + (1 if i < rem_xp else 0),
                'pqg': base_pqg + (1 if i < rem_pqg else 0),
                'elo_opponents': [],
                # Shared kill total for messaging; kept as total across alliance.
                'alliance_kills': total_kills,
            }
        return out


REWARD_POLICY = EqualSplitRewardPolicy()

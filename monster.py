"""Generic monster instance — species data lives in monster_types."""

import uuid

from character_stats import ATTRIBUTE_KEYS, attributes_for_inspect
from monster_types import get_monster_type
from abilities.registry import get_ability

# Module-level AI defaults (used when a type omits a value)
DEFAULT_AGGRESSION = 0
DEFAULT_SPEED = 10
DEFAULT_ACTIVENESS = 5
DEFAULT_SIGHT_RANGE = 20

# 8-direction deltas: (dy, dx) — N, NE, E, SE, S, SW, W, NW
EIGHT_DIRECTIONS = (
    (-1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, -1),
)


def _clamp_stat(value, lo=0.0, hi=10.0):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


class Monster:
    """Individual monster instance. Species-specific data comes from MonsterTypeDef."""

    def __init__(self, monster_id, type_id, position, level=None, rng=None, **runtime_overrides):
        type_def = get_monster_type(type_id)
        if type_def is None:
            raise ValueError(f'Unknown monster type_id: {type_id!r}')

        self.id = monster_id if monster_id is not None else f'{type_def.id}-{uuid.uuid4().hex[:8]}'
        self.type_id = type_def.id
        self.name = type_def.name
        # Combat / legacy callers use .type as the display name
        self.type = type_def.name
        self.pos = list(position)

        lvl = type_def.base_level if level is None else max(1, int(level))
        self.level = lvl
        attrs, mhp, bonuses, hp_bonus = type_def.stats_for_level(lvl, rng=rng)
        for key in ATTRIBUTE_KEYS:
            setattr(self, key, attrs[key])
        self.level_bonuses = dict(bonuses)
        self.level_hp_bonus = int(hp_bonus)
        self.mhp = mhp
        self.hp = mhp
        # Combat rating; dungeon spawn calibrates via monster_elo.calibrate_instance_elo.
        # Keep in sync with monster_elo.INITIAL_ELO (avoid circular import here).
        self.elo = 3000

        self.ability_ids = list(type_def.ability_ids)
        # Damage divisor in combat_damage; species default from type sheet (min 1).
        self.armour = int(runtime_overrides.pop('armour', type_def.armour))
        if self.armour < 1:
            self.armour = 1
        self.in_combat = False

        aggression = runtime_overrides.pop('aggression', type_def.aggression)
        speed = runtime_overrides.pop('speed', type_def.speed)
        activeness = runtime_overrides.pop('activeness', type_def.activeness)
        sight_range = runtime_overrides.pop('sight_range', type_def.sight_range)
        if runtime_overrides:
            unknown = ', '.join(sorted(runtime_overrides))
            raise TypeError(f'Unexpected Monster keyword arguments: {unknown}')

        self.aggression = _clamp_stat(aggression)
        self.speed = _clamp_stat(speed)
        self.activeness = _clamp_stat(activeness)
        self.sight_range = max(0, int(round(float(sight_range))))

        # Player memory (last seen player on this level; live position, no timer)
        self.memory_player_id = None
        self.memory_pos = None  # [y, x]

        # Debug snapshot (last opportunity)
        self.last_intention = None
        self.last_chosen_dest = None
        self.last_fail_reason = None
        self.last_target_visible = False

    @classmethod
    def from_type(cls, type_id, position, monster_id=None, level=None, rng=None, **runtime_overrides):
        """Create a monster from a registered species id."""
        return cls(
            monster_id,
            type_id,
            position,
            level=level,
            rng=rng,
            **runtime_overrides,
        )

    def clear_memory(self):
        self.memory_player_id = None
        self.memory_pos = None

    def move(self, direction):
        """Return proposed position for a cardinal wasd key (player-compatible)."""
        new_pos = self.pos.copy()
        if direction == 'w':
            new_pos[0] -= 1
        elif direction == 's':
            new_pos[0] += 1
        elif direction == 'a':
            new_pos[1] -= 1
        elif direction == 'd':
            new_pos[1] += 1
        return new_pos

    def sprite_url(self):
        type_def = get_monster_type(self.type_id)
        return type_def.sprite if type_def else None

    def portrait_url(self):
        type_def = get_monster_type(self.type_id)
        return type_def.portrait if type_def else None

    def to_inspect_dict(self):
        """Player-facing inspect payload (no internal/AI fields)."""
        type_def = get_monster_type(self.type_id)
        description = type_def.description if type_def else None
        abilities = []
        for aid in self.ability_ids:
            ability = get_ability(aid)
            if ability is not None:
                abilities.append({'id': ability.id, 'name': ability.name})
            else:
                abilities.append({'id': str(aid), 'name': str(aid)})
        elo_value = round(float(getattr(self, 'elo', 3000)), 1)
        try:
            from monster_elo import elo_percentile
            percentile = elo_percentile(elo_value)
        except Exception:
            percentile = None
        try:
            strength = int(getattr(self, 'str', 1) or 1)
        except (TypeError, ValueError):
            strength = 1
        from combat_damage import DEFAULT_WEAPON_BASE_DAMAGE
        mean_damage = int(DEFAULT_WEAPON_BASE_DAMAGE) + strength
        return {
            'kind': 'monster',
            'name': self.name,
            'type_id': self.type_id,
            'description': description,
            'level': self.level,
            'elo': elo_value,
            'elo_percentile': percentile,
            'hp': self.hp,
            'mhp': self.mhp,
            'armour': int(getattr(self, 'armour', 1) or 1),
            'mean_damage': mean_damage,
            'attributes': attributes_for_inspect(self),
            'abilities': abilities,
            'sprite': self.sprite_url(),
            'portrait': self.portrait_url(),
        }

    def to_dict(self):
        return {
            'id': self.id,
            'type_id': self.type_id,
            'type': self.type,
            'name': self.name,
            'level': self.level,
            'elo': round(float(getattr(self, 'elo', 3000)), 1),
            'hp': self.hp,
            'mhp': self.mhp,
            'pos': self.pos,
            'aggression': self.aggression,
            'speed': self.speed,
            'activeness': self.activeness,
            'sight_range': self.sight_range,
            'str': self.str,
            'int': self.int,
            'wis': self.wis,
            'chr': self.chr,
            'dex': self.dex,
            'agi': self.agi,
            'acc': self.acc,
            'ability_ids': list(self.ability_ids),
        }

    def receive_attack(self, damage):
        self.hp -= damage
        return self.hp <= 0

    def __str__(self):
        return (
            f"Monster: {self.name} ({self.type_id}), HP: {self.hp}/{self.mhp}, "
            f"Str: {self.str}, Armour: {self.armour}, Position: {self.pos}, "
            f"Agg: {self.aggression}, Spd: {self.speed}"
        )

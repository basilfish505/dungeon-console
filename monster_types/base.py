"""Monster species definition and level-based attribute scaling."""

from character_stats import attrs_from_mapping
from monster_types.leveling import (
    DEFAULT_LEVEL_SCALING,
    DEFAULT_MAX_LEVEL,
    generate_leveled_stats,
)

# Sheet value for the weapon column meaning "fights bare-handed even when
# carrying a weapon" (blank keeps the legacy loot-based behaviour).
UNARMED_WEAPON_CHOICE = 'unarmed'


def apply_level(base_attributes, base_mhp, level, level_scaling=None, rng=None):
    """
    Apply level bonuses to a copy of base attributes.

    Returns (attrs_dict, mhp). Species base data is never mutated.
    """
    scaling = DEFAULT_LEVEL_SCALING if level_scaling is None else level_scaling
    # Minimal stand-in so generate_leveled_stats can read fields uniformly.
    type_stub = type('TypeStub', (), {
        'base_attributes': attrs_from_mapping(base_attributes),
        'base_mhp': base_mhp,
        'level_scaling': scaling,
        'max_level': DEFAULT_MAX_LEVEL,
        'name': 'Monster',
        'id': 'monster',
    })()
    attrs, mhp, _bonuses, _hp_bonus = generate_leveled_stats(type_stub, level, rng=rng)
    return attrs, mhp


class MonsterTypeDef:
    """Reusable species data — not an instance."""

    def __init__(
        self,
        type_id,
        name,
        base_level=1,
        base_attributes=None,
        base_mhp=10,
        ability_ids=None,
        spell_ids=None,
        loot_ids=None,
        loot_chance=None,
        base_mmp=0,
        description=None,
        sprite=None,
        portrait=None,
        aggression=0,
        speed=10,
        activeness=5,
        sight_range=20,
        armour=1,
        spawn_weight=1,
        level_scaling=None,
        max_level=None,
        weapon_id=None,
    ):
        self.id = str(type_id)
        self.name = str(name)
        # None = legacy (wield the first carried weapon), UNARMED_WEAPON_CHOICE
        # = always bare hands, otherwise a weapon_types id wielded regardless of loot.
        weapon = str(weapon_id).strip() if weapon_id else ''
        if weapon.lower() == UNARMED_WEAPON_CHOICE:
            weapon = UNARMED_WEAPON_CHOICE
        self.weapon_id = weapon or None
        self.base_level = max(1, int(base_level))
        self.base_attributes = attrs_from_mapping(base_attributes)
        self.base_mhp = max(1, int(base_mhp))
        self.ability_ids = list(ability_ids) if ability_ids else []
        self.spell_ids = list(spell_ids) if spell_ids else []
        self.loot_ids = list(loot_ids) if loot_ids else []
        # Percent 0-100 that a spawn carries loot; None = use the game default.
        try:
            self.loot_chance = (
                None if loot_chance is None
                else max(0.0, min(100.0, float(loot_chance)))
            )
        except (TypeError, ValueError):
            self.loot_chance = None
        try:
            self.base_mmp = max(0, int(base_mmp))
        except (TypeError, ValueError):
            self.base_mmp = 0
        self.description = description if description else None
        # Art paths under static/monsters/ (sprites = map, portraits = combat)
        tid = self.id
        self.sprite = sprite or f'/static/monsters/sprites/{tid}.png'
        self.portrait = portrait or f'/static/monsters/portraits/{tid}.png'
        # Data-only defaults for existing AI/combat compatibility
        self.aggression = aggression
        self.speed = speed
        self.activeness = activeness
        self.sight_range = sight_range
        try:
            self.armour = int(armour)
        except (TypeError, ValueError):
            self.armour = 1
        if self.armour < 1:
            self.armour = 1
        try:
            self.spawn_weight = float(spawn_weight)
        except (TypeError, ValueError):
            self.spawn_weight = 1.0
        if self.spawn_weight < 0:
            self.spawn_weight = 0.0

        if level_scaling is None:
            self.level_scaling = DEFAULT_LEVEL_SCALING
        else:
            try:
                self.level_scaling = int(level_scaling)
            except (TypeError, ValueError):
                self.level_scaling = DEFAULT_LEVEL_SCALING
        if self.level_scaling < 0:
            self.level_scaling = 0

        if max_level is None:
            self.max_level = DEFAULT_MAX_LEVEL
        else:
            try:
                self.max_level = int(max_level)
            except (TypeError, ValueError):
                self.max_level = DEFAULT_MAX_LEVEL
        if self.max_level < 1:
            self.max_level = 1

    def stats_for_level(self, level=None, rng=None):
        """Return (attributes_dict, mhp, bonuses_dict, hp_bonus) for the given level."""
        lvl = self.base_level if level is None else max(1, int(level))
        return generate_leveled_stats(self, lvl, rng=rng)

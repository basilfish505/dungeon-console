"""Monster species definition and level stub (no scaling curve yet)."""

from character_stats import attrs_from_mapping


def apply_level(base_attributes, base_mhp, level):
    """
    Placeholder for future level-based scaling.
    Currently returns copies of the base values unchanged.
    """
    attrs = attrs_from_mapping(base_attributes)
    try:
        mhp = int(base_mhp)
    except (TypeError, ValueError):
        mhp = 1
    mhp = max(1, mhp)
    # level reserved for future curves
    _ = level
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
        description=None,
        sprite=None,
        portrait=None,
        aggression=0,
        speed=10,
        activeness=5,
        sight_range=20,
        attack_power=5,
        spawn_weight=1,
    ):
        self.id = str(type_id)
        self.name = str(name)
        self.base_level = max(1, int(base_level))
        self.base_attributes = attrs_from_mapping(base_attributes)
        self.base_mhp = max(1, int(base_mhp))
        self.ability_ids = list(ability_ids) if ability_ids else []
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
        self.attack_power = attack_power
        try:
            self.spawn_weight = float(spawn_weight)
        except (TypeError, ValueError):
            self.spawn_weight = 1.0
        if self.spawn_weight < 0:
            self.spawn_weight = 0.0

    def stats_for_level(self, level=None):
        """Return (attributes_dict, mhp) for the given level."""
        lvl = self.base_level if level is None else max(1, int(level))
        return apply_level(self.base_attributes, self.base_mhp, lvl)

"""Troll species definition — basic monster, no special abilities."""

from monster_types.base import MonsterTypeDef
from monster_types.registry import register_monster_type

TROLL = MonsterTypeDef(
    type_id='troll',
    name='Troll',
    base_level=1,
    description='A large, brutish creature that relies on strength and durability.',
    base_attributes={
        'str': 8,
        'int': 3,
        'wis': 3,
        'chr': 2,
        'dex': 4,
        'agi': 4,
    },
    base_mhp=16,
    ability_ids=[],
    # Match prior global AI defaults so behavior stays familiar
    aggression=0,
    speed=10,
    activeness=5,
    sight_range=20,
    attack_power=5,
)

register_monster_type(TROLL)

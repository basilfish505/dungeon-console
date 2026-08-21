"""Shopkeeper species — not a random spawn. Bump to fight; very high damage."""

from monster_types.base import MonsterTypeDef
from monster_types.registry import register_monster_type

SHOPKEEPER = MonsterTypeDef(
    type_id='shopkeeper',
    name='Shopkeeper',
    base_level=10,
    description='The Items Shop proprietor. Friendly behind the desk; lethal if you jump him.',
    base_attributes={
        'str': 20,
        'int': 12,
        'wis': 12,
        'chr': 14,
        'dex': 10,
        'agi': 10,
    },
    base_mhp=400,
    ability_ids=[],
    aggression=10,
    speed=10,
    activeness=10,
    sight_range=8,
    attack_power=300,
    spawn_weight=0,
    sprite='/static/npcs/shopkeeper.png',
    portrait='/static/npcs/shopkeeper.png',
)

register_monster_type(SHOPKEEPER)

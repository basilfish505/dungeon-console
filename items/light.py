"""Dungeon light sources (candle / torch): light, extinguish, burn ticks."""

from __future__ import annotations

from item_types.registry import get_item_type

LIGHT_TYPE_IDS = frozenset({'candle', 'torch'})


def is_light_source(type_id):
    return str(type_id or '') in LIGHT_TYPE_IDS


def light_ticks_for(type_def):
    if type_def is None:
        return None
    ticks = getattr(type_def, 'light_ticks', None)
    if ticks is None:
        return None
    try:
        return max(0, int(ticks))
    except (TypeError, ValueError):
        return None


def light_sight_for(type_def):
    if type_def is None:
        return None
    sight = getattr(type_def, 'light_sight', None)
    if sight is None:
        return None
    try:
        return float(sight)
    except (TypeError, ValueError):
        return None


def seed_light_extras(inst, type_def=None):
    """Ensure a light instance has light_remaining fuel seeded."""
    if inst is None:
        return
    type_def = type_def or get_item_type(inst.type_id)
    ticks = light_ticks_for(type_def)
    if ticks is None:
        return
    if 'light_remaining' not in inst.extras:
        inst.extras['light_remaining'] = ticks
    inst.extras.setdefault('lit', False)


def get_light_remaining(inst):
    if inst is None:
        return 0
    try:
        return max(0, int(inst.extras.get('light_remaining', 0)))
    except (TypeError, ValueError):
        return 0


def is_instance_lit(inst):
    return bool(inst and inst.extras.get('lit'))


def extinguish_all_lights(player):
    inv = getattr(player, 'inventory', None)
    if inv is None:
        return
    for item in inv:
        if is_light_source(item.type_id):
            item.extras['lit'] = False
    player.lit_light_instance_id = None


def sync_light_sight(player):
    """Set player.sight_range from the currently lit light, else 0."""
    if player is None:
        return
    lit_id = getattr(player, 'lit_light_instance_id', None)
    inv = getattr(player, 'inventory', None)
    if not lit_id or inv is None:
        player.sight_range = 0
        player.lit_light_instance_id = None
        return
    inst = inv.get(lit_id)
    if inst is None or not is_light_source(inst.type_id) or not is_instance_lit(inst):
        player.sight_range = 0
        player.lit_light_instance_id = None
        return
    type_def = get_item_type(inst.type_id)
    sight = light_sight_for(type_def)
    player.sight_range = sight if sight is not None else 0.0


def light_item(player, instance_id, game_state=None):
    """
    Light a candle/torch in the dungeon.

    Returns result dict compatible with use_item.
    """
    result = {
        'ok': False,
        'message': 'Cannot light that.',
        'consumed': False,
        'effects': {},
    }
    if player is None or getattr(player, 'inventory', None) is None:
        return result
    if getattr(player, 'interior_id', None):
        result['message'] = 'There is already enough light here.'
        return result
    if getattr(player, 'dungeon_level', 0) <= 0:
        result['message'] = 'You only need a light in the dungeon.'
        return result

    inst = player.inventory.get(instance_id)
    if inst is None:
        result['message'] = 'You do not have that item.'
        return result
    if not is_light_source(inst.type_id):
        result['message'] = 'That is not a light source.'
        return result

    type_def = get_item_type(inst.type_id)
    if type_def is None or light_sight_for(type_def) is None:
        result['message'] = 'That item is unknown.'
        return result

    seed_light_extras(inst, type_def)
    remaining = get_light_remaining(inst)
    if remaining <= 0:
        result['message'] = f'The {type_def.name} is spent.'
        return result

    if is_instance_lit(inst) and getattr(player, 'lit_light_instance_id', None) == inst.instance_id:
        result['ok'] = True
        result['message'] = f'The {type_def.name} is already lit.'
        return result

    extinguish_all_lights(player)
    inst.extras['lit'] = True
    player.lit_light_instance_id = inst.instance_id
    sync_light_sight(player)

    if game_state is not None and hasattr(game_state, 'recompute_visibility'):
        game_state.recompute_visibility(player)

    result['ok'] = True
    result['effects'] = {
        'lit': True,
        'light_sight': player.sight_range,
        'light_remaining': remaining,
    }
    result['message'] = f'You light the {type_def.name}.'
    return result


def tick_player_light(player, game_state=None):
    """
    Burn one tick of the lit light after a turn-consuming action.

    Returns True if inventory/sight changed (extinguished or fuel updated).
    """
    if player is None or getattr(player, 'inventory', None) is None:
        return False
    lit_id = getattr(player, 'lit_light_instance_id', None)
    if not lit_id:
        return False

    inst = player.inventory.get(lit_id)
    if inst is None or not is_light_source(inst.type_id) or not is_instance_lit(inst):
        player.lit_light_instance_id = None
        player.sight_range = 0
        if game_state is not None and hasattr(game_state, 'recompute_visibility'):
            game_state.recompute_visibility(player)
        return True

    remaining = get_light_remaining(inst) - 1
    inst.extras['light_remaining'] = max(0, remaining)
    if remaining > 0:
        return True

    name = inst.type_id
    type_def = get_item_type(inst.type_id)
    if type_def is not None:
        name = type_def.name or name
    player.inventory.remove(lit_id)
    player.lit_light_instance_id = None
    player.sight_range = 0
    if game_state is not None and hasattr(game_state, 'recompute_visibility'):
        game_state.recompute_visibility(player)
    if game_state is not None and hasattr(game_state, 'add_player_message'):
        game_state.add_player_message(
            player.id, f'Your {name} burns out.'
        )
    return True


def clear_lit_if_removed(player, instance_id):
    if player is None or not instance_id:
        return
    if getattr(player, 'lit_light_instance_id', None) == instance_id:
        player.lit_light_instance_id = None
        player.sight_range = 0

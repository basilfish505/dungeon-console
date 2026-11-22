"""Inn outdoor footprint, interior, and overnight stay logic."""

from __future__ import annotations

import uuid

from interiors.shop_common import SHOPKEEPER_SPRITE, build_shop_interior, stamp_shop

INN_ID = 'inn'
INN_PRICE_PQG = 5
GREETING = (
    "Welcome, traveler. A room is 5 PQG for the night. "
    "Stay here and you'll wake with your HP and MP fully restored."
)
SORRY_MESSAGE = 'Sorry, traveler. A room costs 5 PQG.'
WAKE_MESSAGE = 'You wake feeling rested. Your HP and MP are fully restored.'
STAY_ACTIONS = (
    {'id': 'stay', 'label': 'Stay — 5 PQG'},
    {'id': 'leave', 'label': 'Leave'},
)


def build_inn(facing='s'):
    return build_shop_interior(
        facing,
        shop_id=INN_ID,
        npc_id='innkeeper',
        npc_name='Innkeeper',
        greeting=GREETING,
        sprite=SHOPKEEPER_SPRITE,
    )


def stamp_inn(game_map, rng=None):
    return stamp_shop(game_map, rng=rng, shop_id=INN_ID)


def open_stay_offer(game_state, player_id):
    """Create a one-shot stay offer for this player and return its id."""
    if not hasattr(game_state, 'inn_offers') or game_state.inn_offers is None:
        game_state.inn_offers = {}
    offer_id = uuid.uuid4().hex
    game_state.inn_offers[player_id] = offer_id
    return offer_id


def stay_at_inn(game_state, player, offer_id):
    """
    Charge for one overnight stay and restore HP/MP.

    Returns dict: {ok, message, charged}.
    """
    result = {'ok': False, 'message': None, 'charged': False}
    if player is None:
        return result
    if getattr(player, 'interior_id', None) != INN_ID:
        return result
    if getattr(player, 'in_combat', False):
        return result

    offers = getattr(game_state, 'inn_offers', None) or {}
    player_id = getattr(player, 'id', None)
    stored = offers.get(player_id) if player_id is not None else None
    if not offer_id or stored is None or str(offer_id) != str(stored):
        return result

    purse = int(getattr(player, 'pqg', 0) or 0)
    if purse < INN_PRICE_PQG:
        result['message'] = SORRY_MESSAGE
        return result

    # Consume the offer before mutating stats so a second tap cannot charge again.
    offers.pop(player_id, None)

    player.pqg = purse - INN_PRICE_PQG
    mhp = max(1, int(getattr(player, 'mhp', 1) or 1))
    mmp = max(0, int(getattr(player, 'mmp', 0) or 0))
    player.hp = mhp
    player.mp = mmp

    result['ok'] = True
    result['charged'] = True
    result['message'] = WAKE_MESSAGE
    return result

"""Pending loot offers: a defeated monster's item waits for keep / discard.

When a monster that carried something is defeated, the item is not dropped
straight into the pack. The player gets an *offer* (stored on
``player.pending_loot`` and saved with the character, so a reload or reconnect
cannot lose it) and answers keep or discard.

An offer is a dict: ``offer_id``, ``type_id``, ``boosts``, ``monster_name``.
"""

from __future__ import annotations

import uuid

from armour_types.traits import clean_rolled_boosts
from items.catalog import resolve_loot_type
from items.service import add_item_to_inventory
from monster_loot import describe_loot

MAX_PENDING_OFFERS = 50


def pending_offers(player):
    """The player's live offer list (created on first use)."""
    offers = getattr(player, 'pending_loot', None)
    if not isinstance(offers, list):
        offers = []
        player.pending_loot = offers
    return offers


def clean_offer(raw):
    """Sanitise one saved/received offer -> dict, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    resolved = resolve_loot_type(raw.get('type_id'))
    if resolved is None:
        return None
    _category, loot_def = resolved
    offer_id = str(raw.get('offer_id') or '').strip() or uuid.uuid4().hex[:12]
    return {
        'offer_id': offer_id,
        'type_id': loot_def.id,
        'boosts': clean_rolled_boosts(raw.get('boosts')),
        'monster_name': str(raw.get('monster_name') or 'monster'),
    }


def clean_offers(raw):
    """Sanitise a saved offer list (drops unknown items and duplicates)."""
    out = []
    seen = set()
    for item in raw if isinstance(raw, list) else []:
        offer = clean_offer(item)
        if offer is None or offer['offer_id'] in seen:
            continue
        seen.add(offer['offer_id'])
        out.append(offer)
    return out[:MAX_PENDING_OFFERS]


def add_offer(player, entry):
    """Queue a dropped item for the player. Returns the offer, or None if unusable.

    ``entry`` is what a monster drops: ``{'type_id', 'boosts', 'monster_name'}``.
    """
    offer = clean_offer({**(entry or {}), 'offer_id': None})
    if offer is None:
        return None
    offers = pending_offers(player)
    offers.append(offer)
    del offers[:-MAX_PENDING_OFFERS]
    return offer


def offer_label(offer):
    resolved = resolve_loot_type(offer.get('type_id'))
    if resolved is None:
        return str(offer.get('type_id'))
    return describe_loot(resolved[1], offer.get('boosts'))


def offers_for_client(player):
    """Client rows for the keep/discard prompt."""
    rows = []
    for offer in pending_offers(player):
        resolved = resolve_loot_type(offer.get('type_id'))
        if resolved is None:
            continue
        category, loot_def = resolved
        rows.append({
            'offer_id': offer['offer_id'],
            'type_id': loot_def.id,
            'category': category,
            'name': loot_def.name or loot_def.id,
            'label': describe_loot(loot_def, offer.get('boosts')),
            'image': getattr(loot_def, 'image', None),
            'boosts': dict(offer.get('boosts') or {}),
            'monster_name': offer.get('monster_name') or 'monster',
        })
    return rows


def resolve_offer(player, offer_id, keep):
    """Apply the player's choice. Returns ``{ok, message, kept, full}``.

    Keep with a full pack leaves the offer pending (``ok`` False, ``full``
    True) so the player can still discard it. Unknown ids are rejected, which
    also makes a double-click harmless.
    """
    result = {'ok': False, 'message': 'That item is no longer on offer.', 'kept': False, 'full': False}
    if player is None:
        return result
    offers = pending_offers(player)
    wanted = str(offer_id or '').strip()
    offer = next((o for o in offers if o.get('offer_id') == wanted), None)
    if offer is None:
        return result
    resolved = resolve_loot_type(offer.get('type_id'))
    if resolved is None:
        offers.remove(offer)
        result['message'] = 'That item is gone.'
        return result
    category, loot_def = resolved
    label = describe_loot(loot_def, offer.get('boosts'))

    if not keep:
        offers.remove(offer)
        result.update(ok=True, message=f'You leave the {label} behind.')
        return result

    inst = add_item_to_inventory(player, loot_def.id, quantity=1, category=category)
    if inst is None:
        result.update(
            message=f'Your pack is full, so you cannot keep the {label}.',
            full=True,
        )
        return result
    # Keep the exact boost the monster was wearing instead of a fresh roll.
    boosts = clean_rolled_boosts(offer.get('boosts'))
    if boosts:
        inst.extras['boosts'] = boosts
    offers.remove(offer)
    result.update(ok=True, kept=True, message=f'You pick up the {label}.')
    return result

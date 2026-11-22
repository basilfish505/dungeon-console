"""Treasure chests on dungeon floors.

Each chest generated with a floor is a *slot*. A slot holds what is inside
(one to three items and maybe some PQG, all rolled when the chest spawns and
then fixed), whether the chest is currently on the map, and when it may
respawn. Slots are saved with their level, so reconnecting or restoring the
world shows the same remaining contents.

Respawning is cooldown based and counted in that floor's own monster rounds
(``LevelTurnState.completed_round``), so a round on another floor never moves
a chest's clock. When the last reward is taken the chest leaves the map and
its slot waits ``CHEST_RESPAWN_FIRST_CHECK_ROUNDS`` rounds; each check then
succeeds with ``CHEST_RESPAWN_CHANCE`` and otherwise (or if no tile is free)
tries again ``CHEST_RESPAWN_RETRY_ROUNDS`` rounds later. The chest comes back
on a random valid tile, not necessarily where it stood before.

Everything tunable lives in the constants below and is read at call time, so
tests can patch them.
"""

from __future__ import annotations

import random
import uuid

from armour_types.registry import ARMOUR_TYPES
from armour_types.traits import boosted_name, clean_rolled_boosts, roll_boosts
from item_types.registry import ITEM_TYPES
from items.catalog import (
    CATEGORY_ARMOUR,
    CATEGORY_ITEM,
    CATEGORY_WEAPON,
    resolve_owned_type,
)
from items.service import add_item_to_inventory
from level_turns import get_level_turn_state
from spawn_placement import hidden_far_tiles
from weapon_types.registry import WEAPON_TYPES

CHEST_GLYPH = '$'
FLOOR = '.'
MONSTER_GLYPH = '&'

# Chance that each eligible floor tile gets a chest when a floor is generated.
CHEST_PROBABILITY = 0.05
# Chance a chest's item comes from the items sheet (the rest: weapons + armour).
CHEST_ITEM_SHEET_WEIGHT = 0.60
# A chest always holds one item; these are the odds it also holds a second
# (30% of chests) and a third (10% of chests, which is a subset of those).
CHEST_SECOND_ITEM_CHANCE = 0.30
CHEST_THIRD_ITEM_CHANCE = 0.10
CHEST_GOLD_CHANCE = 0.30
CHEST_GOLD_MIN = 1
CHEST_GOLD_MAX = 200
# Floor rounds after a chest is emptied before its first respawn check.
CHEST_RESPAWN_FIRST_CHECK_ROUNDS = 50
CHEST_RESPAWN_CHANCE = 0.30
# Floor rounds until the next check after a failed roll or blocked placement.
CHEST_RESPAWN_RETRY_ROUNDS = 20

REWARD_ITEM = 'item'
REWARD_PQG = 'pqg'


# ---------------------------------------------------------------- contents

def _gear_pool():
    pool = [(CATEGORY_WEAPON, type_id) for type_id in sorted(WEAPON_TYPES)]
    pool.extend((CATEGORY_ARMOUR, type_id) for type_id in sorted(ARMOUR_TYPES))
    return pool


def roll_chest_item(rng=None):
    """One random item for a chest, or None if no sheet has anything.

    ``CHEST_ITEM_SHEET_WEIGHT`` of the time it is an item-sheet entry; otherwise
    a weapon or armour (pooled together). Within a group every entry is equally
    likely. Rings roll their attribute boost now, so it is fixed in the chest.
    """
    source = rng if rng is not None else random
    items = sorted(ITEM_TYPES)
    gear = _gear_pool()
    if items and (not gear or source.random() < CHEST_ITEM_SHEET_WEIGHT):
        category, type_id = CATEGORY_ITEM, source.choice(items)
    elif gear:
        category, type_id = source.choice(gear)
    else:
        return None
    boosts = {}
    if category == CATEGORY_ARMOUR:
        boosts = roll_boosts(
            getattr(ARMOUR_TYPES.get(type_id), 'attribute_boosts', None), rng=source,
        )
    return {
        'uid': uuid.uuid4().hex[:8],
        'type_id': type_id,
        'category': category,
        'boosts': boosts,
    }


def roll_chest_item_count(rng=None):
    """How many items a chest holds: 1, 2 or 3.

    One roll decides, so ``CHEST_SECOND_ITEM_CHANCE`` and
    ``CHEST_THIRD_ITEM_CHANCE`` are the share of chests holding at least two
    and at least three items.
    """
    source = rng if rng is not None else random
    roll = source.random()
    if roll < CHEST_THIRD_ITEM_CHANCE:
        return 3
    if roll < CHEST_SECOND_ITEM_CHANCE:
        return 2
    return 1


def roll_chest_items(rng=None):
    """The items in a chest. Each one is rolled on its own, so repeats happen."""
    source = rng if rng is not None else random
    items = []
    for _ in range(roll_chest_item_count(source)):
        item = roll_chest_item(source)
        if item is None:
            break
        items.append(item)
    return items


def roll_chest_pqg(rng=None):
    """PQG in the chest: a CHEST_GOLD_CHANCE roll, then 1..200 inclusive (else 0)."""
    source = rng if rng is not None else random
    if source.random() >= CHEST_GOLD_CHANCE:
        return 0
    return source.randint(CHEST_GOLD_MIN, CHEST_GOLD_MAX)


def roll_chest_contents(rng=None):
    """Fresh ``(items, pqg)`` for a chest that is about to appear."""
    return roll_chest_items(rng), roll_chest_pqg(rng)


# ------------------------------------------------------------------- slots

def new_slot(y, x, rng=None):
    """A brand-new active chest slot with freshly rolled contents."""
    items, pqg = roll_chest_contents(rng)
    return {
        'slot_id': uuid.uuid4().hex[:12],
        'y': int(y),
        'x': int(x),
        'items': items,
        'pqg': int(pqg),
        'active': True,
        'next_check_round': None,
        # Bumped on every respawn so ledger keys stay unique across recycles.
        'claim_seq': 0,
    }


def spawn_chests_for_level(game_map, rng=None):
    """Roll an independent chance on every eligible tile of a new floor.

    Only plain floor qualifies, which already excludes stairs, boulders,
    monsters and other chests. Stamps the chest glyph and returns the slots.
    """
    source = rng if rng is not None else random
    slots = []
    for y, row in enumerate(game_map):
        for x, cell in enumerate(row):
            if cell == FLOOR and source.random() < CHEST_PROBABILITY:
                slots.append(new_slot(y, x, source))
                game_map[y][x] = CHEST_GLYPH
    return slots


def level_slots(game_state, level_number):
    """The chest slots of a level (empty list if it has none)."""
    chests = getattr(game_state, 'level_chests', None)
    if chests is None:
        chests = {}
        game_state.level_chests = chests
    return chests.setdefault(level_number, [])


def active_slot_at(game_state, level_number, y, x):
    for slot in level_slots(game_state, level_number):
        if slot['active'] and slot['y'] == y and slot['x'] == x:
            return slot
    return None


def slot_for_player(game_state, player):
    """The active chest slot under a player, or None."""
    if player is None or getattr(player, 'interior_id', None):
        return None
    level = int(getattr(player, 'dungeon_level', 0) or 0)
    if level <= 0:
        return None
    return active_slot_at(game_state, level, int(player.pos[0]), int(player.pos[1]))


# ------------------------------------------------------------- description

def _article(word):
    return 'an' if word[:1].lower() in 'aeiou' else 'a'


def item_label(item):
    """'Ring of Strength +4' for a chest item entry."""
    resolved = resolve_owned_type(item.get('category'), item.get('type_id'))
    if resolved is None:
        return str(item.get('type_id'))
    return boosted_name(resolved.name or resolved.id, item.get('boosts'))


def _join(parts):
    """'a', 'a and b', 'a, b and c'."""
    if len(parts) <= 2:
        return ' and '.join(parts)
    return ', '.join(parts[:-1]) + ' and ' + parts[-1]


def found_message(slot):
    """'You found a Scroll of Town Recall and 87 PQG.' for what is still inside."""
    parts = []
    for item in slot.get('items') or []:
        label = item_label(item)
        parts.append(f'{_article(label)} {label}')
    if slot.get('pqg', 0) > 0:
        parts.append(f"{slot['pqg']} PQG")
    if not parts:
        return 'The chest is empty.'
    return 'You found ' + _join(parts) + '.'


def chest_view(game_state, player):
    """Client payload for the chest a player is standing on, or None."""
    slot = slot_for_player(game_state, player)
    if slot is None:
        return None
    items = []
    for item in slot.get('items') or []:
        resolved = resolve_owned_type(item['category'], item['type_id'])
        items.append({
            'uid': item['uid'],
            'type_id': item['type_id'],
            'category': item['category'],
            'label': item_label(item),
            'name': getattr(resolved, 'name', None) or item['type_id'],
            'image': getattr(resolved, 'image', None),
        })
    return {
        'slot_id': slot['slot_id'],
        'items': items,
        'pqg': int(slot.get('pqg', 0)),
        'text': found_message(slot),
    }


# ----------------------------------------------------------------- claiming

def _vacate(game_state, level_number, slot):
    """Take a fully looted chest off the map and start its respawn clock."""
    game_map, monsters = game_state.ensure_level(level_number)
    y, x = slot['y'], slot['x']
    if game_map[y][x] == CHEST_GLYPH:
        game_map[y][x] = MONSTER_GLYPH if (y, x) in monsters else FLOOR
    completed = get_level_turn_state(game_state, level_number).completed_round
    slot['active'] = False
    slot['items'] = []
    slot['pqg'] = 0
    slot['next_check_round'] = completed + CHEST_RESPAWN_FIRST_CHECK_ROUNDS


def claim_from_chest(game_state, player, slot_id, what, item_id=None):
    """Take one item or the PQG from the chest the player is standing on.

    A chest can hold several items, so ``item_id`` says which one (the chest's
    item ``uid``). Contents are shared and each reward can only be claimed
    once. This runs without yielding, so two players acting "at the same time"
    are handled one after the other and the second one finds the reward gone.

    Returns ``{ok, message, what, item_id, full, emptied}``.
    """
    result = {'ok': False, 'message': 'There is no chest here.', 'what': what,
              'item_id': item_id, 'full': False, 'emptied': False}
    if player is None or getattr(player, 'in_combat', False):
        if player is not None:
            result['message'] = 'You cannot loot a chest during battle.'
        return result
    slot = slot_for_player(game_state, player)
    if slot is None or slot['slot_id'] != str(slot_id or ''):
        return result
    level = int(player.dungeon_level)

    if what == REWARD_ITEM:
        wanted = str(item_id or '')
        item = next(
            (i for i in slot.get('items') or [] if not wanted or i['uid'] == wanted),
            None,
        )
        if item is None:
            result['message'] = 'That is already gone.'
            return result
        label = item_label(item)
        inst = add_item_to_inventory(
            player, item['type_id'], quantity=1, category=item['category'],
        )
        if inst is None:
            result.update(
                message=f'Your pack is full, so the {label} stays in the chest.',
                full=True,
            )
            return result
        boosts = clean_rolled_boosts(item.get('boosts'))
        if boosts:
            inst.extras['boosts'] = boosts
        slot['items'] = [i for i in slot['items'] if i['uid'] != item['uid']]
        result.update(ok=True, item_id=item['uid'], message=f'You take the {label}.')
    elif what == REWARD_PQG:
        amount = int(slot.get('pqg', 0) or 0)
        if amount <= 0:
            result['message'] = 'That is already gone.'
            return result
        credited = _credit_chest_pqg(game_state, player, slot, amount, level)
        if not credited.get('ok'):
            result['message'] = credited.get('message') or 'Could not claim PQG.'
            return result
        # Clear the slot even on already_applied so crash-replay cannot re-offer.
        slot['pqg'] = 0
        result.update(ok=True, message=f'You take {amount} PQG.')
    else:
        result['message'] = 'Take the item or the PQG.'
        return result

    if not slot['items'] and slot['pqg'] <= 0:
        _vacate(game_state, level, slot)
        result['emptied'] = True
    game_state.mark_level_dirty(level)
    return result


def _credit_chest_pqg(game_state, player, slot, amount, level):
    """Credit chest PQG through the durable ledger when a store is available."""
    from pqg_economy import (
        SOURCE_LOOT_CHEST,
        attach_account_to_player,
        chest_idempotency_key,
        credit,
    )

    wp = getattr(game_state, 'world_persistence', None)
    store = getattr(wp, 'store', None) if wp is not None else None
    if store is None:
        player.pqg = int(getattr(player, 'pqg', 0) or 0) + int(amount)
        return {'ok': True}

    account_id = attach_account_to_player(store, player, starting_grant=False)
    world_id = getattr(wp, 'world_id', None) or getattr(game_state, 'world_id', None)
    claim_seq = int(slot.get('claim_seq', 0) or 0)
    key = chest_idempotency_key(
        world_id, level, slot.get('slot_id'), claim_seq, what='pqg',
    )
    return credit(
        store,
        account_id,
        amount,
        source=SOURCE_LOOT_CHEST,
        idempotency_key=key,
        source_instance_id=str(slot.get('slot_id') or ''),
        world_id=world_id,
        character_id=getattr(player, 'id', None),
        dungeon_level=level,
        chest_slot_id=str(slot.get('slot_id') or ''),
        metadata={'claim_seq': claim_seq},
        player=player,
    )


# ---------------------------------------------------------------- respawning

def maybe_respawn_chests(game_state, level_number, rng=None, current_round=None):
    """Check every vacant chest slot of a floor that is due. True if one appeared.

    Call once per monster round on that floor. ``current_round`` is the round
    being run; by default it is the floor's completed rounds plus one.
    """
    if level_number is None or level_number <= 0:
        return False
    slots = level_slots(game_state, level_number)
    if not slots:
        return False
    source = rng if rng is not None else random
    if current_round is None:
        current_round = get_level_turn_state(game_state, level_number).completed_round + 1

    due = [
        s for s in slots
        if not s['active'] and current_round >= int(s.get('next_check_round') or 0)
    ]
    if not due:
        return False

    game_map, _monsters = game_state.ensure_level(level_number)
    candidates = None
    appeared = False
    for slot in due:
        if source.random() >= CHEST_RESPAWN_CHANCE:
            slot['next_check_round'] = current_round + CHEST_RESPAWN_RETRY_ROUNDS
            continue
        if candidates is None:
            players = list(game_state.players_on_level(level_number).values())
            candidates = hidden_far_tiles(game_map, players, {FLOOR})
        if not candidates:
            slot['next_check_round'] = current_round + CHEST_RESPAWN_RETRY_ROUNDS
            continue
        y, x = source.choice(candidates)  # any valid tile, not the old one
        candidates = [t for t in candidates if t != (y, x)]
        items, pqg = roll_chest_contents(source)
        next_seq = int(slot.get('claim_seq', 0) or 0) + 1
        slot.update(
            y=y, x=x, items=items, pqg=int(pqg), active=True,
            next_check_round=None, claim_seq=next_seq,
        )
        game_map[y][x] = CHEST_GLYPH
        appeared = True

    game_state.mark_level_dirty(level_number)  # retry times changed even if none appeared
    return appeared


# --------------------------------------------------------------- persistence

def _clean_item(raw):
    if not isinstance(raw, dict):
        return None
    category = str(raw.get('category') or CATEGORY_ITEM)
    resolved = resolve_owned_type(category, raw.get('type_id'))
    if resolved is None:
        return None
    return {
        'uid': str(raw.get('uid') or '').strip() or uuid.uuid4().hex[:8],
        'type_id': resolved.id,
        'category': category,
        'boosts': clean_rolled_boosts(raw.get('boosts')),
    }


def _clean_items(raw):
    items = []
    seen = set()
    for entry in raw if isinstance(raw, list) else []:
        item = _clean_item(entry)
        if item is None or item['uid'] in seen:
            continue
        seen.add(item['uid'])
        items.append(item)
    return items


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clean_slots(raw):
    """Sanitise saved chest slots; drops malformed ones and unknown items."""
    out = []
    seen = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        slot_id = str(entry.get('slot_id') or '').strip() or uuid.uuid4().hex[:12]
        if slot_id in seen:
            continue
        seen.add(slot_id)
        y, x = _int(entry.get('y')), _int(entry.get('x'))
        out.append({
            'slot_id': slot_id,
            'y': y,
            'x': x,
            'items': _clean_items(entry.get('items')),
            'pqg': max(0, _int(entry.get('pqg'))),
            'active': bool(entry.get('active')),
            'next_check_round': (
                None if entry.get('next_check_round') is None
                else _int(entry.get('next_check_round'))
            ),
            'claim_seq': max(0, _int(entry.get('claim_seq'))),
        })
    return out


def slots_to_list(slots):
    """Plain, JSON-ready copy of a level's chest slots."""
    return [dict(slot, items=[dict(item) for item in slot.get('items') or []])
            for slot in slots or []]


def restore_slots(game_map, raw):
    """Rebuild a level's slots from a save and re-stamp their map glyphs."""
    slots = clean_slots(raw)
    h = len(game_map)
    w = len(game_map[0]) if h else 0
    for slot in slots:
        if not slot['active']:
            continue
        if 0 <= slot['y'] < h and 0 <= slot['x'] < w:
            game_map[slot['y']][slot['x']] = CHEST_GLYPH
        else:
            slot['active'] = False
            slot['items'] = []
            slot['pqg'] = 0
            slot['next_check_round'] = 0
    # A chest with nothing in it is not a chest.
    for slot in slots:
        if slot['active'] and not slot['items'] and slot['pqg'] <= 0:
            slot['active'] = False
            slot['next_check_round'] = 0
            if game_map[slot['y']][slot['x']] == CHEST_GLYPH:
                game_map[slot['y']][slot['x']] = FLOOR
    return slots

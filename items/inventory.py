"""Player inventory — 16 slots of ItemInstance (None = empty)."""

from __future__ import annotations

from items.catalog import (
    CATEGORY_ARMOUR,
    CATEGORY_ITEM,
    CATEGORY_WEAPON,
    normalize_category,
    resolve_owned_type,
)
from items.instance import ItemInstance

PLACEHOLDER_BY_CATEGORY = {
    CATEGORY_ITEM: '/static/items/sprites/placeholder.png',
    CATEGORY_WEAPON: '/static/weapons/sprites/placeholder.png',
    CATEGORY_ARMOUR: '/static/armour/sprites/placeholder.png',
}
SLOT_COUNT = 16


def _row_from_item(item, equipped_ids=None, lit_light_id=None):
    equipped_ids = equipped_ids or set()
    cat = normalize_category(getattr(item, 'category', CATEGORY_ITEM))
    type_def = resolve_owned_type(cat, item.type_id)
    equipped = item.instance_id in equipped_ids
    lit = bool(lit_light_id and item.instance_id == lit_light_id and item.extras.get('lit'))
    if type_def is None:
        row = {
            'instance_id': item.instance_id,
            'type_id': item.type_id,
            'quantity': item.quantity,
            'category': cat,
            'name': item.type_id,
            'description': None,
            'price_pqg': 0,
            'image': PLACEHOLDER_BY_CATEGORY.get(cat, PLACEHOLDER_BY_CATEGORY[CATEGORY_ITEM]),
            'equipped': equipped,
            'lit': lit,
        }
        return row
    row = {
        'instance_id': item.instance_id,
        'type_id': item.type_id,
        'quantity': item.quantity,
        'category': cat,
        'name': type_def.name,
        'description': type_def.description,
        'price_pqg': type_def.price_pqg,
        'image': type_def.image,
        'equipped': equipped,
        'lit': lit,
    }
    if cat == CATEGORY_WEAPON:
        row['base_damage'] = getattr(type_def, 'base_damage', -2)
        row['consistency_factor'] = getattr(type_def, 'consistency_factor', 3)
    elif cat == CATEGORY_ARMOUR:
        row['armour_value'] = getattr(type_def, 'armour_value', 1)
    light_ticks = getattr(type_def, 'light_ticks', None)
    if light_ticks is not None:
        row['light_ticks'] = int(light_ticks)
        try:
            remaining = int(item.extras.get('light_remaining', light_ticks))
        except (TypeError, ValueError):
            remaining = int(light_ticks)
        row['light_remaining'] = max(0, remaining)
        if getattr(type_def, 'light_sight', None) is not None:
            row['light_sight'] = type_def.light_sight
    return row


class Inventory:
    def __init__(self):
        self._slots = [None] * SLOT_COUNT

    def __len__(self):
        return sum(1 for item in self._slots if item is not None)

    def __iter__(self):
        return (item for item in self._slots if item is not None)

    def get(self, instance_id):
        for item in self._slots:
            if item is not None and item.instance_id == instance_id:
                return item
        return None

    def add(self, type_id, quantity=1, category=CATEGORY_ITEM, instance_id=None):
        """
        Place a new instance in the first empty slot.

        Stacking is intentionally not implemented yet — each add creates a new
        instance so later stacking/equipment rules can be layered on cleanly.
        """
        empty = self._first_empty()
        if empty is None:
            raise ValueError('Inventory is full')
        cat = normalize_category(category)
        type_def = resolve_owned_type(cat, type_id)
        if type_def is None:
            raise ValueError(f'Unknown {cat} type_id: {type_id!r}')
        try:
            qty = max(1, int(quantity))
        except (TypeError, ValueError):
            qty = 1
        inst = ItemInstance(
            type_id=type_def.id,
            quantity=qty,
            category=cat,
            instance_id=instance_id,
        )
        if cat == CATEGORY_ITEM:
            from items.light import seed_light_extras
            seed_light_extras(inst, type_def)
        self._slots[empty] = inst
        return inst

    def remove(self, instance_id, quantity=None):
        """
        Clear the slot holding instance_id (does not compact remaining items).

        For now quantity is ignored and the whole instance is removed.
        Returns the removed ItemInstance or None.
        """
        for i, item in enumerate(self._slots):
            if item is not None and item.instance_id == instance_id:
                self._slots[i] = None
                return item
        return None

    def move(self, from_slot, to_slot):
        """Swap/move the contents of two slots. Returns True if applied."""
        try:
            src = int(from_slot)
            dst = int(to_slot)
        except (TypeError, ValueError):
            return False
        if src == dst:
            return True
        if not (0 <= src < SLOT_COUNT and 0 <= dst < SLOT_COUNT):
            return False
        if self._slots[src] is None:
            return False
        self._slots[src], self._slots[dst] = self._slots[dst], self._slots[src]
        return True

    def _first_empty(self):
        for i, item in enumerate(self._slots):
            if item is None:
                return i
        return None

    def to_client_list(
        self,
        equipped_weapon_id=None,
        equipped_armour_id=None,
        lit_light_id=None,
    ):
        """16 entries for the UI; empty slots are None."""
        equipped_ids = set()
        if equipped_weapon_id:
            equipped_ids.add(equipped_weapon_id)
        if equipped_armour_id:
            equipped_ids.add(equipped_armour_id)
        rows = []
        for item in self._slots:
            rows.append(
                None
                if item is None
                else _row_from_item(
                    item, equipped_ids, lit_light_id=lit_light_id
                )
            )
        return rows

    def to_save_list(self):
        return [item.to_dict() for item in self._slots if item is not None]

    def load_from_save(self, rows):
        self._slots = [None] * SLOT_COUNT
        if not rows:
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            type_id = row.get('type_id')
            if not type_id:
                continue
            cat = normalize_category(row.get('category', CATEGORY_ITEM))
            if resolve_owned_type(cat, type_id) is None:
                continue
            try:
                self.add(
                    type_id,
                    quantity=row.get('quantity', 1),
                    category=cat,
                    instance_id=row.get('instance_id'),
                )
                inst = self.get(row.get('instance_id'))
                if inst is not None and isinstance(row.get('extras'), dict):
                    inst.extras.update(row['extras'])
            except ValueError:
                break

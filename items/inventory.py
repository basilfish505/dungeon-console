"""Player inventory — 16 slots of ItemInstance (None = empty)."""

from __future__ import annotations

from items.instance import ItemInstance
from item_types.registry import get_item_type

PLACEHOLDER_IMAGE = '/static/items/sprites/placeholder.png'
SLOT_COUNT = 16


def _row_from_item(item):
    type_def = get_item_type(item.type_id)
    if type_def is None:
        return {
            'instance_id': item.instance_id,
            'type_id': item.type_id,
            'quantity': item.quantity,
            'name': item.type_id,
            'description': None,
            'price_pqg': 0,
            'image': PLACEHOLDER_IMAGE,
        }
    return {
        'instance_id': item.instance_id,
        'type_id': item.type_id,
        'quantity': item.quantity,
        'name': type_def.name,
        'description': type_def.description,
        'price_pqg': type_def.price_pqg,
        'image': type_def.image,
    }


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

    def add(self, type_id, quantity=1):
        """
        Place a new instance in the first empty slot.

        Stacking is intentionally not implemented yet — each add creates a new
        instance so later stacking/equipment rules can be layered on cleanly.
        """
        empty = self._first_empty()
        if empty is None:
            raise ValueError('Inventory is full')
        type_def = get_item_type(type_id)
        if type_def is None:
            raise ValueError(f'Unknown item type_id: {type_id!r}')
        try:
            qty = max(1, int(quantity))
        except (TypeError, ValueError):
            qty = 1
        inst = ItemInstance(type_id=type_def.id, quantity=qty)
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

    def to_client_list(self):
        """16 entries for the UI; empty slots are None."""
        rows = []
        for item in self._slots:
            rows.append(None if item is None else _row_from_item(item))
        return rows

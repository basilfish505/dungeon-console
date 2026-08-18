"""Player inventory — ordered list of ItemInstance."""

from __future__ import annotations

from items.instance import ItemInstance
from item_types.registry import get_item_type

PLACEHOLDER_IMAGE = '/static/items/sprites/placeholder.png'
SLOT_COUNT = 16


class Inventory:
    def __init__(self):
        self._items = []  # list[ItemInstance]

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def get(self, instance_id):
        for item in self._items:
            if item.instance_id == instance_id:
                return item
        return None

    def add(self, type_id, quantity=1):
        """
        Append a new instance for type_id.

        Stacking is intentionally not implemented yet — each add creates a new
        instance so later stacking/equipment rules can be layered on cleanly.
        """
        if len(self._items) >= SLOT_COUNT:
            raise ValueError('Inventory is full')
        type_def = get_item_type(type_id)
        if type_def is None:
            raise ValueError(f'Unknown item type_id: {type_id!r}')
        try:
            qty = max(1, int(quantity))
        except (TypeError, ValueError):
            qty = 1
        inst = ItemInstance(type_id=type_def.id, quantity=qty)
        self._items.append(inst)
        return inst

    def remove(self, instance_id, quantity=None):
        """
        Remove an instance (or reduce quantity later).

        For now quantity is ignored and the whole instance is removed.
        Returns the removed ItemInstance or None.
        """
        for i, item in enumerate(self._items):
            if item.instance_id == instance_id:
                return self._items.pop(i)
        return None

    def to_client_list(self):
        """Enriched list for UI: ownership + resolved definition fields."""
        rows = []
        for item in self._items:
            type_def = get_item_type(item.type_id)
            if type_def is None:
                rows.append({
                    'instance_id': item.instance_id,
                    'type_id': item.type_id,
                    'quantity': item.quantity,
                    'name': item.type_id,
                    'description': None,
                    'price_pqg': 0,
                    'image': PLACEHOLDER_IMAGE,
                })
                continue
            rows.append({
                'instance_id': item.instance_id,
                'type_id': item.type_id,
                'quantity': item.quantity,
                'name': type_def.name,
                'description': type_def.description,
                'price_pqg': type_def.price_pqg,
                'image': type_def.image,
            })
        return rows

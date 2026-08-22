"""Owned inventory instance — item, weapon, or armour."""

from __future__ import annotations

import uuid

from items.catalog import CATEGORY_ITEM, normalize_category


class ItemInstance:
    """
    One stack/instance in a player's inventory.

    extras is reserved for future per-instance fields (durability, charges, etc.).
    """

    __slots__ = ('instance_id', 'type_id', 'quantity', 'category', 'extras')

    def __init__(
        self,
        type_id,
        quantity=1,
        instance_id=None,
        category=CATEGORY_ITEM,
        extras=None,
    ):
        self.instance_id = instance_id or uuid.uuid4().hex
        self.type_id = str(type_id)
        self.category = normalize_category(category)
        try:
            self.quantity = max(1, int(quantity))
        except (TypeError, ValueError):
            self.quantity = 1
        self.extras = dict(extras) if extras else {}

    def to_dict(self):
        """Ownership-only serialization (no definition copy)."""
        data = {
            'instance_id': self.instance_id,
            'type_id': self.type_id,
            'quantity': self.quantity,
            'category': self.category,
        }
        if self.extras:
            data['extras'] = dict(self.extras)
        return data

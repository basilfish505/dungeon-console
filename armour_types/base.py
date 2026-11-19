"""Armour type definition — static library data (not an owned instance)."""

from armour_types.traits import parse_other_ability

SLOT_BODY = 'body'
SLOT_RING = 'ring'
SLOTS = (SLOT_BODY, SLOT_RING)


def normalize_slot(value):
    """'ring' -> ring slot; anything else (blank, typo) -> body armour."""
    slot = str(value or '').strip().lower()
    return slot if slot in SLOTS else SLOT_BODY


class ArmourTypeDef:
    """Reusable armour definition identified by stable armour_id."""

    def __init__(
        self,
        armour_id,
        name=None,
        description=None,
        price_pqg=0,
        image=None,
        armour_value=1,
        slot=None,
        other_ability=None,
    ):
        self.id = str(armour_id)
        self.name = str(name) if name else self.id
        self.description = description if description else None
        try:
            self.price_pqg = max(0, int(price_pqg))
        except (TypeError, ValueError):
            self.price_pqg = 0
        try:
            self.armour_value = max(1, int(armour_value))
        except (TypeError, ValueError):
            self.armour_value = 1
        self.slot = normalize_slot(slot)
        text = str(other_ability).strip() if other_ability is not None else ''
        self.other_ability = text or None
        self.attribute_boosts, self.unrecognised_abilities = parse_other_ability(text)
        tid = self.id
        if image and str(image).strip():
            img = str(image).strip()
            if '/' not in img and not img.startswith('http'):
                img = f'/static/armour/sprites/{img}'
            self.image = img
        else:
            self.image = f'/static/armour/sprites/{tid}.png'

    @property
    def is_ring(self):
        return self.slot == SLOT_RING

    def to_client_dict(self):
        return {
            'item_id': self.id,
            'type_id': self.id,
            'category': 'armour',
            'name': self.name,
            'description': self.description,
            'price_pqg': self.price_pqg,
            'image': self.image,
            'armour_value': self.armour_value,
            'slot': self.slot,
            'other_ability': self.other_ability,
            'boost_ranges': [b.to_dict() for b in self.attribute_boosts],
        }

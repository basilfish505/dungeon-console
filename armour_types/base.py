"""Armour type definition — static library data (not an owned instance)."""


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
        tid = self.id
        if image and str(image).strip():
            img = str(image).strip()
            if '/' not in img and not img.startswith('http'):
                img = f'/static/armour/sprites/{img}'
            self.image = img
        else:
            self.image = f'/static/armour/sprites/{tid}.png'

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
        }

"""Weapon type definition — static library data (not an owned instance)."""


class WeaponTypeDef:
    """Reusable weapon definition identified by stable weapon_id."""

    def __init__(
        self,
        weapon_id,
        name=None,
        description=None,
        price_pqg=0,
        image=None,
        base_damage=-2,
        consistency_factor=3,
    ):
        self.id = str(weapon_id)
        self.name = str(name) if name else self.id
        self.description = description if description else None
        try:
            self.price_pqg = max(0, int(price_pqg))
        except (TypeError, ValueError):
            self.price_pqg = 0
        try:
            self.base_damage = int(base_damage)
        except (TypeError, ValueError):
            self.base_damage = -2
        try:
            self.consistency_factor = float(consistency_factor)
        except (TypeError, ValueError):
            self.consistency_factor = 3.0
        if self.consistency_factor <= 0:
            self.consistency_factor = 3.0
        tid = self.id
        if image and str(image).strip():
            img = str(image).strip()
            if '/' not in img and not img.startswith('http'):
                img = f'/static/weapons/sprites/{img}'
            self.image = img
        else:
            self.image = f'/static/weapons/sprites/{tid}.png'

    def to_client_dict(self):
        return {
            'item_id': self.id,
            'type_id': self.id,
            'category': 'weapon',
            'name': self.name,
            'description': self.description,
            'price_pqg': self.price_pqg,
            'image': self.image,
            'base_damage': self.base_damage,
            'consistency_factor': self.consistency_factor,
        }

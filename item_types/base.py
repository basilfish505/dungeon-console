"""Item type definition — static library data (not an owned instance)."""


class ItemTypeDef:
    """Reusable item definition identified by stable item_id."""

    def __init__(
        self,
        item_id,
        name=None,
        description=None,
        price_pqg=0,
        image=None,
    ):
        self.id = str(item_id)
        self.name = str(name) if name else self.id
        self.description = description if description else None
        try:
            self.price_pqg = max(0, int(price_pqg))
        except (TypeError, ValueError):
            self.price_pqg = 0
        tid = self.id
        if image and str(image).strip():
            img = str(image).strip()
            if '/' not in img and not img.startswith('http'):
                img = f'/static/items/sprites/{img}'
            self.image = img
        else:
            self.image = f'/static/items/sprites/{tid}.png'

    def to_client_dict(self):
        return {
            'item_id': self.id,
            'name': self.name,
            'description': self.description,
            'price_pqg': self.price_pqg,
            'image': self.image,
        }

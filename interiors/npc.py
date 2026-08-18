"""Non-combat NPCs (shopkeepers, later innkeepers, etc.)."""

from items.service import shop_starter_wares


class Npc:
    def __init__(
        self,
        npc_id,
        name,
        pos,
        greeting,
        sprite,
        shop_id=None,
    ):
        self.id = npc_id
        self.name = name
        self.pos = list(pos)
        self.greeting = greeting
        self.sprite = sprite
        self.shop_id = shop_id

    def wares(self):
        if self.shop_id:
            return shop_starter_wares()
        return []

    def to_inspect_result(self):
        wares = self.wares()
        kind = 'shop' if wares else 'npc'
        return {
            'ok': True,
            'kind': kind,
            'data': {
                'kind': kind,
                'name': self.name,
                'greeting': self.greeting,
                'description': self.greeting,
                'portrait': self.sprite,
                'wares': wares,
            },
        }

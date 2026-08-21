"""Non-combat NPCs until bumped into (shopkeepers can fight)."""

from items.service import shop_starter_wares
from monster import Monster


class Npc:
    def __init__(
        self,
        npc_id,
        name,
        pos,
        greeting,
        sprite,
        shop_id=None,
        combat_type_id=None,
    ):
        self.id = npc_id
        self.name = name
        self.pos = list(pos)
        self.greeting = greeting
        self.sprite = sprite
        self.shop_id = shop_id
        self.combat_type_id = combat_type_id
        self._combatant = None

    def wares(self):
        if self.shop_id:
            return shop_starter_wares()
        return []

    def as_combatant(self):
        """Monster instance used if the player attacks this NPC."""
        if not self.combat_type_id:
            return None
        if self._combatant is None:
            self._combatant = Monster.from_type(
                self.combat_type_id,
                self.pos,
                monster_id=self.id,
            )
        self._combatant.pos = list(self.pos)
        return self._combatant

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

import random

from character_stats import attributes_for_inspect
from items.equipment import (
    effective_armour_value,
    equipped_weapon_name,
    equipped_weapon_stats,
    mean_damage_for,
)
from items.inventory import Inventory
from player_growth import (
    apply_pending_growth,
    capture_new_player_baseline,
)
from player_leveling import (
    level_from_total_xp,
    xp_progress,
    xp_required_to_reach_level,
)


def _spells_for_client(player):
    from spell_casting import spells_for_client
    context = 'combat' if getattr(player, 'in_combat', False) else 'exploration'
    return spells_for_client(player, context=context)

# Compass steps (dy, dx). Legacy WASD: w=n, a=west, s=s, d=e.
# Token "w" stays north so cached clients do not strafe west on W.
MOVE_DELTAS = {
    'n': (-1, 0),
    'ne': (-1, 1),
    'e': (0, 1),
    'se': (1, 1),
    's': (1, 0),
    'sw': (1, -1),
    'west': (0, -1),
    'nw': (-1, -1),
    'w': (-1, 0),
    'a': (0, -1),
    'd': (0, 1),
}

# Surface / top level always uses this FOV; dungeon floors use Player.sight_range.
TOP_LEVEL_SIGHT_RANGE = 30
INTERIOR_SIGHT_RANGE = 8
STARTING_MAX_MP = 8


class Player:
    def __init__(self, player_id, position):
        self.id = player_id
        self.pos = position
        self.dungeon_level = 0  # 0 is top level
        self.interior_id = None  # None = outdoors; e.g. 'items_shop'
        self.level = 1
        self.total_xp = 0
        self.elo = 1000
        self.pqg = 10
        # HP/MP properties
        self.mhp = random.randint(300, 500)
        self.hp = self.mhp
        self.mmp = STARTING_MAX_MP
        self.mp = self.mmp
        # Stats
        self.str = random.randint(1, 10)
        self.int = random.randint(1, 10)
        self.wis = random.randint(1, 10)
        self.chr = random.randint(1, 10)
        self.dex = random.randint(1, 10)
        self.agi = random.randint(1, 10)
        self.acc = random.randint(1, 10)
        # Damage divisor in combat_damage; 1 = no reduction until gear exists.
        self.armour = 1
        self.in_combat = False
        # Vision / fog-of-war (dungeon floors only; town and interiors are fully lit)
        self.sight_range = 0
        self.explored = {}  # dungeon_level -> set of (y, x)
        self.visible = set()  # current LOS tiles (y, x)
        self.appearance_id = 'peasant'
        self.inventory = Inventory()
        self.equipped_weapon_instance_id = None
        self.equipped_armour_instance_id = None
        self.lit_light_instance_id = None
        self.known_spells = []
        from items.service import grant_starting_inventory
        from spell_casting import grant_starting_spells
        grant_starting_inventory(self)
        grant_starting_spells(self)
        capture_new_player_baseline(self)

    def explored_key(self):
        """Fog memory key: dungeon level int, or ('interior', id)."""
        if self.interior_id:
            return ('interior', self.interior_id)
        return self.dungeon_level

    def effective_sight_range(self):
        """FOV radius for the player's current floor."""
        if self.interior_id:
            return INTERIOR_SIGHT_RANGE
        if self.dungeon_level <= 0:
            return TOP_LEVEL_SIGHT_RANGE
        try:
            return max(0.0, float(self.sight_range))
        except (TypeError, ValueError):
            return 0.0

    def sprite_url(self):
        return '/static/player/sprites/player_walk1.png'

    def level_up(self, rng=None):
        """Increase level by 1 and apply one independent growth event."""
        self.level += 1
        results = apply_pending_growth(self, rng=rng)
        self.last_level_up_results = results
        return results

    def sync_level_from_xp(self, rng=None):
        """Reconcile stored level with total_xp (total_xp is source of truth)."""
        self.level = level_from_total_xp(self.total_xp)
        results = apply_pending_growth(self, rng=rng)
        if results:
            self.last_level_up_results = results
        return results

    def award_xp(self, amount, rng=None):
        """Add lifetime XP, process level-ups, return count of levels gained."""
        try:
            gain = int(amount)
        except (TypeError, ValueError):
            gain = 0
        if gain <= 0:
            self.last_level_up_results = []
            return 0

        self.total_xp += gain
        levels_gained = 0
        all_results = []
        while self.total_xp >= xp_required_to_reach_level(self.level + 1):
            all_results.extend(self.level_up(rng=rng))
            levels_gained += 1
        self.last_level_up_results = all_results
        return levels_gained

    def xp_progress_dict(self):
        """UI-ready progress snapshot toward the next level."""
        return xp_progress(self.total_xp, self.level)

    def to_inspect_dict(self):
        """Player-facing inspect payload (combat stats; no inventory dump)."""
        weapon_base, _consistency = equipped_weapon_stats(self)
        try:
            strength = int(getattr(self, 'str', 1) or 1)
        except (TypeError, ValueError):
            strength = 1
        return {
            'kind': 'player',
            'name': self.id,
            'id': self.id,
            'level': self.level,
            'elo': round(float(getattr(self, 'elo', 1000)), 1),
            'pqg': int(getattr(self, 'pqg', 0) or 0),
            'hp': int(self.hp),
            'mhp': int(self.mhp),
            'mp': int(self.mp),
            'mmp': int(self.mmp),
            'attributes': attributes_for_inspect(self),
            'armour': int(effective_armour_value(self)),
            'weapon_name': equipped_weapon_name(self),
            'weapon_base_damage': int(weapon_base),
            'strength': strength,
            'mean_damage': int(mean_damage_for(self)),
            'sprite': self.sprite_url(),
            'portrait': self.sprite_url(),
        }

    def to_dict(self):
        return {
            'id': self.id,
            'level': self.level,
            'total_xp': self.total_xp,
            'xp': self.total_xp,
            'xp_progress': self.xp_progress_dict(),
            'elo': round(float(getattr(self, 'elo', 1000)), 1),
            'pqg': int(getattr(self, 'pqg', 0)),
            'hp': f"{self.hp}/{self.mhp}",
            'mp': f"{self.mp}/{self.mmp}",
            'str': self.str,
            'int': self.int,
            'wis': self.wis,
            'chr': self.chr,
            'dex': self.dex,
            'agi': self.agi,
            'acc': self.acc,
            'sight_range': self.sight_range,
            'pos': list(self.pos),
            'dungeon_level': self.dungeon_level,
            'interior_id': self.interior_id,
            'appearance_id': self.appearance_id,
            'sprite': self.sprite_url(),
            'armour': int(getattr(self, 'armour', 1) or 1),
            'equipped_weapon_instance_id': getattr(
                self, 'equipped_weapon_instance_id', None
            ),
            'equipped_armour_instance_id': getattr(
                self, 'equipped_armour_instance_id', None
            ),
            'inventory': self.inventory.to_client_list(
                equipped_weapon_id=getattr(self, 'equipped_weapon_instance_id', None),
                equipped_armour_id=getattr(self, 'equipped_armour_instance_id', None),
                lit_light_id=getattr(self, 'lit_light_instance_id', None),
            ),
            'spells': _spells_for_client(self),
        }

    def move(self, direction):
        new_pos = self.pos.copy()
        delta = MOVE_DELTAS.get(direction)
        if delta is None:
            return new_pos
        new_pos[0] += delta[0]
        new_pos[1] += delta[1]
        return new_pos

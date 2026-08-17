import random

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


class Player:
    def __init__(self, player_id, position):
        self.id = player_id
        self.pos = position
        self.dungeon_level = 0  # 0 is top level
        self.level = 1
        self.xp = 0
        # HP/MP properties
        self.mhp = random.randint(10, 20)
        self.hp = self.mhp
        self.mmp = 0
        self.mp = 0
        # Stats
        self.str = random.randint(1, 10)
        self.int = random.randint(1, 10)
        self.wis = random.randint(1, 10)
        self.chr = random.randint(1, 10)
        self.dex = random.randint(1, 10)
        self.agi = random.randint(1, 10)
        self.in_combat = False
        # Vision / fog-of-war (dungeon floors only; top level uses TOP_LEVEL_SIGHT_RANGE)
        self.sight_range = 8
        self.explored = {}  # dungeon_level -> set of (y, x)
        self.visible = set()  # current LOS tiles (y, x)
        self.appearance_id = 'peasant'

    def effective_sight_range(self):
        """FOV radius for the player's current floor."""
        if self.dungeon_level <= 0:
            return TOP_LEVEL_SIGHT_RANGE
        return max(0, int(self.sight_range))

    def sprite_url(self):
        return '/static/player/sprites/player_walk1.png'

    def to_dict(self):
        return {
            'id': self.id,
            'level': self.level,
            'xp': self.xp,
            'hp': f"{self.hp}/{self.mhp}",
            'mp': f"{self.mp}/{self.mmp}",
            'str': self.str,
            'int': self.int,
            'wis': self.wis,
            'chr': self.chr,
            'dex': self.dex,
            'agi': self.agi,
            'sight_range': self.sight_range,
            'pos': list(self.pos),
            'dungeon_level': self.dungeon_level,
            'appearance_id': self.appearance_id,
            'sprite': self.sprite_url(),
        }

    def move(self, direction):
        new_pos = self.pos.copy()
        delta = MOVE_DELTAS.get(direction)
        if delta is None:
            return new_pos
        new_pos[0] += delta[0]
        new_pos[1] += delta[1]
        return new_pos

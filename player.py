import random

class Player:
    def __init__(self, player_id, position):
        self.id = player_id
        self.pos = position
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
            'agi': self.agi
        }

    def move(self, direction):
        new_pos = self.pos.copy()
        if direction == 'w':
            new_pos[0] -= 1
        elif direction == 's':
            new_pos[0] += 1
        elif direction == 'a':
            new_pos[1] -= 1
        elif direction == 'd':
            new_pos[1] += 1
        return new_pos

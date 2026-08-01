import time

# Default spawn stats (v1 — same for all types; specialize later)
DEFAULT_AGGRESSION = 0
DEFAULT_SPEED = 10
DEFAULT_ACTIVENESS = 5
DEFAULT_SIGHT_RANGE = 20
DEFAULT_MEMORY_DURATION = 5.0

# 8-direction deltas: (dy, dx) — N, NE, E, SE, S, SW, W, NW
EIGHT_DIRECTIONS = (
    (-1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, -1),
)


def _clamp_stat(value, lo=0.0, hi=10.0):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


class Monster:
    def __init__(self, monster_id, monster_type, position,
                 aggression=DEFAULT_AGGRESSION,
                 speed=DEFAULT_SPEED,
                 activeness=DEFAULT_ACTIVENESS,
                 sight_range=DEFAULT_SIGHT_RANGE,
                 memory_duration=DEFAULT_MEMORY_DURATION):
        self.id = monster_id
        self.type = monster_type
        self.pos = list(position)
        self.hp = 10
        self.attack_power = 5
        self.in_combat = False

        self.aggression = _clamp_stat(aggression)
        self.speed = _clamp_stat(speed)
        self.activeness = _clamp_stat(activeness)
        self.sight_range = max(0, int(round(float(sight_range))))
        self.memory_duration = float(memory_duration)

        # Movement timing (monotonic clock); None means never schedule
        self.next_move_at = None
        if self.speed > 0:
            # Stagger first move slightly so spawns don't all tick together
            self.next_move_at = time.monotonic()

        # Player memory
        self.memory_player_id = None
        self.memory_pos = None  # [y, x]
        self.memory_until = None

        # Debug snapshot (last opportunity)
        self.last_intention = None
        self.last_chosen_dest = None
        self.last_fail_reason = None
        self.last_target_visible = False

    def clear_memory(self):
        self.memory_player_id = None
        self.memory_pos = None
        self.memory_until = None

    def schedule_next_move(self, interval, now=None):
        """Set next_move_at from now + interval; clear if interval is None."""
        if interval is None or self.speed <= 0:
            self.next_move_at = None
            return
        if now is None:
            now = time.monotonic()
        self.next_move_at = now + interval

    def move(self, direction):
        """Return proposed position for a cardinal wasd key (player-compatible)."""
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

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'hp': self.hp,
            'pos': self.pos,
            'attack_power': self.attack_power,
            'aggression': self.aggression,
            'speed': self.speed,
            'activeness': self.activeness,
            'sight_range': self.sight_range,
        }

    def receive_attack(self, damage):
        self.hp -= damage
        return self.hp <= 0

    def __str__(self):
        return (
            f"Monster: {self.type}, HP: {self.hp}, Attack: {self.attack_power}, "
            f"Position: {self.pos}, Agg: {self.aggression}, Spd: {self.speed}"
        )

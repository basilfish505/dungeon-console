import math
import random
from collections import deque
from monster import Monster
from monster_types.registry import get_monster_type, pick_spawn_type_id
from monster_types.leveling import assign_monster_level
from monster_elo import calibrate_instance_elo
from interiors.items_shop import ITEMS_SHOP_ID, stamp_items_shop
from interiors.weapon_shop import WEAPON_SHOP_ID, stamp_weapon_shop
from interiors.armour_shop import ARMOUR_SHOP_ID, stamp_armour_shop
from visibility import GRASS, IMPASSABLE_TERRAIN, MOUNTAIN, OPEN_GROUND, TREE

# Constants
MAP_SIZE = 20  # Viewport / simple-dungeon footprint
TOWN_MAP_SIZE = 28  # Top-level yard (three shops, road, stairs)
MONSTER_PROBABILITY = 0.03
TREE_SPAWN_RATE = 0.04
# Keep trees off these tiles and their 8-neighbors (doors, road, stairs).
TREE_CLEAR_GLYPHS = frozenset({'+', ',', '↓', '↑'})
MIN_FLOOR_AREA = 300
MAX_FLOOR_AREA = 500
MAX_GEN_ATTEMPTS = 50

# Temporary testing toggle: True = classic 20x20 rectangle with random boulders.
# False = procedural rooms/tunnels (1k–5k tiles) + scrolling camera on large maps.
USE_SIMPLE_LOWER_LEVELS = False
BOULDER_PROBABILITY = 0.03  # simple-mode only

class MapGenerator:
    def __init__(self, map_size=MAP_SIZE):
        self.map_size = map_size
        self.game_map = None
        self.monsters = {}
        self.town_features = {}

    def generate_level(self, stairs_up_pos=None):
        """Generate a lower level (simple rectangle or procedural rooms/tunnels)."""
        if USE_SIMPLE_LOWER_LEVELS:
            return self._generate_simple_level(stairs_up_pos)

        self.monsters = {}
        for _ in range(MAX_GEN_ATTEMPTS):
            game_map = self._carve_rooms_and_tunnels()
            if game_map is None:
                continue
            self.game_map = game_map
            self.monsters = {}
            self.spawn_monsters()
            if self._place_and_validate_stairs(stairs_up_pos):
                return self.game_map, self.monsters

        self.game_map = self._carve_rooms_and_tunnels() or self._fallback_dungeon()
        self.monsters = {}
        self.spawn_monsters()
        self._place_and_validate_stairs(stairs_up_pos, repair=True)
        return self.game_map, self.monsters

    def generate_top_level(self):
        """Generate the top level: open yard, items shop, road at the door, stairs down."""
        size = TOWN_MAP_SIZE
        self.game_map = [[GRASS for _ in range(size)] for _ in range(size)]
        for i in range(size):
            self.game_map[0][i] = MOUNTAIN
            self.game_map[size - 1][i] = MOUNTAIN
            self.game_map[i][0] = MOUNTAIN
            self.game_map[i][size - 1] = MOUNTAIN

        self.monsters = {}
        self.town_features = {}
        for shop_id, stamp_fn in (
            (ITEMS_SHOP_ID, stamp_items_shop),
            (WEAPON_SHOP_ID, stamp_weapon_shop),
            (ARMOUR_SHOP_ID, stamp_armour_shop),
        ):
            self.town_features[shop_id] = stamp_fn(self.game_map)
        self.place_stair('↓')
        self._plant_trees()
        return self.game_map, self.monsters

    def _tree_keep_clear(self, game_map=None):
        """Tiles that must stay open: reserved glyphs and every 8-neighbor."""
        m = game_map if game_map is not None else self.game_map
        h, w = len(m), len(m[0])
        keep_clear = set()
        for y, row in enumerate(m):
            for x, cell in enumerate(row):
                if cell not in TREE_CLEAR_GLYPHS:
                    continue
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < h and 0 <= nx < w:
                            keep_clear.add((ny, nx))
        return keep_clear

    def _plant_trees(self):
        """Scatter trees on grass; never block doors, road, or stairs."""
        m = self.game_map
        h, w = len(m), len(m[0])
        keep_clear = self._tree_keep_clear(m)
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                if m[y][x] != GRASS or (y, x) in keep_clear:
                    continue
                if random.random() < TREE_SPAWN_RATE:
                    m[y][x] = TREE

    def _generate_simple_level(self, stairs_up_pos=None):
        """Classic fixed 20x20 map: wall border, random interior boulders, stairs both ways."""
        self.game_map = [['#' for _ in range(self.map_size)] for _ in range(self.map_size)]
        self.monsters = {}
        for i in range(1, self.map_size - 1):
            for j in range(1, self.map_size - 1):
                self.game_map[i][j] = '#' if random.random() < BOULDER_PROBABILITY else '.'
        self.spawn_monsters()
        up_pos = self.place_stair('↑', preferred_pos=stairs_up_pos)
        self.place_stair('↓', avoid_pos=up_pos)
        return self.game_map, self.monsters

    # --- Rooms & tunnels -------------------------------------------------

    def _carve_rooms_and_tunnels(self):
        """Build irregular rooms linked by narrow tunnels; target floor count in range."""
        target = random.randint(MIN_FLOOR_AREA, MAX_FLOOR_AREA)

        # Bounding box large enough for scattered rooms + corridors
        side = int(math.sqrt(target) * random.uniform(2.2, 2.8)) + 10
        height = max(45, side + random.randint(-5, 15))
        width = max(45, side + random.randint(-5, 20))
        game_map = [['#' for _ in range(width)] for _ in range(height)]

        floor = set()
        rooms = []  # list of (cy, cx, floors_in_room)

        # Modest rooms so layout stays tunnels + chambers, not open cavern
        avg_room = random.randint(25, 55)
        num_rooms = max(8, min(40, target // avg_room))

        attempts = 0
        while len(rooms) < num_rooms and attempts < num_rooms * 40:
            attempts += 1
            ry = random.randint(2, 5)
            rx = random.randint(2, 6)
            cy = random.randint(ry + 2, height - ry - 3)
            cx = random.randint(rx + 2, width - rx - 3)

            # Reject heavy overlap with existing rooms
            if any(abs(cy - oy) < ry + ory + 2 and abs(cx - ox) < rx + orx + 2
                   for oy, ox, _tiles, ory, orx in rooms):
                continue

            room_tiles = self._carve_irregular_room(cy, cx, ry, rx, height, width)
            if len(room_tiles) < 8:
                continue
            floor |= room_tiles
            rooms.append((cy, cx, room_tiles, ry, rx))

        if len(rooms) < 4:
            return None

        # Connect rooms in a spanning tree, then add a few extra links / dead ends
        order = list(range(len(rooms)))
        random.shuffle(order)
        connected = {order[0]}
        while len(connected) < len(rooms):
            best = None
            best_d = None
            for i in connected:
                for j in order:
                    if j in connected:
                        continue
                    d = abs(rooms[i][0] - rooms[j][0]) + abs(rooms[i][1] - rooms[j][1])
                    if best_d is None or d < best_d:
                        best_d = d
                        best = (i, j)
            i, j = best
            self._carve_narrow_tunnel(floor, rooms[i][0], rooms[i][1],
                                     rooms[j][0], rooms[j][1], height, width)
            connected.add(j)

        # Extra branches and dead ends
        extras = max(2, len(rooms) // 3)
        for _ in range(extras):
            a, b = random.sample(range(len(rooms)), 2)
            self._carve_narrow_tunnel(floor, rooms[a][0], rooms[a][1],
                                     rooms[b][0], rooms[b][1], height, width)

        for _ in range(max(2, len(rooms) // 4)):
            r = random.choice(rooms)
            ey = random.randint(2, height - 3)
            ex = random.randint(2, width - 3)
            self._carve_narrow_tunnel(floor, r[0], r[1], ey, ex, height, width,
                                      max_steps=40)

        # Trim or grow toward target floor area without flooding open space
        floor = self._largest_component(floor)
        if len(floor) > target:
            # Prefer removing dead-end corridor tiles first is hard; randomly
            # discard leaf-like tiles until near target while keeping connectivity
            floor = self._shrink_floor(floor, target)
        elif len(floor) < MIN_FLOOR_AREA * 0.85:
            # Add a few more small rooms connected by tunnels
            while len(floor) < target * 0.9 and len(rooms) < num_rooms + 15:
                ry, rx = random.randint(2, 4), random.randint(2, 5)
                cy = random.randint(ry + 2, height - ry - 3)
                cx = random.randint(rx + 2, width - rx - 3)
                room_tiles = self._carve_irregular_room(cy, cx, ry, rx, height, width)
                if len(room_tiles) < 6:
                    continue
                # Connect to nearest existing floor
                if floor:
                    nearest = min(floor, key=lambda p: abs(p[0] - cy) + abs(p[1] - cx))
                    self._carve_narrow_tunnel(floor, cy, cx, nearest[0], nearest[1],
                                             height, width)
                floor |= room_tiles
                rooms.append((cy, cx, room_tiles, ry, rx))
            floor = self._largest_component(floor)

        if len(floor) < MIN_FLOOR_AREA * 0.5:
            return None

        for y, x in floor:
            game_map[y][x] = '.'

        # Seal map edge — no escapes
        for x in range(width):
            game_map[0][x] = '#'
            game_map[height - 1][x] = '#'
        for y in range(height):
            game_map[y][0] = '#'
            game_map[y][width - 1] = '#'

        return game_map

    def _carve_irregular_room(self, cy, cx, ry, rx, height, width):
        """Carve a jagged, asymmetrical chamber around (cy, cx)."""
        tiles = set()
        angles = 24
        radii_y = [ry * random.uniform(0.65, 1.15) for _ in range(angles)]
        radii_x = [rx * random.uniform(0.65, 1.15) for _ in range(angles)]
        for y in range(cy - ry - 2, cy + ry + 3):
            for x in range(cx - rx - 2, cx + rx + 3):
                if not (1 <= y < height - 1 and 1 <= x < width - 1):
                    continue
                dy, dx = y - cy, x - cx
                dist = math.hypot(dx / max(rx, 1), dy / max(ry, 1))
                angle = math.atan2(dy, dx)
                idx = int((angle + math.pi) / (2 * math.pi) * angles) % angles
                idx2 = (idx + 1) % angles
                t = ((angle + math.pi) / (2 * math.pi) * angles) % 1.0
                limit = (radii_y[idx] / max(ry, 1) * (1 - t) +
                         radii_y[idx2] / max(ry, 1) * t)
                # Mix x radius into limit for asymmetry
                limit_x = (radii_x[idx] / max(rx, 1) * (1 - t) +
                           radii_x[idx2] / max(rx, 1) * t)
                limit = (limit + limit_x) / 2
                if dist <= limit:
                    tiles.add((y, x))
        # Occasional bite / protrusion
        if tiles and random.random() < 0.5:
            for _ in range(random.randint(2, 6)):
                y, x = random.choice(tuple(tiles))
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    ny, nx = y + dy, x + dx
                    if 1 <= ny < height - 1 and 1 <= nx < width - 1 and random.random() < 0.5:
                        tiles.add((ny, nx))
        return tiles

    def _carve_narrow_tunnel(self, floor, y0, x0, y1, x1, height, width, max_steps=None):
        """1-tile corridor with occasional 2-tile widenings; biased drunkard toward goal."""
        y, x = y0, x0
        steps = 0
        limit = max_steps if max_steps is not None else (abs(y1 - y0) + abs(x1 - x0)) * 4 + 40
        while steps < limit:
            steps += 1
            if 1 <= y < height - 1 and 1 <= x < width - 1:
                floor.add((y, x))
                if random.random() < 0.12:
                    # Occasional wider spot
                    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                        ny, nx = y + dy, x + dx
                        if 1 <= ny < height - 1 and 1 <= nx < width - 1 and random.random() < 0.5:
                            floor.add((ny, nx))
            if (y, x) == (y1, x1):
                break
            if random.random() < 0.75:
                if abs(y1 - y) > abs(x1 - x):
                    y += 1 if y1 > y else -1
                elif x != x1:
                    x += 1 if x1 > x else -1
                else:
                    y += 1 if y1 > y else -1
            else:
                y += random.choice((-1, 0, 1))
                x += random.choice((-1, 0, 1))
            y = max(1, min(height - 2, y))
            x = max(1, min(width - 2, x))
        if 1 <= y1 < height - 1 and 1 <= x1 < width - 1:
            floor.add((y1, x1))

    def _largest_component(self, floor):
        if not floor:
            return floor
        seen = set()
        best = set()
        for start in floor:
            if start in seen:
                continue
            comp = set()
            q = deque([start])
            seen.add(start)
            while q:
                y, x = q.popleft()
                comp.add((y, x))
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    n = (y + dy, x + dx)
                    if n in floor and n not in seen:
                        seen.add(n)
                        q.append(n)
            if len(comp) > len(best):
                best = comp
        return best

    def _shrink_floor(self, floor, target):
        """Remove low-connectivity tiles until near target; preserve one component."""
        floor = set(floor)
        # Build neighbor counts
        while len(floor) > target + 50:
            candidates = []
            for y, x in floor:
                n = sum(1 for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0))
                        if (y + dy, x + dx) in floor)
                if n <= 2:
                    candidates.append((y, x))
            if not candidates:
                break
            random.shuffle(candidates)
            for tile in candidates[:max(1, len(candidates) // 4)]:
                floor.discard(tile)
                if len(floor) <= target:
                    break
        return self._largest_component(floor)

    def _fallback_dungeon(self):
        """Simple connected rooms if generation fails repeatedly."""
        h = w = 60
        game_map = [['#' for _ in range(w)] for _ in range(h)]
        floor = set()
        centers = [(15, 15), (15, 45), (45, 15), (45, 45), (30, 30)]
        for cy, cx in centers:
            for y in range(cy - 3, cy + 4):
                for x in range(cx - 4, cx + 5):
                    if 1 <= y < h - 1 and 1 <= x < w - 1:
                        floor.add((y, x))
        for i in range(1, len(centers)):
            self._carve_narrow_tunnel(floor, centers[i - 1][0], centers[i - 1][1],
                                     centers[i][0], centers[i][1], h, w)
        for y, x in floor:
            game_map[y][x] = '.'
        return game_map

    # --- Stairs & connectivity -------------------------------------------

    def _walkable_tiles(self, game_map=None):
        m = game_map if game_map is not None else self.game_map
        return [
            (y, x)
            for y, row in enumerate(m)
            for x, cell in enumerate(row)
            if cell in OPEN_GROUND or cell == '&'
        ]

    def _is_walkable_cell(self, y, x, game_map=None):
        m = game_map if game_map is not None else self.game_map
        h, w = len(m), len(m[0])
        if not (0 <= y < h and 0 <= x < w):
            return False
        return m[y][x] not in IMPASSABLE_TERRAIN

    def _nearest_walkable(self, preferred, game_map=None):
        m = game_map if game_map is not None else self.game_map
        if preferred is None:
            return None
        py, px = preferred
        if self._is_walkable_cell(py, px, m) and m[py][px] in OPEN_GROUND | {'&'}:
            return [py, px]
        best = None
        best_d = None
        for y, x in self._walkable_tiles(m):
            d = abs(y - py) + abs(x - px)
            if best_d is None or d < best_d:
                best_d = d
                best = [y, x]
        return best

    def _bfs_reachable(self, start, goal, game_map=None):
        m = game_map if game_map is not None else self.game_map
        if start is None or goal is None:
            return False
        sy, sx = start[0], start[1]
        gy, gx = goal[0], goal[1]
        if not self._is_walkable_cell(sy, sx, m) or not self._is_walkable_cell(gy, gx, m):
            return False
        q = deque([(sy, sx)])
        seen = {(sy, sx)}
        while q:
            y, x = q.popleft()
            if (y, x) == (gy, gx):
                return True
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                ny, nx = y + dy, x + dx
                if (ny, nx) not in seen and self._is_walkable_cell(ny, nx, m):
                    seen.add((ny, nx))
                    q.append((ny, nx))
        return False

    def _carve_path(self, start, end, game_map=None):
        m = game_map if game_map is not None else self.game_map
        y, x = start[0], start[1]
        ey, ex = end[0], end[1]
        while (y, x) != (ey, ex):
            if m[y][x] == '#':
                m[y][x] = '.'
            if abs(ey - y) > abs(ex - x):
                y += 1 if ey > y else -1
            elif x != ex:
                x += 1 if ex > x else -1
            else:
                y += 1 if ey > y else -1
        if m[ey][ex] == '#':
            m[ey][ex] = '.'

    def _place_and_validate_stairs(self, stairs_up_pos, repair=False):
        floors = [(y, x) for y, x in self._walkable_tiles() if self.game_map[y][x] == '.']
        if len(floors) < 2:
            return False

        for y, row in enumerate(self.game_map):
            for x, cell in enumerate(row):
                if cell in ('↑', '↓'):
                    self.game_map[y][x] = '.'

        up = self._nearest_walkable(stairs_up_pos) if stairs_up_pos else None
        if up is None:
            uy, ux = random.choice(floors)
            up = [uy, ux]
        uy, ux = up
        if (uy, ux) in self.monsters:
            del self.monsters[(uy, ux)]
        if self.game_map[uy][ux] == '#':
            return False
        self.game_map[uy][ux] = '↑'

        down_candidates = [p for p in floors if p != (uy, ux)]
        if not down_candidates:
            return False
        down_candidates.sort(key=lambda p: -(abs(p[0] - uy) + abs(p[1] - ux)))
        dy, dx = down_candidates[random.randint(0, min(25, len(down_candidates) - 1))]
        if (dy, dx) in self.monsters:
            del self.monsters[(dy, dx)]
        self.game_map[dy][dx] = '↓'

        if self._bfs_reachable(up, [dy, dx]):
            return True

        if repair:
            self._carve_path(up, [dy, dx])
            self.game_map[uy][ux] = '↑'
            self.game_map[dy][dx] = '↓'
            return self._bfs_reachable(up, [dy, dx])

        return False

    def place_stair(self, symbol, preferred_pos=None, avoid_pos=None):
        """Place a stair on a walkable floor tile. Returns [y, x]."""
        h, w = self._dims()

        if preferred_pos is not None:
            nearest = self._nearest_walkable(preferred_pos)
            if nearest is not None and (avoid_pos is None or nearest != avoid_pos):
                y, x = nearest
                if (y, x) in self.monsters:
                    del self.monsters[(y, x)]
                if self.game_map[y][x] in OPEN_GROUND | {'&'}:
                    self.game_map[y][x] = symbol
                    return [y, x]

        floors = [
            (y, x)
            for y, x in self._walkable_tiles()
            if self.game_map[y][x] in OPEN_GROUND
            and (avoid_pos is None or [y, x] != avoid_pos)
        ]
        if not floors:
            y, x = h // 2, w // 2
            self.game_map[y][x] = symbol
            return [y, x]

        y, x = random.choice(floors)
        self.game_map[y][x] = symbol
        return [y, x]

    def spawn_monsters(self):
        h, w = self._dims()
        for i in range(h):
            for j in range(w):
                if self.game_map[i][j] == '.' and random.random() < MONSTER_PROBABILITY:
                    type_id = pick_spawn_type_id()
                    type_def = get_monster_type(type_id)
                    level = assign_monster_level(type_def) if type_def else 1
                    monster_id = f"{type_id}-{i},{j}"
                    monster = Monster.from_type(
                        type_id, [i, j], monster_id=monster_id, level=level,
                    )
                    calibrate_instance_elo(monster)
                    self.monsters[(i, j)] = monster
                    self.game_map[i][j] = '&'

    def find_tile(self, game_map, symbol):
        for y, row in enumerate(game_map):
            for x, cell in enumerate(row):
                if cell == symbol:
                    return [y, x]
        return None

    def find_random_start(self, players, existing_monsters, game_map=None):
        check_map = game_map if game_map is not None else self.game_map
        floors = [
            (y, x)
            for y, row in enumerate(check_map)
            for x, cell in enumerate(row)
            if cell in OPEN_GROUND
        ]
        random.shuffle(floors)
        for y, x in floors:
            if self.is_position_free(x, y, players, existing_monsters, check_map):
                return [y, x]
        for y, x in floors:
            return [y, x]
        h, w = len(check_map), len(check_map[0])
        return [h // 2, w // 2]

    def is_position_free(self, x, y, players, existing_monsters, game_map=None):
        check_map = game_map if game_map is not None else self.game_map
        h, w = len(check_map), len(check_map[0])
        if not (0 <= y < h and 0 <= x < w):
            return False
        return (
            check_map[y][x] in OPEN_GROUND
            and not any(p.pos == [y, x] for p in players.values())
            and (y, x) not in existing_monsters
        )

    def _dims(self, game_map=None):
        m = game_map if game_map is not None else self.game_map
        if not m:
            return self.map_size, self.map_size
        return len(m), len(m[0])

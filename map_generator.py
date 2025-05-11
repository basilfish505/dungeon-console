import random
from monster import Monster

# Constants
MAP_SIZE = 20
BOULDER_PROBABILITY = 0.03
MONSTER_PROBABILITY = 0.06

class MapGenerator:
    def __init__(self, map_size=MAP_SIZE):
        self.map_size = map_size
        self.game_map = None
        self.monsters = {}

    def generate_level(self):
        """Generate a new level with walls, boulders, and monsters"""
        self.game_map = self.create_empty_map_with_walls()
        self.populate_map_with_boulders()
        self.spawn_monsters()
        return self.game_map, self.monsters

    def generate_top_level(self):
        """Generate the top level without boulders or monsters, but with stairs down"""
        # Create a map with only border walls
        self.game_map = [['.' for _ in range(self.map_size)] for _ in range(self.map_size)]
        # Add walls around the border
        for i in range(self.map_size):
            self.game_map[0][i] = '#'  # Top border
            self.game_map[self.map_size-1][i] = '#'  # Bottom border
            self.game_map[i][0] = '#'  # Left border
            self.game_map[i][self.map_size-1] = '#'  # Right border
        
        self.monsters = {}  # Clear any existing monsters
        
        # Place stairs down in a random position
        stairs_x, stairs_y = self.get_random_position()
        self.game_map[stairs_y][stairs_x] = '↓'  # Unicode down arrow for stairs down
        
        return self.game_map, self.monsters

    def create_empty_map_with_walls(self):
        """Create an empty map with walls around the edges"""
        return [['#' for _ in range(self.map_size)] for _ in range(self.map_size)]

    def populate_map_with_boulders(self):
        """Add boulders to the map"""
        for i in range(1, self.map_size-1):
            for j in range(1, self.map_size-1):
                self.game_map[i][j] = '#' if random.random() < BOULDER_PROBABILITY else '.'

    def spawn_monsters(self):
        """Add monsters to the map"""
        for i in range(1, self.map_size-1):
            for j in range(1, self.map_size-1):
                # Only spawn monsters on empty spaces
                if self.game_map[i][j] == '.' and random.random() < MONSTER_PROBABILITY:
                    # Select a random monster type
                    monster_types = ["Skeleton", "Ghoul", "Zombie", "Goblin", "Orc", 
                                   "Troll", "Wraith", "Lich", "Giant Spider", "Slime"]
                    monster_type = random.choice(monster_types)
                    monster_id = f"{monster_type}-{i},{j}"
                    monster = Monster(monster_id, monster_type, [i, j])
                    
                    # Store the monster in the monsters dictionary
                    self.monsters[(i, j)] = monster
                    
                    # Mark the monster's position on the map
                    self.game_map[i][j] = '&'

    def find_random_start(self, players, existing_monsters):
        """Find a random starting position that's free of players and monsters"""
        while True:
            x, y = self.get_random_position()
            if self.is_position_free(x, y, players, existing_monsters):
                return [y, x]

    def get_random_position(self):
        """Get a random position within the map bounds"""
        return random.randint(1, self.map_size-2), random.randint(1, self.map_size-2)

    def is_position_free(self, x, y, players, existing_monsters):
        """Check if a position is free of walls, players, and monsters"""
        return (self.game_map[y][x] == '.' and 
                not any(p.pos == [y, x] for p in players.values()) and
                (y, x) not in existing_monsters)

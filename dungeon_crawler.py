from flask import Flask, render_template, request, jsonify
import random
import os
import math

app = Flask(__name__)

# Game state
class GameState:
    def __init__(self):
        self.map_width = 0  # Will be set by generate_map
        self.map_height = 0  # Will be set by generate_map
        self.player_pos = [1, 1]
        self.game_map = self.generate_map()
        self.messages = ["Welcome to the dungeon! Use WASD to move."]
        self.health = 100
        self.gold = 0

    def generate_map(self):
        # Start with a much larger work area
        work_width = random.randint(60, 80)
        work_height = random.randint(50, 70)
        
        # Create empty work map (all void/unused)
        work_map = [[' ' for _ in range(work_width)] for _ in range(work_height)]
        
        # Center point
        center_x = work_width // 2
        center_y = work_height // 2
        
        # Create main cave with very irregular shape
        for y in range(5, work_height-5):
            for x in range(5, work_width-5):
                # Distance from center with lots of noise
                dx = (x - center_x) / (work_width * 0.3)
                dy = (y - center_y) / (work_height * 0.3)
                base_distance = dx*dx + dy*dy
                
                # Add multiple layers of noise
                noise1 = math.sin(x * 0.5) * math.cos(y * 0.3) * 0.2
                noise2 = math.sin(x * 0.1 + y * 0.2) * 0.3
                noise3 = random.uniform(-0.1, 0.1)
                total_noise = noise1 + noise2 + noise3
                
                # Create floor if within noise-adjusted distance
                if base_distance + total_noise < 1:
                    work_map[y][x] = '.'
        
        # Add some random cave extensions
        num_extensions = random.randint(5, 10)
        for _ in range(num_extensions):
            # Find a random edge point of the existing cave
            edge_points = []
            for y in range(1, work_height-1):
                for x in range(1, work_width-1):
                    if work_map[y][x] == '.':
                        # Check if it's an edge (has at least one empty neighbor)
                        has_empty = False
                        for ny, nx in [(y-1,x), (y+1,x), (y,x-1), (y,x+1)]:
                            if work_map[ny][nx] == ' ':
                                has_empty = True
                                break
                        if has_empty:
                            edge_points.append((y, x))
            
            if not edge_points:
                continue
            
            # Pick a random edge point
            start_y, start_x = random.choice(edge_points)
            
            # Generate a random direction away from the cave
            directions = []
            for dy, dx in [(-1,0), (1,0), (0,-1), (0,1)]:
                ny, nx = start_y + dy, start_x + dx
                if 0 <= ny < work_height and 0 <= nx < work_width:
                    if work_map[ny][nx] == ' ':
                        directions.append((dy, dx))
            
            if not directions:
                continue
            
            dy, dx = random.choice(directions)
            
            # Create a random extension
            extension_length = random.randint(5, 15)
            curr_x, curr_y = start_x, start_y
            
            for _ in range(extension_length):
                # Add some wandering to the extension
                if random.random() < 0.3:
                    # Change direction slightly
                    if dx != 0:  # Moving horizontally
                        dy = random.choice([-1, 0, 1])
                    else:  # Moving vertically
                        dx = random.choice([-1, 0, 1])
                
                # Move in the current direction
                curr_x += dx
                curr_y += dy
                
                # Stay within bounds
                if 2 <= curr_y < work_height-2 and 2 <= curr_x < work_width-2:
                    # Add main path
                    work_map[curr_y][curr_x] = '.'
                    
                    # Add some width
                    for wy in range(-1, 2):
                        for wx in range(-1, 2):
                            ny, nx = curr_y + wy, curr_x + wx
                            if 2 <= ny < work_height-2 and 2 <= nx < work_width-2:
                                if random.random() < 0.7:
                                    work_map[ny][nx] = '.'
        
        # Now add a single layer of wall/rock around all floor tiles
        # First, find all floor tiles
        floor_tiles = []
        for y in range(work_height):
            for x in range(work_width):
                if work_map[y][x] == '.':
                    floor_tiles.append((y, x))
        
        # Then add walls around them
        for y, x in floor_tiles:
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < work_height and 0 <= nx < work_width:
                        if work_map[ny][nx] == ' ':
                            work_map[ny][nx] = '#'
        
        # Find the bounds of our actual map (including the wall border)
        min_x, max_x = work_width, 0
        min_y, max_y = work_height, 0
        
        for y in range(work_height):
            for x in range(work_width):
                if work_map[y][x] != ' ':
                    min_x = min(min_x, x)
                    max_x = max(max_x, x)
                    min_y = min(min_y, y)
                    max_y = max(max_y, y)
        
        # Extract just the actual map
        self.map_width = max_x - min_x + 1
        self.map_height = max_y - min_y + 1
        
        # Create the final map
        game_map = []
        for y in range(min_y, max_y + 1):
            row = []
            for x in range(min_x, max_x + 1):
                row.append(work_map[y][x])
            game_map.append(row)
        
        # Place player in a safe spot
        player_placed = False
        for attempt in range(100):
            y = random.randint(self.map_height // 4, self.map_height * 3 // 4)
            x = random.randint(self.map_width // 4, self.map_width * 3 // 4)
            
            if 0 <= y < self.map_height and 0 <= x < self.map_width and game_map[y][x] == '.':
                # Check for open space around
                open_count = 0
                for dy in [-1, 0, 1]:
                    for dx in [-1, 0, 1]:
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < self.map_height and 0 <= nx < self.map_width:
                            if game_map[ny][nx] == '.':
                                open_count += 1
                
                if open_count >= 5:
                    self.player_pos = [y, x]
                    player_placed = True
                    break
        
        # Fallback player position
        if not player_placed:
            # Find center-ish point
            center_y = self.map_height // 2
            center_x = self.map_width // 2
            # Clear area around it
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    ny, nx = center_y + dy, center_x + dx
                    if 0 <= ny < self.map_height and 0 <= nx < self.map_width:
                        game_map[ny][nx] = '.'
            self.player_pos = [center_y, center_x]
        
        # Add monsters, gold and health potions
        for y in range(self.map_height):
            for x in range(self.map_width):
                if game_map[y][x] == '.':
                    roll = random.random()
                    if [y, x] != self.player_pos:  # Don't place on player
                        if roll < 0.08:
                            game_map[y][x] = 'M'  # Monster
                        elif roll < 0.15:
                            game_map[y][x] = 'G'  # Gold
                        elif roll < 0.18:
                            game_map[y][x] = 'H'  # Health potion
        
        return game_map

    def move_player(self, direction):
        # If health is already 0, don't allow any more moves
        if self.health <= 0:
            return False
            
        new_pos = self.player_pos.copy()
        
        if direction == 'w':
            new_pos[0] -= 1
        elif direction == 's':
            new_pos[0] += 1
        elif direction == 'a':
            new_pos[1] -= 1
        elif direction == 'd':
            new_pos[1] += 1

        # Check if move is valid
        if (0 <= new_pos[0] < self.map_height and 
            0 <= new_pos[1] < self.map_width and 
            self.game_map[new_pos[0]][new_pos[1]] != '#'):
            
            # Handle what's in the new position
            tile = self.game_map[new_pos[0]][new_pos[1]]
            
            if tile == 'M':
                damage = random.randint(10, 20)
                self.health -= damage
                self.messages.append(f"You fought a monster! Took {damage} damage!")
                if self.health <= 0:
                    self.messages.append("Game Over! You died!")
                    return False
            
            elif tile == 'G':
                gold_amount = random.randint(10, 30)
                self.gold += gold_amount
                self.messages.append(f"You found {gold_amount} gold!")
            
            elif tile == 'H':
                heal_amount = random.randint(20, 40)
                self.health = min(100, self.health + heal_amount)
                self.messages.append(f"You found a health potion! Healed {heal_amount} HP!")

            # Clear the tile and move player
            self.game_map[new_pos[0]][new_pos[1]] = '.'
            self.player_pos = new_pos
            
        return True

game_state = GameState()

@app.route('/')
def home():
    return render_template('dungeon.html')

@app.route('/move/<direction>')
def move(direction):
    global game_state
    
    if not game_state.move_player(direction):
        # Reset the game when player dies
        game_state = GameState()
        return jsonify({
            'game_over': True,
            'map': game_state.game_map,
            'messages': game_state.messages,
            'health': game_state.health,
            'gold': game_state.gold
        })
    
    # Keep only last 5 messages
    game_state.messages = game_state.messages[-5:]
    
    # Create visible map (showing only near player)
    visible_map = [row[:] for row in game_state.game_map]
    visible_map[game_state.player_pos[0]][game_state.player_pos[1]] = '@'
    
    # Important: Don't pad the map with empty space
    return jsonify({
        'map': visible_map,
        'messages': game_state.messages,
        'health': game_state.health,
        'gold': game_state.gold,
        'game_over': False
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001))) 
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
        self.current_level = 0  # Start at level 0
        self.levels = {}  # Store multiple levels
        
        # Create empty structure for first level
        self.levels[0] = {
            'map': None,  # Will be set after generation
            'stairs_down_pos': None,
            'stairs_up_pos': None
        }
        
        # Generate the first level map
        first_map = self.generate_map()
        
        # Now store the generated map
        self.levels[0]['map'] = first_map
        self.game_map = first_map
        
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
        
        # After creating the basic cave, identify perimeter walls for rocks
        marked_map = [row[:] for row in game_map]
        for y in range(self.map_height):
            for x in range(self.map_width):
                if game_map[y][x] == '#':
                    # Check if this wall is adjacent to the map edge or void
                    is_perimeter = False
                    if (y == 0 or y == self.map_height-1 or 
                        x == 0 or x == self.map_width-1):
                        is_perimeter = True
                    
                    # Also check for adjacent void
                    for dy in [-1, 0, 1]:
                        for dx in [-1, 0, 1]:
                            ny, nx = y + dy, x + dx
                            if (0 <= ny < self.map_height and 
                                0 <= nx < self.map_width and 
                                game_map[ny][nx] == ' '):
                                is_perimeter = True
                    
                    if is_perimeter:
                        marked_map[y][x] = 'P'  # Mark as perimeter
        
        # Add internal rocks - but much fewer!
        # Large hollow rock formations (2-4)
        num_large_formations = random.randint(2, 4)
        for _ in range(num_large_formations):
            center_y = random.randint(self.map_height//4, self.map_height*3//4)
            center_x = random.randint(self.map_width//4, self.map_width*3//4)
            
            # Skip if too close to perimeter
            too_close = False
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    ny, nx = center_y + dy, center_x + dx
                    if (0 <= ny < self.map_height and 
                        0 <= nx < self.map_width and 
                        marked_map[ny][nx] == 'P'):
                        too_close = True
                        break
            if too_close:
                continue
            
            outer_radius = random.randint(2, 4)
            inner_radius = max(1, outer_radius - 1)
            
            # Create the formation
            formation = {}
            for y in range(center_y - outer_radius, center_y + outer_radius + 1):
                for x in range(center_x - outer_radius, center_x + outer_radius + 1):
                    if (0 <= y < self.map_height and 
                        0 <= x < self.map_width and 
                        game_map[y][x] == '.'):
                        
                        dist = ((y - center_y)**2 + (x - center_x)**2)**0.5
                        noise = random.uniform(-0.6, 0.6)
                        if dist + noise < outer_radius:
                            formation[(y, x)] = '#'
            
            # Hollow out the center
            for y in range(center_y - inner_radius, center_y + inner_radius + 1):
                for x in range(center_x - inner_radius, center_x + inner_radius + 1):
                    if (y, x) in formation:
                        dist = ((y - center_y)**2 + (x - center_x)**2)**0.5
                        if dist < inner_radius:
                            formation[(y, x)] = '.'
            
            # Apply to map
            for (y, x), cell in formation.items():
                game_map[y][x] = cell
                if cell == '#':
                    marked_map[y][x] = 'I'
        
        # Medium rock formations (3-5)
        num_medium_formations = random.randint(3, 5)
        for _ in range(num_medium_formations):
            center_y = random.randint(3, self.map_height - 4)
            center_x = random.randint(3, self.map_width - 4)
            
            # Skip if too close to existing rocks
            too_close = False
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    ny, nx = center_y + dy, center_x + dx
                    if (0 <= ny < self.map_height and 
                        0 <= nx < self.map_width and 
                        (marked_map[ny][nx] == 'P' or marked_map[ny][nx] == 'I')):
                        too_close = True
                        break
            if too_close:
                continue
            
            # Create medium formation
            radius = random.randint(1, 2)
            for y in range(center_y - radius, center_y + radius + 1):
                for x in range(center_x - radius, center_x + radius + 1):
                    if (0 <= y < self.map_height and 
                        0 <= x < self.map_width and 
                        game_map[y][x] == '.'):
                        
                        dist = ((y - center_y)**2 + (x - center_x)**2)**0.5
                        if dist < radius + random.uniform(-0.3, 0.3):
                            game_map[y][x] = '#'
                            marked_map[y][x] = 'I'
        
        # Individual rocks (10-15)
        num_small_rocks = random.randint(10, 15)
        for _ in range(num_small_rocks):
            y = random.randint(2, self.map_height - 3)
            x = random.randint(2, self.map_width - 3)
            
            if (game_map[y][x] == '.' and
                not any((marked_map[y+dy][x+dx] == 'P' or marked_map[y+dy][x+dx] == 'I')
                        for dy in [-1, 0, 1] 
                        for dx in [-1, 0, 1] 
                        if 0 <= y+dy < self.map_height and 
                           0 <= x+dx < self.map_width)):
                
                game_map[y][x] = '#'
                marked_map[y][x] = 'I'
        
        # Flood fill to ensure map is navigable
        flood_map = [row[:] for row in game_map]
        
        # Find a random floor tile as start
        start_y, start_x = None, None
        for y in range(self.map_height):
            for x in range(self.map_width):
                if game_map[y][x] == '.':
                    start_y, start_x = y, x
                    break
            if start_y is not None:
                break
        
        # Flood fill
        if start_y is not None:
            to_fill = [(start_y, start_x)]
            while to_fill:
                y, x = to_fill.pop(0)
                if 0 <= y < self.map_height and 0 <= x < self.map_width and flood_map[y][x] == '.':
                    flood_map[y][x] = 'F'  # Marked as filled
                    for dy, dx in [(0,1), (1,0), (0,-1), (-1,0)]:
                        to_fill.append((y + dy, x + dx))
        
        # Remove any disconnected areas
        for y in range(self.map_height):
            for x in range(self.map_width):
                if game_map[y][x] == '.' and flood_map[y][x] != 'F':
                    game_map[y][x] = '#'
        
        # Place player
        player_placed = False
        for attempt in range(100):
            y = random.randint(self.map_height//4, self.map_height*3//4)
            x = random.randint(self.map_width//4, self.map_width*3//4)
            
            if game_map[y][x] == '.':
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
            for y in range(self.map_height):
                for x in range(self.map_width):
                    if game_map[y][x] == '.':
                        self.player_pos = [y, x]
                        for dy in [-1, 0, 1]:
                            for dx in [-1, 0, 1]:
                                ny, nx = y + dy, x + dx
                                if 0 <= ny < self.map_height and 0 <= nx < self.map_width:
                                    game_map[ny][nx] = '.'
                        player_placed = True
                        break
                if player_placed:
                    break
        
        # Add monsters, gold and health potions
        for y in range(self.map_height):
            for x in range(self.map_width):
                if game_map[y][x] == '.':
                    roll = random.random()
                    if [y, x] != self.player_pos:  # Don't place on player
                        if roll < 0.05:  # Reduced monster frequency
                            game_map[y][x] = 'M'  # Monster
                        elif roll < 0.10:  # Reduced item frequency
                            game_map[y][x] = 'G'  # Gold
                        elif roll < 0.12:  # Reduced item frequency
                            game_map[y][x] = 'H'  # Health potion
        
        # Add stairs down to the next level - pick a remote location
        stairs_placed = False
        # First try to place stairs far from player
        candidate_spots = []
        for y in range(self.map_height):
            for x in range(self.map_width):
                if game_map[y][x] == '.':
                    player_distance = ((y - self.player_pos[0])**2 + (x - self.player_pos[1])**2)**0.5
                    if player_distance > self.map_height/3:  # Must be reasonably far
                        open_space = sum(1 for dy in [-1, 0, 1] for dx in [-1, 0, 1]
                                        if 0 <= y+dy < self.map_height and 0 <= x+dx < self.map_width
                                        and game_map[y+dy][x+dx] == '.')
                        if open_space >= 5:  # Must have open space around
                            candidate_spots.append((y, x, player_distance))
        
        # Sort by distance from player (farthest first)
        candidate_spots.sort(key=lambda spot: -spot[2])
        
        # Place stairs at a good spot
        for y, x, _ in candidate_spots[:5]:  # Try the 5 best spots
            game_map[y][x] = '⌄'  # Down stairs
            
            # Store stairs location
            if self.current_level in self.levels:
                self.levels[self.current_level]['stairs_down_pos'] = [y, x]
                
            stairs_placed = True
            break
        
        # If still not placed, try anywhere
        if not stairs_placed:
            for y in range(self.map_height):
                for x in range(self.map_width):
                    if game_map[y][x] == '.' and [y, x] != self.player_pos:
                        game_map[y][x] = '⌄'
                        
                        # Store stairs location
                        if self.current_level in self.levels:
                            self.levels[self.current_level]['stairs_down_pos'] = [y, x]
                            
                        stairs_placed = True
                        break
                if stairs_placed:
                    break
        
        return game_map

    def create_new_level(self):
        # Save current level information
        self.levels[self.current_level]['map'] = self.game_map
        
        # Create new level
        self.current_level += 1
        
        # Check if we've already visited this level
        if self.current_level in self.levels:
            # Restore existing level
            self.game_map = self.levels[self.current_level]['map']
            self.map_height = len(self.game_map)
            self.map_width = len(self.game_map[0])
            
            # Place player at the stairs up position
            if self.levels[self.current_level]['stairs_up_pos']:
                self.player_pos = self.levels[self.current_level]['stairs_up_pos'][:]
                
            self.messages.append(f"You returned to level {self.current_level + 1}!")
        else:
            # Important: Create the level structure BEFORE generating the map
            self.levels[self.current_level] = {
                'map': None,  # Will be set after generation
                'stairs_down_pos': None,
                'stairs_up_pos': None
            }
            
            # Generate new level
            self.map_width = 0  # Reset so generate_map creates new dimensions
            self.map_height = 0
            new_map = self.generate_map()
            
            # Find a good spot for stairs up (away from stairs down)
            stairs_up_placed = False
            for attempt in range(100):
                y = random.randint(4, self.map_height - 5)
                x = random.randint(4, self.map_width - 5)
                
                if new_map[y][x] == '.':
                    # Check for open space
                    open_space = sum(1 for dy in [-1, 0, 1] for dx in [-1, 0, 1]
                                   if 0 <= y+dy < self.map_height and 0 <= x+dx < self.map_width
                                   and new_map[y+dy][x+dx] == '.')
                    
                    if open_space >= 6:
                        new_map[y][x] = '⌃'  # Place up stairs
                        self.player_pos = [y, x]  # Player starts here
                        self.levels[self.current_level]['stairs_up_pos'] = [y, x]
                        stairs_up_placed = True
                        break
            
            # Fallback
            if not stairs_up_placed:
                for y in range(self.map_height):
                    for x in range(self.map_width):
                        if new_map[y][x] == '.':
                            new_map[y][x] = '⌃'  # Place up stairs
                            self.player_pos = [y, x]
                            self.levels[self.current_level]['stairs_up_pos'] = [y, x]
                            stairs_up_placed = True
                            break
                        if stairs_up_placed:
                            break
            
            # Store the new map
            self.levels[self.current_level]['map'] = new_map
            self.game_map = new_map
            self.messages.append(f"You descended to level {self.current_level + 1}!")

    def return_to_previous_level(self):
        if self.current_level > 0:
            # Save current level data
            self.levels[self.current_level]['map'] = self.game_map
            
            # Move up a level
            self.current_level -= 1
            
            # Restore previous level
            self.game_map = self.levels[self.current_level]['map']
            self.map_height = len(self.game_map)
            self.map_width = len(self.game_map[0])
            
            # Place player at stairs down location
            if self.levels[self.current_level]['stairs_down_pos']:
                self.player_pos = self.levels[self.current_level]['stairs_down_pos'][:]
            
            self.messages.append(f"You ascended to level {self.current_level + 1}!")
            return True
        return False

    def move_player(self, direction):
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
        elif direction == 'start':
            # Just return current state
            return True

        # Check if move is valid
        if (0 <= new_pos[0] < self.map_height and 
            0 <= new_pos[1] < self.map_width and 
            self.game_map[new_pos[0]][new_pos[1]] != '#'):
            
            # What's in the new position
            tile = self.game_map[new_pos[0]][new_pos[1]]
            
            if tile == 'M':
                damage = random.randint(10, 20)
                self.health -= damage
                self.messages.append(f"You fought a monster! Took {damage} damage!")
                if self.health <= 0:
                    self.messages.append("Game Over! You died!")
                    return False
                self.game_map[new_pos[0]][new_pos[1]] = '.'
            
            elif tile == 'G':
                gold_amount = random.randint(10, 30)
                self.gold += gold_amount
                self.messages.append(f"You found {gold_amount} gold!")
                self.game_map[new_pos[0]][new_pos[1]] = '.'
            
            elif tile == 'H':
                heal_amount = random.randint(20, 40)
                self.health = min(100, self.health + heal_amount)
                self.messages.append(f"You found a health potion! Healed {heal_amount} HP!")
                self.game_map[new_pos[0]][new_pos[1]] = '.'

            elif tile == '⌄':  # Down stairs
                # Create new level - don't modify current tile
                self.create_new_level()
                return True
                
            elif tile == '⌃':  # Up stairs
                # Return to previous level - don't modify current tile
                self.return_to_previous_level()
                return True
            
            # For normal floor movement
            if tile == '.':
                # Update the player's previous position
                old_y, old_x = self.player_pos
                
                # Handle special cases for previous position
                # Check if leaving stairs up
                if (self.levels[self.current_level]['stairs_up_pos'] and 
                    old_y == self.levels[self.current_level]['stairs_up_pos'][0] and
                    old_x == self.levels[self.current_level]['stairs_up_pos'][1]):
                    # Player was on up stairs, don't clear them
                    pass  # The up stairs remain
                
                # Check if leaving stairs down
                elif (self.levels[self.current_level]['stairs_down_pos'] and
                     old_y == self.levels[self.current_level]['stairs_down_pos'][0] and
                     old_x == self.levels[self.current_level]['stairs_down_pos'][1]):
                    # Player was on down stairs, don't clear them
                    pass  # The down stairs remain
                
                else:
                    # Normal case - clear old position
                    self.game_map[old_y][old_x] = '.'
                
                # Update player position
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
    
    # Add current level info to the JSON response
    return jsonify({
        'map': visible_map,
        'messages': game_state.messages,
        'health': game_state.health,
        'gold': game_state.gold,
        'game_over': False,
        'current_level': game_state.current_level + 1  # Display as level 1, 2, 3, etc.
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001))) 
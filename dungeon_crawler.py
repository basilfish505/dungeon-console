from flask import Flask, render_template, request, jsonify
import random
import os

app = Flask(__name__)

# Game state
class GameState:
    def __init__(self):
        self.map_size = 25
        self.player_pos = [1, 1]
        self.game_map = self.generate_map()
        self.messages = ["Welcome to the dungeon! Use WASD to move."]
        self.health = 100
        self.gold = 0

    def generate_map(self):
        # Create empty map with walls
        game_map = [['#' for _ in range(self.map_size)] for _ in range(self.map_size)]
        
        # Create paths
        for i in range(1, self.map_size-1):
            for j in range(1, self.map_size-1):
                if random.random() > 0.1:  # 90% chance of being a path
                    game_map[i][j] = '.'
                    
                    # Sometimes add items or monsters
                    if random.random() < 0.1:
                        game_map[i][j] = 'M'  # Monster
                    elif random.random() < 0.1:
                        game_map[i][j] = 'G'  # Gold
                    elif random.random() < 0.05:
                        game_map[i][j] = 'H'  # Health potion

        # Ensure player starting position is clear
        game_map[1][1] = '.'
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
        if (0 <= new_pos[0] < self.map_size and 
            0 <= new_pos[1] < self.map_size and 
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
    
    return jsonify({
        'map': visible_map,
        'messages': game_state.messages,
        'health': game_state.health,
        'gold': game_state.gold,
        'game_over': False
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001))) 
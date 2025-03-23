from flask import Flask, render_template, request, jsonify
import random
import os

app = Flask(__name__)

# Game state
class GameState:
    def __init__(self):
        self.map_size = 20
        self.game_map = self.generate_map()
        self.player_pos = self.find_random_start()
        self.messages = ["Welcome to the dungeon! Use WASD to move."]

    def find_random_start(self):
        while True:
            # Random position (avoiding edges)
            x = random.randint(1, self.map_size-2)
            y = random.randint(1, self.map_size-2)
            if self.game_map[y][x] == '.':
                return [y, x]

    def generate_map(self):
        # Create empty map with walls
        game_map = [['#' for _ in range(self.map_size)] for _ in range(self.map_size)]
        
        # Create simple empty box with random boulders
        for i in range(1, self.map_size-1):
            for j in range(1, self.map_size-1):
                if random.random() < 0.03:  # 3% chance of boulder
                    game_map[i][j] = '#'
                else:
                    game_map[i][j] = '.'

        return game_map

    def move_player(self, direction):
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
            
            # Move player
            self.player_pos = new_pos
            
        return True

game_state = GameState()

@app.route('/')
def home():
    return render_template('dungeon.html')

@app.route('/move/<direction>')
def move(direction):
    global game_state
    
    game_state.move_player(direction)
    
    # Keep only last 5 messages
    game_state.messages = game_state.messages[-5:]
    
    # Create visible map (showing only near player)
    visible_map = [row[:] for row in game_state.game_map]
    visible_map[game_state.player_pos[0]][game_state.player_pos[1]] = '@'
    
    return jsonify({
        'map': visible_map,
        'messages': game_state.messages,
        'game_over': False
    })

if __name__ == '__main__':
    if os.environ.get('FLASK_ENV') == 'production':
        app.run(host='0.0.0.0', 
                port=int(os.environ.get('PORT', 5001)),
                debug=False)
    else:
        app.run(host='0.0.0.0', 
                port=int(os.environ.get('PORT', 5001)),
                debug=True) 
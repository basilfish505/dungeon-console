from flask import Flask, render_template, session, redirect, url_for
import random

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Required for session

def create_dungeon(size=10):
    # Create empty dungeon
    dungeon = [[' ' for _ in range(size)] for _ in range(size)]
    
    # Add walls randomly (about 20% of spaces)
    for i in range(size):
        for j in range(size):
            if random.random() < 0.2:
                dungeon[i][j] = '#'
    
    # Ensure starting position is empty
    dungeon[0][0] = ' '
    return dungeon

@app.route('/')
def home():
    # Initialize game state
    dungeon = create_dungeon()
    session['dungeon'] = dungeon
    session['player'] = {'x': 0, 'y': 0, 'hp': 20, 'attack': 5}
    
    # Create monsters ensuring they don't spawn on walls
    monsters = []
    for _ in range(3):  # Create 3 monsters
        while True:
            x = random.randint(1, 8)
            y = random.randint(1, 8)
            # Only place monster if position is empty (not a wall)
            if dungeon[y][x] == ' ':
                monsters.append({'x': x, 'y': y, 'hp': 15, 'attack': 3, 'symbol': 'X'})
                break
    
    session['monsters'] = monsters
    session['game_over'] = False
    session['message'] = "Welcome to the dungeon!"
    
    return render_template('game.html',
                         dungeon=dungeon,
                         player=session['player'],
                         monsters=session['monsters'],
                         message=session['message'],
                         game_over=session['game_over'])

@app.route('/move/<direction>')
def move(direction):
    if session.get('game_over', True):
        return redirect(url_for('home'))
    
    player = session['player']
    dungeon = session['dungeon']
    monsters = session['monsters']
    message = ""
    
    # Calculate new position
    new_x, new_y = player['x'], player['y']
    if direction == 'up' and player['y'] > 0:
        new_y -= 1
    elif direction == 'down' and player['y'] < len(dungeon) - 1:
        new_y += 1
    elif direction == 'left' and player['x'] > 0:
        new_x -= 1
    elif direction == 'right' and player['x'] < len(dungeon[0]) - 1:
        new_x += 1
    
    # Check for walls
    if dungeon[new_y][new_x] == '#':
        message = "You hit a wall!"
        new_x, new_y = player['x'], player['y']
    
    # Check for monster collision
    for monster in monsters:
        if monster['x'] == new_x and monster['y'] == new_y and monster['hp'] > 0:
            # Combat!
            monster['hp'] -= player['attack']
            message = f"You hit the monster for {player['attack']} damage!"
            if monster['hp'] <= 0:
                message = "You defeated the monster!"
            else:
                player['hp'] -= monster['attack']
                message += f" Monster hits back for {monster['attack']} damage!"
            new_x, new_y = player['x'], player['y']  # Don't move into monster's space
    
    # Update player position
    player['x'], player['y'] = new_x, new_y
    
    # Move monsters (simple AI - move towards player)
    for monster in monsters:
        if monster['hp'] <= 0:
            continue
        
        dx = player['x'] - monster['x']
        dy = player['y'] - monster['y']
        
        if abs(dx) > abs(dy):
            new_x = monster['x'] + (1 if dx > 0 else -1)
            new_y = monster['y']
        else:
            new_x = monster['x']
            new_y = monster['y'] + (1 if dy > 0 else -1)
            
        # Check if new position is valid
        if (0 <= new_x < len(dungeon[0]) and 
            0 <= new_y < len(dungeon) and 
            dungeon[new_y][new_x] != '#'):
            monster['x'], monster['y'] = new_x, new_y
    
    # Check for game over
    if player['hp'] <= 0:
        session['game_over'] = True
        message = "Game Over! You died!"
    
    # Update session
    session['player'] = player
    session['monsters'] = monsters
    session['message'] = message
    
    return render_template('game.html',
                         dungeon=dungeon,
                         player=player,
                         monsters=monsters,
                         message=message,
                         game_over=session['game_over'])

if __name__ == '__main__':
    app.run(debug=True)  # Add debug=True for development 
from flask import Flask, render_template, session, redirect, url_for
import random

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Required for session

def create_dungeon():
    # Create a 10x10 dungeon with walls and empty spaces
    dungeon = [['#' for _ in range(10)] for _ in range(10)]
    
    # Create paths through the dungeon
    for y in range(1, 9):
        for x in range(1, 9):
            if random.random() > 0.3:  # 70% chance of empty space
                dungeon[y][x] = ' '
    
    # Ensure starting position is empty
    dungeon[1][1] = ' '
    return dungeon

@app.route('/')
def home():
    # Initialize game state
    dungeon = create_dungeon()
    session['dungeon'] = dungeon
    session['player'] = {'x': 1, 'y': 1, 'hp': 20, 'attack': 5}
    
    # Create monsters
    monsters = []
    for _ in range(4):  # Create 4 monsters
        while True:
            x = random.randint(1, 8)
            y = random.randint(1, 8)
            if dungeon[y][x] == ' ':
                monsters.append({
                    'x': x,
                    'y': y,
                    'hp': 10,
                    'attack': 3,
                    'symbol': '👾'
                })
                break
    
    session['monsters'] = monsters
    session['game_over'] = False
    session['message'] = "Welcome to the dungeon! Find the treasure! 💎"
    
    # Place treasure
    while True:
        tx = random.randint(6, 8)
        ty = random.randint(6, 8)
        if dungeon[ty][tx] == ' ':
            session['treasure'] = {'x': tx, 'y': ty}
            break
    
    return render_template('game.html',
                         dungeon=dungeon,
                         player=session['player'],
                         monsters=monsters,
                         message=session['message'],
                         treasure=session['treasure'],
                         game_over=session['game_over'])

@app.route('/move/<direction>')
def move(direction):
    if session.get('game_over', True):
        return redirect(url_for('home'))
    
    player = session['player']
    dungeon = session['dungeon']
    monsters = session['monsters']
    treasure = session['treasure']
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
    
    # Check for treasure
    elif new_x == treasure['x'] and new_y == treasure['y']:
        session['game_over'] = True
        message = "You found the treasure! You win! 🎉"
        player['x'], player['y'] = new_x, new_y
        return render_template('game.html',
                            dungeon=dungeon,
                            player=player,
                            monsters=monsters,
                            message=message,
                            treasure=treasure,
                            game_over=True)
    
    # Check for monster collision and handle combat
    for monster in monsters[:]:
        if monster['x'] == new_x and monster['y'] == new_y:
            monster['hp'] -= player['attack']
            message = f"You hit the monster for {player['attack']} damage! "
            
            if monster['hp'] <= 0:
                message += "You defeated the monster!"
                monsters.remove(monster)
            else:
                player['hp'] -= monster['attack']
                message += f"Monster hits back for {monster['attack']} damage!"
                new_x, new_y = player['x'], player['y']
            break
    
    # Update player position
    player['x'], player['y'] = new_x, new_y
    
    # Move monsters
    for monster in monsters:
        if random.random() > 0.5:  # 50% chance to move
            dx = player['x'] - monster['x']
            dy = player['y'] - monster['y']
            
            if abs(dx) > abs(dy):
                new_x = monster['x'] + (1 if dx > 0 else -1)
                new_y = monster['y']
            else:
                new_x = monster['x']
                new_y = monster['y'] + (1 if dy > 0 else -1)
                
            if (dungeon[new_y][new_x] == ' ' and
                not any(m != monster and m['x'] == new_x and m['y'] == new_y 
                       for m in monsters)):
                monster['x'], monster['y'] = new_x, new_y
    
    # Check for game over
    if player['hp'] <= 0:
        session['game_over'] = True
        message = "Game Over! You died! ☠️"
    
    # Update session
    session['player'] = player
    session['monsters'] = monsters
    session['message'] = message
    
    return render_template('game.html',
                         dungeon=dungeon,
                         player=player,
                         monsters=monsters,
                         message=message,
                         treasure=treasure,
                         game_over=session['game_over'])

if __name__ == '__main__':
    app.run(debug=True) 
class Monster:
    def __init__(self, monster_id, monster_type, position):
        self.id = monster_id  # Unique identifier
        self.type = monster_type  # Type of the monster (e.g., "Goblin")
        self.pos = position   # Position on the map
        self.hp = 20          # Starting HP, slightly lower than players
        self.attack_power = 5 # Basic attack power
        self.in_combat = False # Combat status flag
    
    def move(self, direction):
        # Placeholder for movement logic - match Player interface
        # For now, just return current position
        return self.pos
    
    def to_dict(self):
        # Match Player's to_dict method for consistent interface
        return {
            'id': self.id,
            'type': self.type,  # Include type for display purposes
            'hp': self.hp,
            'pos': self.pos,
            'attack_power': self.attack_power
        }
    
    def receive_attack(self, damage):
        # Method to handle receiving damage
        self.hp -= damage
        return self.hp <= 0  # Return True if monster is defeated
    
    def __str__(self):
        return f"Monster: {self.type}, HP: {self.hp}, Attack: {self.attack_power}, Position: {self.pos}"

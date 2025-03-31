// Handle turn notification
function handleTurnNotification(data) {
    // Update button states to enable actions
    updateButtonStates(data.your_turn);
    
    // Show turn message
    if (data.message) {
        elements.combatMessage.innerHTML = data.message;
    }
    
    // Update opponent thinking message if it's not our turn
    if (!data.your_turn) {
        elements.opponentThinking.style.display = 'block';
        elements.opponentThinking.textContent = data.message;
    } else {
        elements.opponentThinking.style.display = 'none';
    }
    
    // Play a sound or add some visual effect to get attention (optional)
    // Example: flash the combat message briefly
    if (data.your_turn) {
        elements.combatMessage.style.color = "#ffff00";  // Yellow flash
        setTimeout(() => {
            elements.combatMessage.style.color = "#00ff00";  // Back to green
        }, 500);
    }
    
    // Update the combatants list to highlight the active player
    if (data.active_player && currentBattle.opponents) {
        currentBattle.opponents.forEach(opponent => {
            opponent.is_current_turn = (opponent.id === data.active_player);
        });
        updateOpponentsList();
    }
}

// Handle combat action
function handleCombatAction(data) {
    // Update button states
    updateButtonStates(data.your_turn);
    
    // Update combat message
    if (data.message) {
        elements.combatMessage.innerHTML = data.message;
    }
    
    // Show opponent thinking message if it's not our turn
    if (!data.your_turn) {
        elements.opponentThinking.style.display = 'block';
        if (data.target_id) {
            elements.opponentThinking.textContent = `Waiting for next turn...`;
        }
    } else {
        elements.opponentThinking.style.display = 'none';
    }
    
    // Update combatants status if provided
    if (data.combatants) {
        // Update our tracking of opponents
        currentBattle.opponents = data.combatants.filter(c => 
            c.id !== document.getElementById('player-id').value // Filter out the current player
        );
        
        // Update the opponents list
        updateOpponentsList();
    }
    
    // Update player HP if provided
    if (data.your_hp) {
        const playerHP = document.getElementById('player-hp');
        if (playerHP) {
            playerHP.textContent = data.your_hp;
        }
    }
} 
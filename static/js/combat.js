// combat.js - Handles combat interactions
const Combat = (function() {
    // Cache combat elements
    const elements = {
        combatBox: document.getElementById('combat-box'),
        opponentName: document.getElementById('opponent-name'),
        opponentHP: document.getElementById('opponent-hp'),
        combatMessage: document.getElementById('combat-message'),
        opponentThinking: document.getElementById('opponent-thinking'),
        targetSelection: document.getElementById('target-selection'),
        opponentsList: document.getElementById('opponents-list'),
        attackBtn: document.getElementById('attack-btn'),
        defendBtn: document.getElementById('defend-btn'),
        spellBtn: document.getElementById('spell-btn'),
        itemBtn: document.getElementById('item-btn'),
        runBtn: document.getElementById('run-btn')
    };
    
    // Track current battle state
    let currentBattle = {
        battleId: null,
        opponents: [],
        selectedTarget: null
    };
    
    // Update combat buttons based on turn
    function updateButtonStates(isYourTurn) {
        if (isYourTurn === false) {
            // It's NOT your turn - disable ALL buttons
            elements.attackBtn.disabled = true;
            elements.defendBtn.disabled = true;
            elements.spellBtn.disabled = true;
            elements.itemBtn.disabled = true;
            elements.runBtn.disabled = true;
            
            // Show opponent thinking message
            elements.opponentThinking.style.display = 'block';
            elements.opponentThinking.textContent = "Waiting for opponent's move...";
        } else if (isYourTurn === true) {
            // It's your turn - enable attack and defend, disable others
            elements.attackBtn.disabled = false;
            elements.defendBtn.disabled = false;
            elements.spellBtn.disabled = true;
            elements.itemBtn.disabled = true;
            elements.runBtn.disabled = true;
            
            // Hide opponent thinking message when it's your turn
            elements.opponentThinking.style.display = 'none';
        }
    }
    
    // Handle combat start
    function handleCombatStart(data) {
        // Store battle info
        currentBattle.battleId = data.battle_id;
        currentBattle.opponents = data.opponents;
        
        // Show combat UI
        elements.combatBox.style.display = 'block';
        
        // Update opponents list
        updateOpponentsList();
        
        // Set initial message
        elements.combatMessage.innerHTML = "Combat has begun! Select your target and action.";
        
        // Update button states
        updateButtonStates(data.your_turn);
    }
    
    // Update the list of opponents
    function updateOpponentsList() {
        if (!elements.opponentsList) {
            // Create opponents list if it doesn't exist
            elements.opponentsList = document.createElement('div');
            elements.opponentsList.id = 'opponents-list';
            elements.opponentsList.className = 'opponents-list';
            elements.combatBox.appendChild(elements.opponentsList);
        }
        
        // Clear existing list
        elements.opponentsList.innerHTML = '<h4>Combatants:</h4>';
        
        // Add each opponent to the list
        currentBattle.opponents.forEach((opponent, index) => {
            const opponentEl = document.createElement('div');
            opponentEl.className = 'opponent-entry';
            opponentEl.dataset.id = opponent.is_monster ? opponent.monster_id || opponent.id : opponent.id;
            opponentEl.dataset.index = index;
            
            // Mark selected target
            if (currentBattle.selectedTarget === opponent.id) {
                opponentEl.classList.add('selected-target');
            }
            
            // Mark current turn
            if (opponent.is_current_turn) {
                opponentEl.classList.add('current-turn');
            }
            
            // Create display name with current turn indicator
            const turnIndicator = opponent.is_current_turn ? '→ ' : '';
            const typeIndicator = opponent.is_monster ? ' (Monster)' : '';
            const defendIndicator = opponent.defending ? ' 🛡️' : '';
            
            opponentEl.innerHTML = `
                <span class="opponent-name">${turnIndicator}${opponent.id}${typeIndicator}${defendIndicator}</span>
                <span class="opponent-hp">HP: ${opponent.hp}</span>
            `;
            
            // Add click handler for target selection (but only if it's a valid target)
            opponentEl.addEventListener('click', function() {
                // Update selected target
                currentBattle.selectedTarget = opponent.id;
                
                // Update visual selection
                document.querySelectorAll('.opponent-entry').forEach(el => {
                    el.classList.remove('selected-target');
                });
                this.classList.add('selected-target');
                
                // Update primary display
                elements.opponentName.textContent = opponent.id;
                elements.opponentHP.textContent = opponent.hp;
            });
            
            elements.opponentsList.appendChild(opponentEl);
        });
        
        // Select first opponent by default if none selected
        if (!currentBattle.selectedTarget && currentBattle.opponents.length > 0) {
            currentBattle.selectedTarget = currentBattle.opponents[0].id;
            const firstOpponent = elements.opponentsList.querySelector('.opponent-entry');
            if (firstOpponent) {
                firstOpponent.classList.add('selected-target');
                
                // Update primary display
                elements.opponentName.textContent = currentBattle.opponents[0].id;
                elements.opponentHP.textContent = currentBattle.opponents[0].hp;
            }
        }
    }
    
    // Handle target selection request
    function handleTargetRequest(data) {
        // Store opponents data
        currentBattle.opponents = data.targets;
        
        // Update opponents list
        updateOpponentsList();
        
        // Show target selection message
        elements.combatMessage.innerHTML = "Select a target for your action.";
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
    
    // Handle monster death
    function handleMonsterDeath(data) {
        // Show death message
        elements.combatMessage.innerHTML = data.message;
        
        // Remove the monster from our opponents list
        currentBattle.opponents = currentBattle.opponents.filter(opponent => 
            !(opponent.is_monster && opponent.id === data.monster_id)
        );
        
        // Update the opponents list
        updateOpponentsList();
        
        // Add message to log
        const messageLog = document.getElementById('message-log');
        messageLog.innerHTML += `<div>${data.message}</div>`;
        messageLog.scrollTop = messageLog.scrollHeight;
    }
    
    // Handle player death
    function handlePlayerDeath(data) {
        // Show death message
        elements.combatMessage.innerHTML = data.message;
        
        // Remove the player from our opponents list
        currentBattle.opponents = currentBattle.opponents.filter(opponent => 
            opponent.is_monster || opponent.id !== data.player_id
        );
        
        // Update the opponents list
        updateOpponentsList();
        
        // Add message to log
        const messageLog = document.getElementById('message-log');
        messageLog.innerHTML += `<div>${data.message}</div>`;
        messageLog.scrollTop = messageLog.scrollHeight;
    }
    
    // Handle combat end
    function handleCombatEnd(data) {
        // Hide combat UI
        elements.combatBox.style.display = 'none';
        
        // Reset battle state
        currentBattle = {
            battleId: null,
            opponents: [],
            selectedTarget: null
        };
        
        // Add the message to log
        if (data.message) {
            const messageLog = document.getElementById('message-log');
            messageLog.innerHTML += `<div>${data.message}</div>`;
            messageLog.scrollTop = messageLog.scrollHeight;
        }
    }
    
    // Handle turn notification
    function handleTurnNotification(data) {
        // Update button states to enable actions
        updateButtonStates(data.your_turn);
        
        // Show turn message
        if (data.message) {
            elements.combatMessage.innerHTML = data.message;
            
            // Also update the opponent thinking message if it's not our turn
            if (!data.your_turn) {
                elements.opponentThinking.style.display = 'block';
                elements.opponentThinking.textContent = data.message;
            } else {
                elements.opponentThinking.style.display = 'none';
            }
        }
        
        // Play a sound or add some visual effect to get attention (optional)
        if (data.your_turn) {
            // Flash the message if it's our turn
            elements.combatMessage.style.color = "#ffff00";  // Yellow flash
            setTimeout(() => {
                elements.combatMessage.style.color = "#00ff00";  // Back to green
            }, 500);
        }
        
        // Update the combatants list to highlight the active player
        if (data.active_player && currentBattle.opponents) {
            // Update current turn indicators
            currentBattle.opponents.forEach(opponent => {
                opponent.is_current_turn = (opponent.id === data.active_player);
            });
            
            // Refresh the opponents list UI
            updateOpponentsList();
        }
    }
    
    // Process combat update
    function processCombatUpdate(data) {
        console.log("Combat update:", data);
        
        switch(data.type) {
            case 'combat_start':
                handleCombatStart(data);
                break;
            case 'target_request':
                handleTargetRequest(data);
                break;
            case 'combat_action':
                handleCombatAction(data);
                break;
            case 'monster_death':
                handleMonsterDeath(data);
                break;
            case 'player_death':
                handlePlayerDeath(data);
                break;
            case 'combat_end':
                handleCombatEnd(data);
                break;
            case 'turn_notification':
                handleTurnNotification(data);
                break;
        }
    }
    
    // Send combat action to server
    function sendAction(action) {
        if (window.socket) {
            window.socket.emit('combat_action', { 
                action: action,
                target_id: currentBattle.selectedTarget 
            });
        }
    }
    
    // Return public API
    return {
        processCombatUpdate,
        sendAction
    };
})();
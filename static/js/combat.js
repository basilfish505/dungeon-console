// combat.js - Handles combat interactions
const Combat = (function() {
    // Cache combat elements
    const elements = {
        combatBox: document.getElementById('combat-box'),
        opponentName: document.getElementById('opponent-name'),
        opponentHP: document.getElementById('opponent-hp'),
        combatMessage: document.getElementById('combat-message'),
        opponentThinking: document.getElementById('opponent-thinking'),
        attackBtn: document.getElementById('attack-btn'),
        defendBtn: document.getElementById('defend-btn'),
        spellBtn: document.getElementById('spell-btn'),
        itemBtn: document.getElementById('item-btn'),
        runBtn: document.getElementById('run-btn')
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
            elements.opponentThinking.textContent = "Your opponent weighs their next move...";
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
        elements.combatBox.style.display = 'block';
        elements.opponentName.textContent = data.opponent_id;
        elements.opponentHP.textContent = data.opponent_hp;
        
        // Set initial message based on turn
        elements.combatMessage.textContent = "";
        updateButtonStates(data.your_turn);
    }
    
    // Handle combat action
    function handleCombatAction(data) {
        // Update button states
        updateButtonStates(data.your_turn);
        
        // Clear previous messages
        elements.combatMessage.innerHTML = '';
        
        // Handle combat messages based on action and what happened
        if (data.blocked) {
            // This is for block results
            if (data.your_turn) {
                // You successfully blocked their attack
                elements.combatMessage.innerHTML = `You blocked ${data.opponent_id}'s attack with your skillful guard!`;
            } else {
                // Your attack was blocked
                elements.combatMessage.innerHTML = `Your blow was thwarted by ${data.opponent_id}'s skillful guard!`;
            }
        } 
        else if (data.action === 'defend' && !data.blocked) {
            // This is for taking defensive stance (not the result of a block)
            if (data.your_turn) {
                // You're now taking your turn after opponent defended
                if (data.previous_action === 'defend') {
                    elements.combatMessage.innerHTML = `${data.opponent_id} took a defensive stance.`;
                }
            } else {
                // You just took a defensive stance
                elements.combatMessage.innerHTML = "You took a defensive stance.";
            }
        }
        else if (data.damage_dealt) {
            // You dealt damage
            let message = `You dealt ${data.damage_dealt} damage to ${data.opponent_id}.`;
            
            // Add monster counter-attack message if applicable
            if (data.damage_taken && data.opponent_is_monster) {
                message += `<br><span class="monster-attack">The ${data.opponent_id} strikes back for ${data.damage_taken} damage!</span>`;
            }
            
            elements.combatMessage.innerHTML = message;
        } 
        else if (data.damage_taken) {
            // You took damage
            elements.combatMessage.innerHTML = `You took ${data.damage_taken} damage from ${data.opponent_id}.`;
        }
        
        // Update HP display if applicable
        if (data.opponent_hp) {
            elements.opponentHP.textContent = data.opponent_hp;
        }
        
        // Update player HP if provided (for monster attacks)
        if (data.your_hp) {
            const playerHP = document.getElementById('player-hp');
            if (playerHP) {
                playerHP.textContent = data.your_hp;
            }
        }
    }
    
    // Handle combat end
    function handleCombatEnd(data) {
        elements.combatBox.style.display = 'none';
        
        // Add the appropriate battle result message to message log
        if (data.message) {
            const messageLog = document.getElementById('message-log');
            messageLog.innerHTML += `<div>${data.message}</div>`;
            messageLog.scrollTop = messageLog.scrollHeight;
        }
    }
    
    // Process combat update
    function processCombatUpdate(data) {
        console.log("Combat update:", data);
        
        switch(data.type) {
            case 'combat_start':
                handleCombatStart(data);
                break;
            case 'combat_action':
                handleCombatAction(data);
                break;
            case 'combat_end':
                handleCombatEnd(data);
                break;
        }
    }
    
    // Send combat action to server
    function sendAction(action) {
        if (window.socket) {
            window.socket.emit('combat_action', { action: action });
        }
    }
    
    // Return public API
    return {
        processCombatUpdate,
        sendAction
    };
})();
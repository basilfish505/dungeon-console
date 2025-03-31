// socket.js - Socket event handlers
const SocketHandler = (function() {
    // Create socket connection
    const socket = io();
    
    // Handle socket events
    function setupSocketEvents() {
        // ID taken error
        socket.on('id_taken', function(data) {
            alert(data.message);
            document.getElementById('player-login').style.display = 'block';
        });
        
        // Game state update
        socket.on('game_state', function(data) {
            UI.updateMap(data.map);
            UI.updateMessages(data.messages);
            UI.updatePlayerProperties(data.player);
            UI.updateGameInfo(data.game_info);
        });
        
        // Combat update
        socket.on('combat_update', function(data) {
            Combat.processCombatUpdate(data);
        });
        
        // Player death
        socket.on('player_died', function() {
            UI.handlePlayerDeath();
            socket.disconnect();
        });
    }
    
    // Send player ID to server
    function selectPlayerId(playerId) {
        if (playerId) {
            // Store player ID in hidden input for combat targeting
            document.getElementById('player-id').value = playerId;
            socket.emit('select_id', playerId);
        }
    }
    
    // Send movement to server
    function sendMove(direction) {
        socket.emit('move', direction);
    }
    
    // Return public API
    return {
        socket,
        setupSocketEvents,
        selectPlayerId,
        sendMove
    };
})();
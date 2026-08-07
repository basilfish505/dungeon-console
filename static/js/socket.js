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
            const shell = document.getElementById('game-shell');
            if (shell) {
                shell.hidden = true;
            }
        });

        // Game state update
        socket.on('game_state', function(data) {
            UI.applyGameState(data);
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

    // Send player ID (and optional measured viewport) to server
    function selectPlayerId(playerId, viewport) {
        if (!playerId) {
            return;
        }
        document.getElementById('player-id').value = playerId;
        if (viewport && viewport.h && viewport.w) {
            socket.emit('select_id', {
                id: playerId,
                h: viewport.h | 0,
                w: viewport.w | 0,
            });
        } else {
            socket.emit('select_id', playerId);
        }
    }

    // Send movement to server
    function sendMove(direction) {
        socket.emit('move', direction);
    }

    function setViewport(h, w) {
        socket.emit('set_viewport', { h: h, w: w });
    }

    function panCamera(dy, dx) {
        if (!dy && !dx) {
            return;
        }
        socket.emit('pan_camera', { dy: dy | 0, dx: dx | 0 });
    }

    // Return public API
    return {
        socket,
        setupSocketEvents,
        selectPlayerId,
        sendMove,
        setViewport,
        panCamera
    };
})();

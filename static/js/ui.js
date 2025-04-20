// ui.js - Handles UI updates and display
const UI = (function() {
    // Cache DOM elements
    const elements = {
        loginForm: document.getElementById('player-login'),
        playerName: document.getElementById('player-name'),
        header: document.getElementById('header'),
        mapDisplay: document.getElementById('map-display'),
        mobileControls: document.querySelector('.mobile-controls'),
        messageLog: document.getElementById('message-log'),
        playerProperties: document.getElementById('player-properties'),
        gameInfo: document.getElementById('game-info').querySelector('.properties-grid'),
        combatBox: document.getElementById('combat-box')
    };
    
    // Hide all game elements initially
    function hideGameElements() {
        elements.header.style.display = 'none';
        elements.mapDisplay.style.display = 'none';
        elements.mobileControls.style.display = 'none';
        elements.messageLog.style.display = 'none';
        elements.playerProperties.style.display = 'none';
        elements.combatBox.style.display = 'none';
    }
    
    // Show game elements after login
    function showGameElements() {
        elements.loginForm.style.display = 'none';
        elements.header.style.display = 'block';
        elements.mapDisplay.style.display = 'block';
        elements.mobileControls.style.display = 'grid';
        elements.messageLog.style.display = 'block';
        elements.playerProperties.style.display = 'block';
    }
    
    // Update map display
    function updateMap(mapData) {
        if(mapData) {
            elements.mapDisplay.textContent = mapData.map(row => row.join('')).join('\n');
        }
    }
    
    // Update message log
    function updateMessages(messages) {
        if (messages && messages.length > 0) {
            elements.messageLog.innerHTML = messages.map(msg => `<div>${msg}</div>`).join('');
            elements.messageLog.scrollTop = elements.messageLog.scrollHeight;
        }
    }
    
    // Update player properties
    function updatePlayerProperties(player) {
        if (player) {
            document.getElementById('player-name-display').textContent = player.id;
            document.getElementById('player-level').textContent = player.level;
            document.getElementById('player-xp').textContent = player.xp;
            document.getElementById('player-str').textContent = player.str;
            document.getElementById('player-int').textContent = player.int;
            document.getElementById('player-wis').textContent = player.wis;
            document.getElementById('player-chr').textContent = player.chr;
            document.getElementById('player-dex').textContent = player.dex;
            document.getElementById('player-hp').textContent = player.hp;
            document.getElementById('player-mp').textContent = player.mp;
            document.getElementById('player-agi').textContent = player.agi;
        }
    }
    
    // Update game info display
    function updateGameInfo(gameInfo) {
        if (gameInfo) {
            elements.gameInfo.innerHTML = '';
            gameInfo.forEach(row => {
                row.forEach(cell => {
                    const span = document.createElement('span');
                    span.className = 'property-value';
                    span.textContent = cell;
                    elements.gameInfo.appendChild(span);
                });
            });
        }
    }
    
    // Handle player death
    function handlePlayerDeath() {
        elements.combatBox.style.display = 'none';
        elements.mapDisplay.textContent = '';
        elements.playerProperties.style.display = 'none';
        elements.mobileControls.style.display = 'none';
        elements.loginForm.style.display = 'none';
        elements.messageLog.innerHTML = '<div>Thou art dead.</div>';
    }
    
    // Return public API
    return {
        elements,
        hideGameElements,
        showGameElements,
        updateMap,
        updateMessages,
        updatePlayerProperties,
        updateGameInfo,
        handlePlayerDeath
    };
})();
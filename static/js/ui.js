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

    // Undo mobile browser zoom left over from focusing the name field
    function resetMobileViewport() {
        const meta = document.querySelector('meta[name="viewport"]');
        if (!meta) {
            return;
        }
        const locked = 'width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover';
        meta.setAttribute('content', locked);
        // Bounce content so WebKit reapplies scale after the keyboard/input zoom
        meta.setAttribute('content', 'width=device-width, initial-scale=0.99, maximum-scale=1, viewport-fit=cover');
        setTimeout(function () {
            meta.setAttribute('content', locked);
        }, 50);
    }

    // Scale the 20x20 ASCII map so it fits the phone width
    function fitMapToScreen() {
        const el = elements.mapDisplay;
        if (!el || el.style.display === 'none') {
            return;
        }
        const available = Math.max(0, window.innerWidth - 24);
        if (available <= 0) {
            return;
        }
        el.style.fontSize = '100px';
        const widthAt100 = el.offsetWidth;
        if (widthAt100 <= 0) {
            el.style.fontSize = '';
            return;
        }
        const size = Math.max(7, Math.min(16, 100 * (available / widthAt100)));
        el.style.fontSize = size + 'px';
    }

    function layoutForMobile() {
        resetMobileViewport();
        fitMapToScreen();
        // Refit after keyboard dismissal / visual viewport settle
        setTimeout(fitMapToScreen, 100);
        setTimeout(fitMapToScreen, 300);
    }

    // Show game elements after login
    function showGameElements() {
        if (elements.playerName) {
            elements.playerName.blur();
        }
        if (document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
        elements.loginForm.style.display = 'none';
        elements.header.style.display = 'block';
        elements.mapDisplay.style.display = 'block';
        elements.mobileControls.style.display = 'grid';
        elements.messageLog.style.display = 'block';
        elements.playerProperties.style.display = 'block';
        layoutForMobile();
    }
    
    // Update map display (optional fog grid for LOS coloring)
    function updateMap(mapData, fogData) {
        if (!mapData) {
            return;
        }
        if (!fogData) {
            elements.mapDisplay.textContent = mapData.map(row => row.join('')).join('\n');
            return;
        }
        const parts = [];
        for (let y = 0; y < mapData.length; y++) {
            if (y > 0) {
                parts.push('\n');
            }
            const row = mapData[y];
            const fogRow = fogData[y] || [];
            for (let x = 0; x < row.length; x++) {
                const state = fogRow[x] || 'visible';
                const cls = state === 'explored' ? 'fog-explored'
                    : state === 'unexplored' ? 'fog-unexplored'
                    : 'fog-visible';
                const ch = row[x] === ' ' ? '\u00a0' : row[x];
                parts.push(`<span class="${cls}">${escapeHtml(ch)}</span>`);
            }
        }
        elements.mapDisplay.innerHTML = parts.join('');
    }

    function escapeHtml(ch) {
        if (ch === '&') return '&amp;';
        if (ch === '<') return '&lt;';
        if (ch === '>') return '&gt;';
        return ch;
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
        handlePlayerDeath,
        fitMapToScreen,
        layoutForMobile
    };
})();
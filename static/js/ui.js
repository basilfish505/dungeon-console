// ui.js - Handles UI updates and display
const UI = (function() {
    // Cache DOM elements
    const elements = {
        loginForm: document.getElementById('player-login'),
        playerName: document.getElementById('player-name'),
        gameShell: document.getElementById('game-shell'),
        header: document.getElementById('header'),
        mapPane: document.getElementById('map-pane'),
        mapDisplay: document.getElementById('map-display'),
        mobileControls: document.getElementById('mobile-controls') || document.querySelector('.mobile-controls'),
        messageLog: document.getElementById('message-log'),
        playerProperties: document.getElementById('player-properties'),
        gameInfo: document.getElementById('game-info').querySelector('.properties-grid'),
        combatBox: document.getElementById('combat-overlay')
    };

    let mapSystemReady = false;
    let ignoreResizeUntil = 0;

    // Hide all game elements initially
    function hideGameElements() {
        if (elements.gameShell) {
            elements.gameShell.hidden = true;
        }
        if (elements.mobileControls) {
            elements.mobileControls.style.display = 'none';
        }
        if (elements.combatBox) {
            elements.combatBox.hidden = true;
            elements.combatBox.setAttribute('aria-hidden', 'true');
            elements.combatBox.style.display = 'none';
        }
    }

    // Undo mobile browser zoom left over from focusing the name field
    function resetMobileViewport() {
        const meta = document.querySelector('meta[name="viewport"]');
        if (!meta) {
            return;
        }
        const locked = 'width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover';
        meta.setAttribute('content', locked);
    }

    function initMapSystem() {
        if (mapSystemReady) {
            return;
        }
        MapView.init({
            paneEl: elements.mapPane,
            displayEl: elements.mapDisplay,
            emitViewport: function (size) {
                SocketHandler.setViewport(size.h, size.w, size.camera);
            },
            emitPan: function (delta) {
                SocketHandler.panCamera(delta.dy, delta.dx);
            },
        });
        MapGestures.init({ paneEl: elements.mapPane });

        if (typeof ResizeObserver !== 'undefined' && elements.mapPane) {
            const ro = new ResizeObserver(function () {
                if (Date.now() < ignoreResizeUntil) {
                    return;
                }
                MapView.requestMapUpdate('resize');
            });
            ro.observe(elements.mapPane);
        }

        mapSystemReady = true;
    }

    function layoutForMobile() {
        resetMobileViewport();
        if (mapSystemReady && Date.now() >= ignoreResizeUntil) {
            MapView.requestMapUpdate('layout');
        }
    }

    /**
     * Reveal the game UI, measure the map pane, and return {h,w} for select_id.
     * Call this before joining so the first game_state already has the real size.
     */
    function prepareJoinViewport() {
        if (elements.playerName) {
            elements.playerName.blur();
        }
        if (document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
        resetMobileViewport();
        elements.loginForm.style.display = 'none';
        if (elements.gameShell) {
            elements.gameShell.hidden = false;
        }
        if (elements.mobileControls) {
            elements.mobileControls.style.display = 'grid';
        }
        initMapSystem();
        // Ignore keyboard/layout resize noise right after join
        ignoreResizeUntil = Date.now() + 500;
        // Force layout, then measure once
        if (elements.gameShell) {
            void elements.gameShell.offsetHeight;
        }
        if (elements.mapPane) {
            void elements.mapPane.offsetHeight;
        }
        let viewport = MapView.measureViewportNow();
        if (!viewport && elements.mapPane) {
            void elements.mapPane.offsetWidth;
            viewport = MapView.measureViewportNow();
        }
        return viewport;
    }

    // Show game elements after login (legacy path without pre-measure)
    function showGameElements() {
        prepareJoinViewport();
    }

    // Update map display via MapView + MapRenderer
    function updateMap(mapData, fogData) {
        // Legacy entry point — prefer ingestGameState from socket
        if (!mapData) {
            return;
        }
        MapView.ingestGameState({ map: mapData, fog: fogData });
    }

    function applyGameState(data) {
        MapView.ingestGameState(data);
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
            document.getElementById('player-elo').textContent =
                player.elo != null ? Math.round(Number(player.elo)) : 0;
            document.getElementById('player-xp').textContent = player.total_xp ?? player.xp ?? 0;
            document.getElementById('player-pqg').textContent = player.pqg ?? 0;
            document.getElementById('player-str').textContent = player.str;
            document.getElementById('player-int').textContent = player.int;
            document.getElementById('player-wis').textContent = player.wis;
            document.getElementById('player-chr').textContent = player.chr;
            document.getElementById('player-dex').textContent = player.dex;
            document.getElementById('player-hp').textContent = player.hp;
            document.getElementById('player-mp').textContent = player.mp;
            document.getElementById('player-agi').textContent = player.agi;
            document.getElementById('player-acc').textContent = player.acc ?? player.accuracy ?? '-';
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

    function showLoginScreen() {
        if (elements.combatBox) {
            elements.combatBox.hidden = true;
            elements.combatBox.setAttribute('aria-hidden', 'true');
            elements.combatBox.style.display = 'none';
        }
        if (typeof MapRenderer !== 'undefined' && MapRenderer.clearCanvas) {
            MapRenderer.clearCanvas();
        }
        if (elements.mobileControls) {
            elements.mobileControls.style.display = 'none';
        }
        if (elements.gameShell) {
            elements.gameShell.hidden = true;
        }
        if (elements.messageLog) {
            elements.messageLog.innerHTML = '';
        }
        elements.loginForm.style.display = 'flex';
    }

    // Handle player death
    function handlePlayerDeath() {
        if (elements.combatBox) {
            elements.combatBox.hidden = true;
            elements.combatBox.setAttribute('aria-hidden', 'true');
            elements.combatBox.style.display = 'none';
        }
        if (typeof MapRenderer !== 'undefined' && MapRenderer.clearCanvas) {
            MapRenderer.clearCanvas();
        } else if (elements.mapDisplay) {
            elements.mapDisplay.textContent = '';
        }
        if (elements.mobileControls) {
            elements.mobileControls.style.display = 'none';
        }
        elements.loginForm.style.display = 'none';
        if (elements.gameShell) {
            elements.gameShell.hidden = false;
        }
        elements.messageLog.innerHTML = '<div>Thou art dead.</div>';
    }

    // Return public API
    return {
        elements,
        hideGameElements,
        showGameElements,
        prepareJoinViewport,
        updateMap,
        applyGameState,
        updateMessages,
        updatePlayerProperties,
        updateGameInfo,
        handlePlayerDeath,
        showLoginScreen,
        layoutForMobile,
        requestMapUpdate: function (reason) {
            if (mapSystemReady && Date.now() >= ignoreResizeUntil) {
                MapView.requestMapUpdate(reason);
            }
        }
    };
})();

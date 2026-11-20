// ui.js - Handles UI updates and display
const UI = (function() {
    // Cache DOM elements
    const elements = {
        loginForm: document.getElementById('entry-screen'),
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
    let lastKnownLevel = null;

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

    // Undo mobile browser zoom left over from focusing an entry field
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
        if (document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
        resetMobileViewport();
        if (elements.loginForm) {
            elements.loginForm.style.display = 'none';
        }
        if (elements.gameShell) {
            elements.gameShell.hidden = false;
        }
        if (elements.mobileControls) {
            elements.mobileControls.style.display = 'grid';
        }
        initMapSystem();
        // Ignore keyboard/layout resize noise right after join
        ignoreResizeUntil = Date.now() + 500;
        lastKnownLevel = null;
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
            const level = player.level | 0;
            if (lastKnownLevel !== null && level > lastKnownLevel
                && typeof Sound !== 'undefined') {
                Sound.play('levelUp');
            }
            lastKnownLevel = level;
            document.getElementById('player-name-display').textContent = player.id;
            document.getElementById('player-level').textContent = level;
            document.getElementById('player-elo').textContent =
                player.elo != null ? Math.round(Number(player.elo)) : 0;
            const xpProgress = player.xp_progress || {};
            const currentXp = xpProgress.xp_progress_this_level;
            const xpNeeded = xpProgress.xp_required_for_next_level;
            if (currentXp != null && xpNeeded != null) {
                document.getElementById('player-xp').textContent = `${currentXp} / ${xpNeeded}`;
            } else {
                document.getElementById('player-xp').textContent = player.total_xp ?? player.xp ?? 0;
            }
            document.getElementById('player-pqg').textContent = player.pqg ?? 0;
            // Permanent value in its own column; worn-gear boost (e.g. "(+5)")
            // in a separate column to its right. Stat totals include the boost.
            const gearBonus = player.attribute_bonus || {};
            const setAttr = function (key, total) {
                const bonus = Number(gearBonus[key]) || 0;
                const numeric = Number(total);
                document.getElementById('player-' + key).textContent =
                    (bonus && !Number.isNaN(numeric)) ? numeric - bonus : total;
                document.getElementById('player-' + key + '-bonus').textContent =
                    bonus ? '(' + (bonus > 0 ? '+' : '') + bonus + ')' : '';
            };
            setAttr('str', player.str);
            setAttr('int', player.int);
            setAttr('wis', player.wis);
            setAttr('chr', player.chr);
            setAttr('dex', player.dex);
            document.getElementById('player-hp').textContent = player.hp;
            document.getElementById('player-mp').textContent = player.mp;
            setAttr('agi', player.agi);
            setAttr('acc', player.acc ?? player.accuracy ?? '-');
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
        lastKnownLevel = null;
        if (elements.loginForm) {
            elements.loginForm.style.display = 'flex';
        }
        if (typeof Entry !== 'undefined' && Entry.showChoice) {
            Entry.showChoice();
        }
    }

    /** Ignore key presses right after death so mashing movement keys cannot skip it. */
    const DEATH_ARM_DELAY_MS = 700;
    const MODIFIER_KEYS = ['Shift', 'Control', 'Alt', 'Meta', 'AltGraph', 'CapsLock'];
    let deathScreenActive = false;

    /** Close every battle/menu overlay so none of them blocks the next character. */
    function closeOverlaysForDeath() {
        const closers = [
            function () { Combat.resetAfterDeath(); },
            function () { InspectUI.hide(); },
            function () { InspectUI.hideAlert(); },
            function () { InventoryUI.hide(); },
            function () { InteractionUI.hide(); },
            function () { LootUI.reset(); },
            function () { ChestUI.reset(); },
        ];
        closers.forEach(function (close) {
            try {
                close();
            } catch (err) {
                /* module missing or nothing open */
            }
        });
    }

    /**
     * Player died (or tried to load a dead character): show "Thou art dead" and
     * wait for any key / tap, then go back to the new / returning character screen.
     * onContinue runs just before the entry screen is shown.
     */
    function handlePlayerDeath(deathInfo, onContinue) {
        if (deathScreenActive) {
            return;
        }
        const screen = document.getElementById('death-screen');
        if (!screen) {
            if (typeof onContinue === 'function') {
                onContinue();
            }
            showLoginScreen();
            return;
        }
        deathScreenActive = true;

        closeOverlaysForDeath();
        if (typeof MapRenderer !== 'undefined' && MapRenderer.clearCanvas) {
            MapRenderer.clearCanvas();
        } else if (elements.mapDisplay) {
            elements.mapDisplay.textContent = '';
        }
        if (elements.mobileControls) {
            elements.mobileControls.style.display = 'none';
        }
        if (elements.loginForm) {
            elements.loginForm.style.display = 'none';
        }

        const detail = document.getElementById('death-detail');
        if (detail) {
            const killer = deathInfo && deathInfo.killer_name;
            detail.textContent = killer ? 'Slain by ' + killer + '.' : '';
        }
        screen.hidden = false;
        screen.setAttribute('aria-hidden', 'false');
        if (typeof screen.focus === 'function') {
            screen.focus({ preventScroll: true });
        }

        const armedAt = Date.now() + DEATH_ARM_DELAY_MS;

        function onKeyDown(e) {
            // Always swallow keys so nothing underneath reacts (movement, etc.)
            if (e.ctrlKey || e.metaKey || e.altKey) {
                return; // browser shortcuts (refresh, dev tools) still work
            }
            e.preventDefault();
            e.stopImmediatePropagation();
            if (e.repeat || MODIFIER_KEYS.indexOf(e.key) !== -1) {
                return;
            }
            if (Date.now() < armedAt) {
                return;
            }
            dismiss();
        }

        function onClick(e) {
            e.preventDefault();
            if (Date.now() < armedAt) {
                return;
            }
            dismiss();
        }

        function dismiss() {
            if (!deathScreenActive) {
                return;
            }
            deathScreenActive = false;
            document.removeEventListener('keydown', onKeyDown, true);
            screen.removeEventListener('click', onClick);
            screen.hidden = true;
            screen.setAttribute('aria-hidden', 'true');
            if (typeof onContinue === 'function') {
                onContinue();
            }
            showLoginScreen();
        }

        document.addEventListener('keydown', onKeyDown, true);
        screen.addEventListener('click', onClick);
    }

    // Return public API
    return {
        elements,
        hideGameElements,
        prepareJoinViewport,
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

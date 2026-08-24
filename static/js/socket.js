// socket.js - Socket event handlers + reconnect resume
const SocketHandler = (function () {
    const socket = io({
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: Infinity,
        reconnectionDelay: 500,
        reconnectionDelayMax: 5000,
    });

    let joinedPlayerId = null;
    let resumeInFlight = false;
    let idTakenRetries = 0;
    /** World this tab joined. A new server process has a different id. */
    let knownBootId = null;

    function currentViewport() {
        if (typeof MapView !== 'undefined' && MapView.measureViewportNow) {
            return MapView.measureViewportNow();
        }
        return null;
    }

    function getJoinedPlayerId() {
        if (joinedPlayerId) {
            return joinedPlayerId;
        }
        const el = document.getElementById('player-id');
        const v = el && el.value ? el.value.trim() : '';
        return v || null;
    }

    function clearJoinedSession() {
        joinedPlayerId = null;
        resumeInFlight = false;
        idTakenRetries = 0;
        const el = document.getElementById('player-id');
        if (el) {
            el.value = '';
        }
    }

    function handleWorldReset(newBootId) {
        clearJoinedSession();
        knownBootId = newBootId || null;
        if (typeof UI !== 'undefined' && UI.showLoginScreen) {
            UI.showLoginScreen();
        } else {
            document.getElementById('player-login').style.display = 'block';
            const shell = document.getElementById('game-shell');
            if (shell) {
                shell.hidden = true;
            }
        }
    }

    /** Re-bind server session after mobile background / socket drop. */
    function tryResumeSession() {
        const playerId = getJoinedPlayerId();
        if (!playerId || !socket.connected || !knownBootId) {
            return;
        }
        if (resumeInFlight) {
            return;
        }
        resumeInFlight = true;
        const viewport = currentViewport();
        selectPlayerId(playerId, viewport);
        // Allow another resume shortly (e.g. visibility after connect)
        setTimeout(function () {
            resumeInFlight = false;
        }, 750);
    }

    function setupSocketEvents() {
        socket.on('server_hello', function (data) {
            const boot = data && data.boot_id ? String(data.boot_id) : '';
            if (!boot) {
                return;
            }
            if (knownBootId && boot !== knownBootId) {
                handleWorldReset(boot);
                return;
            }
            if (!knownBootId) {
                knownBootId = boot;
            }
            // Same world after a drop — reclaim the character
            if (getJoinedPlayerId()) {
                tryResumeSession();
            }
        });

        socket.on('world_reset', function (data) {
            const boot = data && data.boot_id ? String(data.boot_id) : '';
            handleWorldReset(boot || knownBootId);
        });

        socket.on('id_taken', function (data) {
            // Brief race after reconnect: retry a couple times, then give up
            if (joinedPlayerId && idTakenRetries < 2) {
                idTakenRetries += 1;
                setTimeout(tryResumeSession, 400);
                return;
            }
            clearJoinedSession();
            alert((data && data.message) || 'That name is currently in use!');
            document.getElementById('player-login').style.display = 'block';
            const shell = document.getElementById('game-shell');
            if (shell) {
                shell.hidden = true;
            }
        });

        socket.on('game_state', function (data) {
            const boot = data && data.boot_id ? String(data.boot_id) : '';
            if (boot && knownBootId && boot !== knownBootId) {
                handleWorldReset(boot);
                return;
            }
            if (boot && !knownBootId) {
                knownBootId = boot;
            }
            // Ignore spectator/level-0 payloads while logged in (reconnect flash)
            if (getJoinedPlayerId() && (!data || !data.player)) {
                tryResumeSession();
                return;
            }
            if (data && data.player && data.player.id) {
                idTakenRetries = 0;
                if (boot) {
                    knownBootId = boot;
                }
            }
            UI.applyGameState(data);
            UI.updateMessages(data.messages);
            UI.updatePlayerProperties(data.player);
            UI.updateGameInfo(data.game_info);
            if (typeof InventoryUI !== 'undefined' && InventoryUI.setInventory) {
                InventoryUI.setInventory(data.player && data.player.inventory);
            }
        });

        socket.on('combat_update', function (data) {
            Combat.processCombatUpdate(data);
        });

        socket.on('inspect_result', function (data) {
            if (typeof InspectUI !== 'undefined' && InspectUI.show) {
                InspectUI.show(data);
            }
        });

        socket.on('buy_item_result', function (data) {
            if (data && data.message && typeof InspectUI !== 'undefined' && InspectUI.showAlert) {
                InspectUI.showAlert(data.message);
            }
        });

        socket.on('player_died', function () {
            clearJoinedSession();
            UI.handlePlayerDeath();
            socket.disconnect();
        });

        socket.on('character_dead', function (data) {
            clearJoinedSession();
            UI.handlePlayerDeath(data);
            if (typeof UI !== 'undefined' && UI.showLoginScreen) {
                setTimeout(function () {
                    UI.showLoginScreen();
                }, 4000);
            }
        });

        document.addEventListener('visibilitychange', function () {
            if (!document.hidden && getJoinedPlayerId()) {
                tryResumeSession();
            }
        });

        window.addEventListener('pageshow', function (e) {
            if (e.persisted && getJoinedPlayerId()) {
                tryResumeSession();
            }
        });
    }

    function selectPlayerId(playerId, viewport) {
        if (!playerId) {
            return;
        }
        if (!knownBootId) {
            return;
        }
        joinedPlayerId = playerId;
        document.getElementById('player-id').value = playerId;
        const payload = {
            id: playerId,
            boot_id: knownBootId,
        };
        if (viewport && viewport.h && viewport.w) {
            payload.h = viewport.h | 0;
            payload.w = viewport.w | 0;
        }
        socket.emit('select_id', payload);
    }

    function sendMove(direction) {
        socket.emit('move', direction);
    }

    function setViewport(h, w, camera) {
        const payload = { h: h, w: w };
        if (camera && Number.isFinite(camera.y) && Number.isFinite(camera.x)) {
            payload.cam_y = camera.y | 0;
            payload.cam_x = camera.x | 0;
        }
        socket.emit('set_viewport', payload);
    }

    function panCamera(dy, dx) {
        if (!dy && !dx) {
            return;
        }
        socket.emit('pan_camera', { dy: dy | 0, dx: dx | 0 });
    }

    function inspectMap(y, x) {
        socket.emit('inspect_map', { y: y | 0, x: x | 0 });
    }

    function inspectCombatant(targetId) {
        if (!targetId) {
            return;
        }
        socket.emit('inspect_combatant', { target_id: targetId });
    }

    function buyItem(itemId) {
        if (!itemId) {
            return;
        }
        socket.emit('buy_item', { item_id: itemId });
    }

    return {
        socket,
        setupSocketEvents,
        selectPlayerId,
        sendMove,
        setViewport,
        panCamera,
        inspectMap,
        inspectCombatant,
        buyItem,
        tryResumeSession,
        getJoinedPlayerId,
        clearJoinedSession,
    };
})();

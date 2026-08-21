// movement_controller.js — single hold-to-move input + paced emit loop
const MovementController = (function () {
    const KEY_TO_CARDINAL = {
        w: 'n', a: 'west', s: 's', d: 'e',
        ArrowUp: 'n', ArrowLeft: 'west', ArrowDown: 's', ArrowRight: 'e',
    };
    const CARDINALS = { n: true, e: true, s: true, west: true };
    const DELTA_TO_DIR = {
        '-1,0': 'n',
        '-1,1': 'ne',
        '0,1': 'e',
        '1,1': 'se',
        '1,0': 's',
        '1,-1': 'sw',
        '0,-1': 'west',
        '-1,-1': 'nw',
    };
    const DIR_DELTA = {
        n: [-1, 0], ne: [-1, 1], e: [0, 1], se: [1, 1],
        s: [1, 0], sw: [1, -1], west: [0, -1], nw: [-1, -1],
    };

    /** Most-recently-pressed held direction is last. */
    const heldDirs = [];
    /** Exclusive map-swipe direction (not mixed with pad/keyboard holds). */
    let stickDir = null;
    let holdRafId = null;
    let nextEmitAt = 0;
    let bound = false;

    function stepMs() {
        if (typeof PlayerPresentation !== 'undefined' && PlayerPresentation.MOVE_MS) {
            return PlayerPresentation.MOVE_MS;
        }
        return 250;
    }

    function pipelineT() {
        if (typeof PlayerPresentation !== 'undefined' && PlayerPresentation.PIPELINE_T != null) {
            return PlayerPresentation.PIPELINE_T;
        }
        return 0.9;
    }

    function combineHeld() {
        let dy = 0;
        let dx = 0;
        let hasCardinal = false;
        let lastDiagonal = null;
        for (let i = 0; i < heldDirs.length; i++) {
            const dir = heldDirs[i];
            if (CARDINALS[dir]) {
                hasCardinal = true;
                const d = DIR_DELTA[dir];
                dy += d[0];
                dx += d[1];
            } else if (DIR_DELTA[dir]) {
                lastDiagonal = dir;
            }
        }
        if (hasCardinal) {
            dy = dy < 0 ? -1 : (dy > 0 ? 1 : 0);
            dx = dx < 0 ? -1 : (dx > 0 ? 1 : 0);
            return DELTA_TO_DIR[dy + ',' + dx] || null;
        }
        return lastDiagonal;
    }

    function currentDir() {
        return combineHeld();
    }

    function localPlayerId() {
        const el = document.getElementById('player-id');
        return el && el.value ? el.value : '';
    }

    function viewportChar(y, x) {
        if (typeof MapView === 'undefined' || !MapView.getState) {
            return null;
        }
        const st = MapView.getState();
        const map = st.lastMap;
        if (!map || !map.length) {
            return null;
        }
        const originY = Number.isFinite(st.mapOriginY) ? (st.mapOriginY | 0) : (st.cameraY | 0);
        const originX = Number.isFinite(st.mapOriginX) ? (st.mapOriginX | 0) : (st.cameraX | 0);
        const vy = y - originY;
        const vx = x - originX;
        if (vy < 0 || vx < 0 || vy >= map.length) {
            return null;
        }
        const row = map[vy];
        if (!row || vx >= row.length) {
            return null;
        }
        return row[vx];
    }

    function entityKindAt(worldY, worldX) {
        if (typeof MapView === 'undefined' || !MapView.getState) {
            return null;
        }
        const st = MapView.getState();
        const ents = st.lastEntities || [];
        const camY = Number.isFinite(st.mapOriginY) ? (st.mapOriginY | 0) : (st.cameraY | 0);
        const camX = Number.isFinite(st.mapOriginX) ? (st.mapOriginX | 0) : (st.cameraX | 0);
        for (let i = 0; i < ents.length; i++) {
            const e = ents[i];
            if (!e) {
                continue;
            }
            if (camY + (e.vy | 0) === worldY && camX + (e.vx | 0) === worldX) {
                return e.kind || null;
            }
        }
        return null;
    }

    function isSolidTerrain(ch) {
        // Match server IMPASSABLE_TERRAIN plus void.
        return ch === '#' || ch === ' ' || ch === 'R' || ch === '=' || ch === 'T' || ch === 'M' || ch === 'W';
    }

    function isOpenFloor(ch) {
        // Walkable for client prediction. Stairs omitted so we do not
        // predict across a floor change.
        return ch != null && !isSolidTerrain(ch) && ch !== '&' && ch !== '@'
            && ch !== '\u2191' && ch !== '\u2193';
    }

    function canAttemptStep(fromY, fromX, toY, toX) {
        const dest = viewportChar(toY, toX);
        const kind = entityKindAt(toY, toX);
        // Bumps that must reach the server: desk talk, NPC/monster/player combat.
        if (dest === '=' || dest === '&' || dest === '@'
            || kind === 'npc' || kind === 'monster' || kind === 'player') {
            return true;
        }
        if (dest == null || isSolidTerrain(dest)) {
            return false;
        }
        const dy = toY - fromY;
        const dx = toX - fromX;
        if (dy !== 0 && dx !== 0) {
            if (isSolidTerrain(viewportChar(fromY + dy, fromX))
                || isSolidTerrain(viewportChar(fromY, fromX + dx))) {
                return false;
            }
        }
        return true;
    }

    function canPredictStep(fromY, fromX, toY, toX) {
        const kind = entityKindAt(toY, toX);
        if (kind === 'npc' || kind === 'monster' || kind === 'player') {
            return false;
        }
        if (!isOpenFloor(viewportChar(toY, toX))) {
            return false;
        }
        const dy = toY - fromY;
        const dx = toX - fromX;
        if (dy !== 0 && dx !== 0) {
            if (!isOpenFloor(viewportChar(fromY + dy, fromX))
                || !isOpenFloor(viewportChar(fromY, fromX + dx))) {
                return false;
            }
        }
        return true;
    }

    function localStepBlocked(direction) {
        const delta = DIR_DELTA[direction];
        if (!delta || typeof PlayerPresentation === 'undefined'
            || !PlayerPresentation.tilePos) {
            return false;
        }
        const tile = PlayerPresentation.tilePos(localPlayerId());
        if (!tile) {
            return false;
        }
        return !canAttemptStep(
            tile.y, tile.x, tile.y + delta[0], tile.x + delta[1]
        );
    }

    function predictStep(direction) {
        const delta = DIR_DELTA[direction];
        if (!delta || typeof PlayerPresentation === 'undefined'
            || !PlayerPresentation.predictLocalStep) {
            return;
        }
        const id = localPlayerId();
        if (!id) {
            return;
        }
        const tile = PlayerPresentation.tilePos ? PlayerPresentation.tilePos(id) : null;
        if (!tile) {
            return;
        }
        const fromY = tile.y;
        const fromX = tile.x;
        const toY = fromY + delta[0];
        const toX = fromX + delta[1];
        if (!canPredictStep(fromY, fromX, toY, toX)) {
            return;
        }
        PlayerPresentation.predictLocalStep(id, delta[0], delta[1]);
    }

    /**
     * @param {boolean} force  true on fresh press (ignore STEP_MS floor)
     */
    function tryEmit(force) {
        const direction = currentDir();
        if (!direction) {
            return false;
        }
        if (typeof InspectUI !== 'undefined' && InspectUI.isOpen()) {
            return false;
        }
        if (typeof InventoryUI !== 'undefined' && InventoryUI.isOpen()) {
            return false;
        }
        const now = performance.now();
        if (!force && now < nextEmitAt) {
            return false;
        }
        if (localStepBlocked(direction)) {
            return false;
        }

        if (typeof PlayerPresentation !== 'undefined' && PlayerPresentation.beginLocalStep) {
            const id = localPlayerId();
            const t = PlayerPresentation.progress ? PlayerPresentation.progress(id) : 0;
            const opts = (t >= pipelineT()) ? { pipeline: true } : {};
            if (!PlayerPresentation.beginLocalStep(id, opts)) {
                return false;
            }
        }

        if (typeof SocketHandler === 'undefined' || !SocketHandler.sendMove) {
            return false;
        }
        SocketHandler.sendMove(direction);
        predictStep(direction);
        nextEmitAt = now + stepMs();
        return true;
    }

    function startHoldLoop() {
        if (holdRafId !== null) {
            return;
        }
        holdRafId = requestAnimationFrame(function tick() {
            holdRafId = null;
            if (!currentDir()) {
                return;
            }
            tryEmit(false);
            holdRafId = requestAnimationFrame(tick);
        });
    }

    function pressDir(dir) {
        if (!dir || !DIR_DELTA[dir]) {
            return;
        }
        const i = heldDirs.indexOf(dir);
        if (i >= 0) {
            heldDirs.splice(i, 1);
        }
        heldDirs.push(dir);
        tryEmit(true);
        startHoldLoop();
    }

    function releaseDir(dir) {
        const i = heldDirs.indexOf(dir);
        if (i >= 0) {
            heldDirs.splice(i, 1);
        }
    }

    function clearHeld() {
        heldDirs.length = 0;
        stickDir = null;
    }

    /**
     * Exclusive virtual-stick direction for map swipe.
     * Passing the same dir is a no-op (avoids re-emitting every pointermove).
     */
    function setStickDir(dir) {
        if (!dir || !DIR_DELTA[dir]) {
            if (stickDir) {
                releaseDir(stickDir);
                stickDir = null;
            }
            return;
        }
        if (dir === stickDir) {
            return;
        }
        if (stickDir) {
            releaseDir(stickDir);
        }
        stickDir = dir;
        pressDir(dir);
    }

    function bind() {
        if (bound) {
            return;
        }
        bound = true;

        document.addEventListener('keydown', function (e) {
            if (typeof InspectUI !== 'undefined' && InspectUI.isOpen()) {
                if (e.key === 'Escape') {
                    InspectUI.hide();
                }
                return;
            }
            if (typeof InventoryUI !== 'undefined' && InventoryUI.isOpen()) {
                if (e.key === 'Escape') {
                    if (InventoryUI.handleEscape) {
                        InventoryUI.handleEscape();
                    } else {
                        InventoryUI.hide();
                    }
                }
                return;
            }
            const dir = KEY_TO_CARDINAL[e.key];
            if (!dir) {
                return;
            }
            e.preventDefault();
            if (e.repeat) {
                return;
            }
            pressDir(dir);
        });

        document.addEventListener('keyup', function (e) {
            const dir = KEY_TO_CARDINAL[e.key];
            if (dir) {
                releaseDir(dir);
            }
        });

        window.addEventListener('blur', clearHeld);
        document.addEventListener('visibilitychange', function () {
            if (document.hidden) {
                clearHeld();
            }
        });

        document.querySelectorAll('.mobile-btn').forEach(function (btn) {
            const direction = btn.getAttribute('data-direction');
            if (!direction) {
                return;
            }
            btn.addEventListener('pointerdown', function (e) {
                e.preventDefault();
                if (typeof InspectUI !== 'undefined' && InspectUI.isOpen()) {
                    return;
                }
                if (typeof InventoryUI !== 'undefined' && InventoryUI.isOpen()) {
                    return;
                }
                if (btn.setPointerCapture && e.pointerId != null) {
                    try {
                        btn.setPointerCapture(e.pointerId);
                    } catch (err) { /* ignore */ }
                }
                pressDir(direction);
            });
            const up = function (e) {
                e.preventDefault();
                releaseDir(direction);
            };
            btn.addEventListener('pointerup', up);
            btn.addEventListener('pointercancel', up);
            btn.addEventListener('lostpointercapture', up);
        });
    }

    return {
        bind: bind,
        pressDir: pressDir,
        releaseDir: releaseDir,
        setStickDir: setStickDir,
        clearHeld: clearHeld,
        currentDir: currentDir,
    };
})();

// map_view.js — authoritative client map viewport state + RAF update pipeline
const MapView = (function () {
    // Zoom = tiles across the shorter pane axis. Longer axis shows more tiles.
    const ZOOM_SPANS = [40, 36, 32, 28, 24, 20, 16, 14, 12, 10, 5];
    const DEFAULT_ZOOM_INDEX = 5; // 20×20 — matches camera.DEFAULT_VIEW_SPAN
    const MARGIN_REF_SPAN = 20; // matches camera.DEFAULT_VIEW_SPAN
    const EDGE_MARGIN_REF = 4; // matches camera.EDGE_MARGIN at default span
    // Keep payload size bounded (mirrors camera.MAX_VIEWPORT and ~3200 cells).
    const MAX_VIEWPORT_AXIS = 120;
    const MAX_VIEWPORT_CELLS = 3200;

    const state = {
        zoomIndex: DEFAULT_ZOOM_INDEX,
        tileW: 1,
        tileH: 1,
        visibleCols: ZOOM_SPANS[DEFAULT_ZOOM_INDEX],
        visibleRows: ZOOM_SPANS[DEFAULT_ZOOM_INDEX],
        cameraY: 0,
        cameraX: 0,
        drawCamY: 0,
        drawCamX: 0,
        // Origin of lastMap/lastFog (must match the slice, or the leading edge is empty/black)
        mapOriginY: 0,
        mapOriginX: 0,
        playerId: '',
        paneW: 0,
        paneH: 0,
        mapH: 0,
        mapW: 0,
        playerY: 0,
        playerX: 0,
        dungeonLevel: null,
        interiorId: null,
        lastMap: null,
        lastFog: null,
        lastEntities: [],
        ready: false,
    };

    let paneEl = null;
    let displayEl = null;
    let rafId = null;
    let pendingReasons = [];
    let emitViewport = null;
    let emitPan = null;
    let lastEmitted = { h: 0, w: 0 };
    let pendingStairArrive = null;
    // Hold first paint until server uses our measured pane size (avoids 20×20 → real jump)
    let initialViewportSynced = false;
    // Pinch/wheel zoom: keep this world point under the same pane pixel after zoom
    let pendingZoomAnchor = null;
    let drawCamReady = false;
    let pendingPanSnap = false;
    let followSuspended = false;

    function currentSpan() {
        return ZOOM_SPANS[state.zoomIndex] || ZOOM_SPANS[DEFAULT_ZOOM_INDEX];
    }

    function isMaxZoom() {
        return state.zoomIndex >= ZOOM_SPANS.length - 1;
    }

    function shortSide() {
        if (state.paneW > 0 && state.paneH > 0) {
            return Math.min(state.paneW, state.paneH);
        }
        return Math.max(state.paneW, state.paneH);
    }

    function marginForSpan(span) {
        // Same formula as camera.margin_for_span
        span = span | 0;
        if (span <= 0) {
            return 0;
        }
        return Math.max(1, Math.floor((EDGE_MARGIN_REF * span + Math.floor(MARGIN_REF_SPAN / 2)) / MARGIN_REF_SPAN));
    }

    function effectiveMargin(size, edgeMargin) {
        if (size <= 1) {
            return 0;
        }
        return Math.min(edgeMargin, Math.floor((size - 1) / 2));
    }

    function measurePane() {
        if (!paneEl) {
            return false;
        }
        const rect = paneEl.getBoundingClientRect();
        state.paneW = Math.max(0, Math.floor(rect.width));
        state.paneH = Math.max(0, Math.floor(rect.height));
        return state.paneW > 0 && state.paneH > 0;
    }

    function measureTileMetrics() {
        const n = currentSpan();
        const side = shortSide();
        let size = side > 0 && n > 0 ? side / n : 1;
        // Grow tile size until the rectangular request fits the budget.
        for (let guard = 0; guard < 64; guard++) {
            const rows = Math.max(1, Math.ceil(state.paneH / size));
            const cols = Math.max(1, Math.ceil(state.paneW / size));
            if (rows <= MAX_VIEWPORT_AXIS && cols <= MAX_VIEWPORT_AXIS
                    && rows * cols <= MAX_VIEWPORT_CELLS) {
                break;
            }
            size *= 1.05;
        }
        state.tileW = size;
        state.tileH = size;
    }

    function computeVisibleCounts() {
        const tw = Math.max(1e-6, state.tileW);
        const th = Math.max(1e-6, state.tileH);
        let rows = Math.max(1, Math.ceil(state.paneH / th));
        let cols = Math.max(1, Math.ceil(state.paneW / tw));
        rows = Math.min(MAX_VIEWPORT_AXIS, rows);
        cols = Math.min(MAX_VIEWPORT_AXIS, cols);
        state.visibleRows = rows;
        state.visibleCols = cols;
    }

    function snapDrawCam() {
        state.drawCamY = state.mapOriginY;
        state.drawCamX = state.mapOriginX;
        drawCamReady = true;
    }

    function localPlayerMoving() {
        return !!(state.playerId
            && typeof PlayerPresentation !== 'undefined'
            && PlayerPresentation.isMoving
            && PlayerPresentation.isMoving(state.playerId));
    }

    function updateDrawCam() {
        if (!localPlayerMoving()) {
            followSuspended = false;
        }
        // Never scroll the draw camera off the current slice — that paints black
        // at the leading edge until the next game_state map arrives.
        if (followSuspended || pendingPanSnap) {
            if (!drawCamReady) {
                snapDrawCam();
            }
            return;
        }
        snapDrawCam();
    }

    function updateCameraForPlayer() {
        // Client camera is advisory until server ack. Per-axis margins match camera.py.
        const vh = state.visibleRows;
        const vw = state.visibleCols;
        const py = state.playerY;
        const px = state.playerX;
        const my = effectiveMargin(vh, marginForSpan(vh));
        const mx = effectiveMargin(vw, marginForSpan(vw));

        if (state.mapH > 0 && vh >= state.mapH) {
            state.cameraY = Math.floor((state.mapH - vh) / 2);
        } else {
            let cy = state.cameraY;
            const sy = py - cy;
            if (sy < my) cy = py - my;
            else if (sy > vh - 1 - my) cy = py - (vh - 1 - my);
            cy = Math.max(py - (vh - 1), Math.min(cy, py));
            state.cameraY = cy | 0;
        }

        if (state.mapW > 0 && vw >= state.mapW) {
            state.cameraX = Math.floor((state.mapW - vw) / 2);
        } else {
            let cx = state.cameraX;
            const sx = px - cx;
            if (sx < mx) cx = px - mx;
            else if (sx > vw - 1 - mx) cx = px - (vw - 1 - mx);
            cx = Math.max(px - (vw - 1), Math.min(cx, px));
            state.cameraX = cx | 0;
        }
    }

    function applyRender() {
        updateDrawCam();
        if (typeof MapRenderer !== 'undefined' && MapRenderer.render) {
            MapRenderer.render(state);
        }
    }

    function captureZoomAnchor(clientX, clientY) {
        if (!paneEl || !Number.isFinite(clientX) || !Number.isFinite(clientY)) {
            return null;
        }
        const rect = paneEl.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) {
            return null;
        }
        const tw = Math.max(1e-6, state.tileW);
        const th = Math.max(1e-6, state.tileH);
        const localX = clientX - rect.left;
        const localY = clientY - rect.top;
        return {
            localX: localX,
            localY: localY,
            worldY: state.cameraY + localY / th,
            worldX: state.cameraX + localX / tw,
        };
    }

    function applyZoomAnchor(anchor) {
        if (!anchor) {
            return;
        }
        const tw = Math.max(1e-6, state.tileW);
        const th = Math.max(1e-6, state.tileH);
        state.cameraY = Math.round(anchor.worldY - anchor.localY / th);
        state.cameraX = Math.round(anchor.worldX - anchor.localX / tw);
    }

    function emitIfNeeded(zoomFocused, force) {
        if (!emitViewport || !state.ready) {
            return;
        }
        const h = state.visibleRows;
        const w = state.visibleCols;
        if (!force && !zoomFocused && h === lastEmitted.h && w === lastEmitted.w) {
            return;
        }
        lastEmitted = { h: h, w: w };
        const payload = { h: h, w: w };
        if (zoomFocused) {
            payload.camera = { y: state.cameraY | 0, x: state.cameraX | 0 };
        }
        emitViewport(payload);
    }

    /** Synchronously measure the pane and return {h,w} for join (no paint). */
    function measureViewportNow() {
        if (!measurePane()) {
            return null;
        }
        measureTileMetrics();
        computeVisibleCounts();
        lastEmitted = { h: state.visibleRows, w: state.visibleCols };
        return { h: state.visibleRows, w: state.visibleCols };
    }

    function runUpdate(reasons) {
        if (!measurePane()) {
            pendingZoomAnchor = null;
            return;
        }
        measureTileMetrics();
        computeVisibleCounts();

        const zoomFocused = !!pendingZoomAnchor;
        if (pendingZoomAnchor) {
            applyZoomAnchor(pendingZoomAnchor);
            pendingZoomAnchor = null;
            snapDrawCam();
            followSuspended = true;
        } else {
            updateCameraForPlayer();
        }

        const forceViewport = reasons.some(function (r) {
            return r === 'level-change' || r === 'combat-map-peek' || r === 'combat-end';
        });
        emitIfNeeded(zoomFocused, forceViewport);
        if (initialViewportSynced || !state.lastMap) {
            applyRender();
        }
        pendingReasons = [];
    }

    function requestMapUpdate(reason) {
        pendingReasons.push(reason || 'update');
        if (rafId !== null) {
            return;
        }
        rafId = requestAnimationFrame(function () {
            rafId = null;
            runUpdate(pendingReasons.slice());
        });
    }

    /**
     * @param {number} index
     * @param {{ clientX: number, clientY: number } | null} focusClient
     *        Screen point that should stay fixed (pinch midpoint or pane centre).
     */
    function setZoomIndex(index, focusClient) {
        const max = ZOOM_SPANS.length - 1;
        const next = Math.max(0, Math.min(max, index | 0));
        if (next === state.zoomIndex) {
            return false;
        }
        if (focusClient) {
            pendingZoomAnchor = captureZoomAnchor(focusClient.clientX, focusClient.clientY);
        } else if (paneEl) {
            const rect = paneEl.getBoundingClientRect();
            pendingZoomAnchor = captureZoomAnchor(
                rect.left + rect.width / 2,
                rect.top + rect.height / 2
            );
        } else {
            pendingZoomAnchor = null;
        }
        state.zoomIndex = next;
        requestMapUpdate('zoom');
        return true;
    }

    function zoomBy(delta, focusClient) {
        return setZoomIndex(state.zoomIndex + delta, focusClient || null);
    }

    function panBy(dTilesY, dTilesX) {
        dTilesY = dTilesY | 0;
        dTilesX = dTilesX | 0;
        if ((!dTilesY && !dTilesX) || !emitPan) {
            return false;
        }
        pendingPanSnap = true;
        emitPan({ dy: dTilesY, dx: dTilesX });
        return true;
    }

    function preloadMonsterEntities(entities) {
        if (typeof MonsterAssets === 'undefined' || !entities) {
            return;
        }
        for (let i = 0; i < entities.length; i++) {
            const ent = entities[i];
            if (ent && ent.kind === 'monster') {
                MonsterAssets.ensureType(ent.type_id, ent.sprite, null);
            }
        }
    }

    function applySnapshot(data, opts) {
        opts = opts || {};
        if (opts.floorChange && typeof PlayerPresentation !== 'undefined'
            && PlayerPresentation.purgeMonsters) {
            PlayerPresentation.purgeMonsters();
        }
        if (data.map) {
            state.lastMap = data.map;
        }
        if (data.fog) {
            state.lastFog = data.fog;
        }
        if (Object.prototype.hasOwnProperty.call(data, 'entities')) {
            state.lastEntities = Array.isArray(data.entities) ? data.entities : [];
            preloadMonsterEntities(state.lastEntities);
        }
        if (data.player && data.player.id != null) {
            state.playerId = String(data.player.id);
        }
        if (data.camera) {
            state.cameraY = data.camera.y | 0;
            state.cameraX = data.camera.x | 0;
            if (data.map) {
                state.mapOriginY = state.cameraY;
                state.mapOriginX = state.cameraX;
            }
            snapDrawCam();
            if (pendingPanSnap || opts.snapPlayer || opts.snapDrawCam) {
                followSuspended = true;
                pendingPanSnap = false;
            }
        } else if (data.map) {
            state.mapOriginY = state.cameraY;
            state.mapOriginX = state.cameraX;
            snapDrawCam();
        }
        if (data.viewport) {
            if (data.viewport.h) state.visibleRows = data.viewport.h | 0;
            if (data.viewport.w) state.visibleCols = data.viewport.w | 0;
        }
        if (data.map_size) {
            state.mapH = data.map_size.h | 0;
            state.mapW = data.map_size.w | 0;
        }
        if (data.player && data.player.pos) {
            state.playerY = data.player.pos[0] | 0;
            state.playerX = data.player.pos[1] | 0;
        }
        if (data.player && data.player.dungeon_level != null) {
            state.dungeonLevel = data.player.dungeon_level | 0;
        }
        if (data.player) {
            state.interiorId = data.player.interior_id || null;
        }

        if (typeof PlayerPresentation !== 'undefined') {
            if (opts.snapPlayer && data.player && data.player.id != null && data.player.pos
                && PlayerPresentation.snapTo) {
                PlayerPresentation.snapTo(data.player.id, data.player.pos[0], data.player.pos[1]);
            }
            if (PlayerPresentation.sync) {
                PlayerPresentation.sync(
                    state.lastEntities || [],
                    state.mapOriginY,
                    state.mapOriginX,
                    data.player || null
                );
            }
        }
    }

    function finishStairArrive() {
        const held = pendingStairArrive;
        pendingStairArrive = null;
        if (!held) {
            applyRender();
            return;
        }
        applySnapshot(held, { snapPlayer: true, floorChange: true });
        requestMapUpdate('level-change');
        applyRender();
    }

    function ingestGameState(data) {
        if (!data) {
            return;
        }
        // Pre-join spectator updates (no player) — ignore for map paint during login
        if (!data.player && !initialViewportSynced) {
            return;
        }
        // After join: never paint spectator payloads (mobile reconnect flash)
        if (!data.player && initialViewportSynced) {
            return;
        }

        // Hold further snapshots until the walk-onto-stairs clip finishes
        if (pendingStairArrive && data.player) {
            pendingStairArrive = data;
            return;
        }

        const newLevel = data.player && data.player.dungeon_level != null
            ? (data.player.dungeon_level | 0)
            : null;
        const levelChanged = state.dungeonLevel != null && newLevel != null
            && newLevel !== state.dungeonLevel;
        if (levelChanged && typeof Sound !== 'undefined') {
            Sound.play('stairs');
        }
        const step = data.stair_step;
        const canApproach = levelChanged && step && state.lastMap
            && typeof PlayerPresentation !== 'undefined'
            && PlayerPresentation.walkToThen
            && data.player && data.player.id != null;

        if (canApproach) {
            pendingStairArrive = data;
            PlayerPresentation.walkToThen(
                data.player.id,
                step.y,
                step.x,
                finishStairArrive
            );
            if (typeof PlayerPresentation.kick === 'function') {
                PlayerPresentation.kick();
            }
            applyRender();
            return;
        }

        const newInterior = data.player ? (data.player.interior_id || null) : null;
        const interiorChanged = state.interiorId !== newInterior;

        applySnapshot(data, {
            snapPlayer: !!levelChanged || interiorChanged,
            floorChange: levelChanged || interiorChanged,
        });

        if (levelChanged || interiorChanged) {
            requestMapUpdate('level-change');
        }

        if (!initialViewportSynced) {
            const matched = data.viewport &&
                lastEmitted.w > 0 &&
                (data.viewport.h | 0) === lastEmitted.h &&
                (data.viewport.w | 0) === lastEmitted.w;
            if (matched) {
                initialViewportSynced = true;
                applyRender();
            } else {
                if (typeof MapRenderer !== 'undefined' && MapRenderer.clearCanvas) {
                    MapRenderer.clearCanvas();
                }
                // Ensure we have a measured size and push it to the server
                if (lastEmitted.w <= 0) {
                    measureViewportNow();
                }
                if (lastEmitted.w > 0 && emitViewport) {
                    emitViewport({ h: lastEmitted.h, w: lastEmitted.w });
                }
            }
            return;
        }

        // Already synced: paint only. Do not remasure here — that caused a post-join shift
        // when pane height settled by one row. ResizeObserver handles real resizes.
        applyRender();
    }

    function init(options) {
        options = options || {};
        paneEl = options.paneEl || document.getElementById('map-pane');
        displayEl = options.displayEl || document.getElementById('map-display');
        emitViewport = options.emitViewport || null;
        emitPan = options.emitPan || null;
        state.ready = true;
        initialViewportSynced = false;
        lastEmitted = { h: 0, w: 0 };
        drawCamReady = false;
        pendingPanSnap = false;
        followSuspended = false;
    }

    function getState() {
        return state;
    }

    return {
        ZOOM_SPANS,
        DEFAULT_ZOOM_INDEX,
        state,
        getState,
        init,
        measurePane,
        measureViewportNow,
        setZoomIndex,
        zoomBy,
        panBy,
        updateCameraForPlayer,
        requestMapUpdate,
        ingestGameState,
        captureZoomAnchor,
        paint: applyRender,
    };
})();

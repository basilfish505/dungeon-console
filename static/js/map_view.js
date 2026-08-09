// map_view.js — authoritative client map viewport state + RAF update pipeline
const MapView = (function () {
    // Zoom = visible tile span (N×N). Last entry is max zoom → exactly 10×10.
    const ZOOM_SPANS = [40, 36, 32, 28, 24, 20, 16, 14, 12, 10];
    const DEFAULT_ZOOM_INDEX = 5; // 20×20 — matches camera.DEFAULT_VIEW_SPAN
    const MIN_VISIBLE = 10; // furthest zoom-in
    const MARGIN_REF_SPAN = 20; // matches camera.DEFAULT_VIEW_SPAN
    const EDGE_MARGIN_REF = 4; // matches camera.EDGE_MARGIN at default span

    // Back-compat alias for any callers still reading ZOOM_LEVELS
    const ZOOM_LEVELS = ZOOM_SPANS;

    const state = {
        zoomIndex: DEFAULT_ZOOM_INDEX,
        tileW: 1,
        tileH: 1,
        visibleCols: ZOOM_SPANS[DEFAULT_ZOOM_INDEX],
        visibleRows: ZOOM_SPANS[DEFAULT_ZOOM_INDEX],
        cameraY: 0,
        cameraX: 0,
        paneW: 0,
        paneH: 0,
        mapH: 0,
        mapW: 0,
        playerY: 0,
        playerX: 0,
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
    // Hold first paint until server uses our measured pane size (avoids 20×20 → real jump)
    let initialViewportSynced = false;
    // Pinch/wheel zoom: keep this world point under the same pane pixel after zoom
    let pendingZoomAnchor = null;

    function currentSpan() {
        return ZOOM_SPANS[state.zoomIndex] || ZOOM_SPANS[DEFAULT_ZOOM_INDEX];
    }

    function isMaxZoom() {
        return state.zoomIndex >= ZOOM_SPANS.length - 1;
    }

    function paneSide() {
        // Prefer measured square; fall back to either axis if layout is mid-update
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
        let w = Math.max(0, Math.floor(rect.width));
        let h = Math.max(0, Math.floor(rect.height));
        // Enforce square metrics even if CSS is slightly off
        if (w > 0 && h > 0 && w !== h) {
            const side = Math.min(w, h);
            w = side;
            h = side;
        }
        state.paneW = w;
        state.paneH = h;
        return state.paneW > 0 && state.paneH > 0;
    }

    function measureTileMetrics() {
        const n = currentSpan();
        const side = paneSide();
        const size = side > 0 ? side / n : 1;
        state.tileW = size;
        state.tileH = size;
    }

    function computeVisibleCounts() {
        const n = currentSpan();
        state.visibleCols = n;
        state.visibleRows = n;
    }

    function updateCameraForPlayer() {
        // Client camera is advisory until server ack. Square viewport → one margin.
        const n = state.visibleRows;
        const py = state.playerY;
        const px = state.playerX;
        const m = effectiveMargin(n, marginForSpan(n));

        if (state.mapH > 0 && n >= state.mapH) {
            state.cameraY = Math.floor((state.mapH - n) / 2);
        } else {
            let cy = state.cameraY;
            const sy = py - cy;
            if (sy < m) cy = py - m;
            else if (sy > n - 1 - m) cy = py - (n - 1 - m);
            cy = Math.max(py - (n - 1), Math.min(cy, py));
            state.cameraY = cy | 0;
        }

        if (state.mapW > 0 && n >= state.mapW) {
            state.cameraX = Math.floor((state.mapW - n) / 2);
        } else {
            let cx = state.cameraX;
            const sx = px - cx;
            if (sx < m) cx = px - m;
            else if (sx > n - 1 - m) cx = px - (n - 1 - m);
            cx = Math.max(px - (n - 1), Math.min(cx, px));
            state.cameraX = cx | 0;
        }
    }

    function applyRender() {
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

    function emitIfNeeded(zoomFocused) {
        if (!emitViewport || !state.ready) {
            return;
        }
        const h = state.visibleRows;
        const w = state.visibleCols;
        if (!zoomFocused && h === lastEmitted.h && w === lastEmitted.w) {
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
        } else {
            updateCameraForPlayer();
        }

        emitIfNeeded(zoomFocused);
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
        emitPan({ dy: dTilesY, dx: dTilesX });
        return true;
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

        if (data.map) {
            state.lastMap = data.map;
        }
        if (data.fog) {
            state.lastFog = data.fog;
        }
        if (Object.prototype.hasOwnProperty.call(data, 'entities')) {
            state.lastEntities = Array.isArray(data.entities) ? data.entities : [];
        }
        if (data.camera) {
            state.cameraY = data.camera.y | 0;
            state.cameraX = data.camera.x | 0;
        }
        if (data.viewport) {
            if (data.viewport.h) state.visibleRows = data.viewport.h | 0;
            if (data.viewport.w) state.visibleCols = data.viewport.w | 0;
            // Keep square if server ever differs
            if (state.visibleRows !== state.visibleCols) {
                const n = Math.min(state.visibleRows, state.visibleCols);
                state.visibleRows = n;
                state.visibleCols = n;
            }
        }
        if (data.map_size) {
            state.mapH = data.map_size.h | 0;
            state.mapW = data.map_size.w | 0;
        }
        if (data.player && data.player.pos) {
            state.playerY = data.player.pos[0] | 0;
            state.playerX = data.player.pos[1] | 0;
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
    }

    function getState() {
        return state;
    }

    return {
        ZOOM_SPANS,
        ZOOM_LEVELS,
        DEFAULT_ZOOM_INDEX,
        MIN_VISIBLE,
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
    };
})();

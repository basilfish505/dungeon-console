// map_view.js — authoritative client map viewport state + RAF update pipeline
const MapView = (function () {
    const ZOOM_LEVELS = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24];
    const DEFAULT_ZOOM_INDEX = 4; // 12px

    const state = {
        zoomIndex: DEFAULT_ZOOM_INDEX,
        tileW: 12,
        tileH: 12,
        visibleCols: 20,
        visibleRows: 20,
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
        ready: false,
    };

    let paneEl = null;
    let displayEl = null;
    let rafId = null;
    let pendingReasons = [];
    let emitViewport = null;
    let lastEmitted = { h: 0, w: 0 };

    function tileSize() {
        return ZOOM_LEVELS[state.zoomIndex] || ZOOM_LEVELS[DEFAULT_ZOOM_INDEX];
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
        const size = tileSize();
        state.tileW = size;
        state.tileH = size;
        if (!displayEl) {
            return;
        }
        displayEl.style.fontSize = size + 'px';
        displayEl.style.lineHeight = '1';
        const probe = document.createElement('span');
        probe.style.cssText =
            'position:absolute;left:-9999px;top:0;visibility:hidden;white-space:pre;' +
            'font-family:\'Courier New\',Courier,monospace;font-size:' + size + 'px;line-height:1;';
        probe.textContent = 'M'.repeat(20);
        document.body.appendChild(probe);
        const w = probe.getBoundingClientRect().width;
        document.body.removeChild(probe);
        if (w > 0) {
            state.tileW = w / 20;
            state.tileH = size;
        }
    }

    function computeVisibleCounts() {
        const tw = Math.max(1, state.tileW);
        const th = Math.max(1, state.tileH);
        state.visibleCols = Math.max(8, Math.floor(state.paneW / tw));
        state.visibleRows = Math.max(8, Math.floor(state.paneH / th));
        // Soft headroom matching server MAX_VIEWPORT
        state.visibleCols = Math.min(80, state.visibleCols);
        state.visibleRows = Math.min(80, state.visibleRows);
    }

    function updateCameraForPlayer() {
        // Client camera is advisory until server ack; keep player centered band locally
        // for immediate re-render of last map when only zoom/resize changed before ack.
        const vh = state.visibleRows;
        const vw = state.visibleCols;
        const py = state.playerY;
        const px = state.playerX;
        const my = Math.min(4, Math.max(0, Math.floor((vh - 1) / 2)));
        const mx = Math.min(4, Math.max(0, Math.floor((vw - 1) / 2)));

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
        if (typeof MapRenderer !== 'undefined' && MapRenderer.render) {
            MapRenderer.render(state);
        }
    }

    function emitIfNeeded() {
        if (!emitViewport || !state.ready) {
            return;
        }
        const h = state.visibleRows;
        const w = state.visibleCols;
        if (h === lastEmitted.h && w === lastEmitted.w) {
            return;
        }
        lastEmitted = { h, w };
        emitViewport({ h, w });
    }

    function runUpdate(reasons) {
        if (!measurePane()) {
            return;
        }
        measureTileMetrics();
        computeVisibleCounts();
        updateCameraForPlayer();
        emitIfNeeded();
        applyRender();
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

    function setZoomIndex(index) {
        const max = ZOOM_LEVELS.length - 1;
        const next = Math.max(0, Math.min(max, index | 0));
        if (next === state.zoomIndex) {
            return false;
        }
        state.zoomIndex = next;
        requestMapUpdate('zoom');
        return true;
    }

    function zoomBy(delta) {
        return setZoomIndex(state.zoomIndex + delta);
    }

    function ingestGameState(data) {
        if (!data) {
            return;
        }
        if (data.map) {
            state.lastMap = data.map;
        }
        if (data.fog) {
            state.lastFog = data.fog;
        }
        if (data.camera) {
            state.cameraY = data.camera.y | 0;
            state.cameraX = data.camera.x | 0;
        }
        if (data.viewport) {
            // Server tile counts are authoritative for the received map buffer
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
        applyRender();
        // Re-measure after layout settles; emit if pane wants a different tile count
        if (state.ready) {
            requestMapUpdate('game_state');
        }
    }

    function init(options) {
        options = options || {};
        paneEl = options.paneEl || document.getElementById('map-pane');
        displayEl = options.displayEl || document.getElementById('map-display');
        emitViewport = options.emitViewport || null;
        state.ready = true;
        requestMapUpdate('init');
    }

    function getState() {
        return state;
    }

    return {
        ZOOM_LEVELS,
        state,
        getState,
        init,
        measurePane,
        setZoomIndex,
        zoomBy,
        updateCameraForPlayer,
        requestMapUpdate,
        ingestGameState,
    };
})();

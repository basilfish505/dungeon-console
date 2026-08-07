// map_view.js — authoritative client map viewport state + RAF update pipeline
const MapView = (function () {
    // Discrete font-size steps (px). Last entry is max zoom → exact 10 tiles across.
    const ZOOM_LEVELS = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 40, 48];
    const DEFAULT_ZOOM_INDEX = 7; // 18px — one step in from 16px
    const MIN_VISIBLE = 10; // furthest zoom-in: 10 tiles across
    const MARGIN_REF_SPAN = 20; // matches camera.DEFAULT_VIEW_SPAN for edge-margin scaling

    const state = {
        zoomIndex: DEFAULT_ZOOM_INDEX,
        tileW: ZOOM_LEVELS[DEFAULT_ZOOM_INDEX],
        tileH: ZOOM_LEVELS[DEFAULT_ZOOM_INDEX],
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
    let emitPan = null;
    let lastEmitted = { h: 0, w: 0 };
    // Hold first paint until server uses our measured pane size (avoids 20×20 → real jump)
    let initialViewportSynced = false;

    function isMaxZoom() {
        return state.zoomIndex >= ZOOM_LEVELS.length - 1;
    }

    function probeMonoAspect() {
        const probe = document.createElement('span');
        probe.style.cssText =
            'position:absolute;left:-9999px;top:0;visibility:hidden;white-space:pre;' +
            'font-family:\'Courier New\',Courier,monospace;font-size:100px;line-height:1;';
        probe.textContent = 'M'.repeat(20);
        document.body.appendChild(probe);
        const probeW = probe.getBoundingClientRect().width;
        document.body.removeChild(probe);
        return probeW > 0 ? (probeW / 20) / 100 : 0.6;
    }

    function applyExactColumnFit(cols) {
        // Used only for max zoom: size font so exactly `cols` glyphs span the pane
        let fontSize = state.paneW / (cols * probeMonoAspect());
        if (!displayEl) {
            state.tileW = state.paneW / cols;
            state.tileH = fontSize;
            return;
        }
        displayEl.style.fontSize = fontSize + 'px';
        displayEl.style.lineHeight = '1';
        const probe = document.createElement('span');
        probe.style.cssText =
            'position:absolute;left:-9999px;top:0;visibility:hidden;white-space:pre;' +
            'font-family:\'Courier New\',Courier,monospace;font-size:' + fontSize +
            'px;line-height:1;';
        probe.textContent = 'M'.repeat(cols);
        document.body.appendChild(probe);
        let measured = probe.getBoundingClientRect().width;
        if (measured > state.paneW && measured > 0) {
            fontSize = fontSize * (state.paneW / measured) * 0.995;
            displayEl.style.fontSize = fontSize + 'px';
            probe.style.fontSize = fontSize + 'px';
            measured = probe.getBoundingClientRect().width;
        }
        probe.textContent = 'M\nM';
        const twoLine = probe.getBoundingClientRect().height;
        document.body.removeChild(probe);
        state.tileW = measured > 0 ? measured / cols : state.paneW / cols;
        state.tileH = twoLine > 0 ? twoLine / 2 : fontSize;
    }

    function tileSize() {
        if (isMaxZoom() && state.paneW > 0) {
            return state.paneW / MIN_VISIBLE;
        }
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
        if (!displayEl) {
            const size = tileSize();
            state.tileW = size;
            state.tileH = size;
            return;
        }

        if (isMaxZoom() && state.paneW > 0) {
            applyExactColumnFit(MIN_VISIBLE);
            return;
        }

        const size = tileSize();
        state.tileW = size;
        state.tileH = size;
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

    function rowsThatFit() {
        const th = Math.max(1, state.tileH);
        return Math.max(1, Math.min(80, Math.floor(state.paneH / th)));
    }

    function computeVisibleCounts() {
        const tw = Math.max(1, state.tileW);

        if (isMaxZoom()) {
            state.visibleCols = MIN_VISIBLE;
            state.visibleRows = rowsThatFit();
            return;
        }

        let cols = Math.max(1, Math.floor(state.paneW / tw));
        let rows = rowsThatFit();

        // Discrete zoom grew tiles past what fits MIN_VISIBLE cols → promote to max fit
        if (cols < MIN_VISIBLE) {
            state.zoomIndex = ZOOM_LEVELS.length - 1;
            applyExactColumnFit(MIN_VISIBLE);
            state.visibleCols = MIN_VISIBLE;
            state.visibleRows = rowsThatFit();
            return;
        }

        state.visibleCols = Math.min(80, cols);
        state.visibleRows = Math.min(80, rows);
    }

    function updateCameraForPlayer() {
        // Client camera is advisory until server ack
        const vh = state.visibleRows;
        const vw = state.visibleCols;
        const py = state.playerY;
        const px = state.playerX;
        const refMargin = 4;
        const rawMy = Math.max(1, Math.round(refMargin * vh / MARGIN_REF_SPAN));
        const rawMx = Math.max(1, Math.round(refMargin * vw / MARGIN_REF_SPAN));
        const my = Math.min(rawMy, Math.max(0, Math.floor((vh - 1) / 2)));
        const mx = Math.min(rawMx, Math.max(0, Math.floor((vw - 1) / 2)));

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
            return;
        }
        measureTileMetrics();
        computeVisibleCounts();
        updateCameraForPlayer();
        emitIfNeeded();
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

        if (!initialViewportSynced) {
            const matched = data.viewport &&
                lastEmitted.w > 0 &&
                (data.viewport.h | 0) === lastEmitted.h &&
                (data.viewport.w | 0) === lastEmitted.w;
            if (matched) {
                initialViewportSynced = true;
                applyRender();
            } else {
                if (displayEl) {
                    displayEl.textContent = '';
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
    };
})();

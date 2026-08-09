// map_inspect.js — resolve map taps to inspectable cells (extensible by glyph/kind)
const MapInspect = (function () {
    /** Glyphs that may be inspected (client-side hint; server validates). */
    const INSPECTABLE_GLYPHS = {
        '&': 'monster',
        // Future: '@' player (other), '↑'/'↓' stairs, etc.
    };

    function clientToWorldTile(clientX, clientY) {
        if (typeof MapView === 'undefined' || !MapView.captureZoomAnchor) {
            return null;
        }
        const anchor = MapView.captureZoomAnchor(clientX, clientY);
        if (!anchor) {
            return null;
        }
        return {
            y: Math.floor(anchor.worldY),
            x: Math.floor(anchor.worldX),
            localX: anchor.localX,
            localY: anchor.localY,
        };
    }

    function viewportCharAt(worldY, worldX) {
        const st = MapView.getState();
        const map = st.lastMap;
        if (!map || !map.length) {
            return null;
        }
        const vy = worldY - (st.cameraY | 0);
        const vx = worldX - (st.cameraX | 0);
        if (vy < 0 || vx < 0 || vy >= map.length) {
            return null;
        }
        const row = map[vy];
        if (!row || vx >= row.length) {
            return null;
        }
        return row[vx];
    }

    function fogAt(worldY, worldX) {
        const st = MapView.getState();
        const fog = st.lastFog;
        if (!fog || !fog.length) {
            return 'visible';
        }
        const vy = worldY - (st.cameraY | 0);
        const vx = worldX - (st.cameraX | 0);
        if (vy < 0 || vx < 0 || vy >= fog.length) {
            return 'unexplored';
        }
        const row = fog[vy];
        if (!row || vx >= row.length) {
            return 'unexplored';
        }
        return row[vx] || 'unexplored';
    }

    /**
     * If the tile under the pointer is inspectable, emit inspect_map.
     * @returns {boolean} true if the tap was consumed as an inspect attempt
     */
    function tryInspectAt(clientX, clientY) {
        if (typeof InspectUI !== 'undefined' && InspectUI.isOpen()) {
            return true;
        }
        const tile = clientToWorldTile(clientX, clientY);
        if (!tile) {
            return false;
        }
        const ch = viewportCharAt(tile.y, tile.x);
        if (!ch || !INSPECTABLE_GLYPHS[ch]) {
            return false;
        }
        // Only inspect currently visible cells (explored memory may still show terrain)
        if (fogAt(tile.y, tile.x) !== 'visible') {
            return false;
        }
        if (typeof SocketHandler === 'undefined' || !SocketHandler.inspectMap) {
            return false;
        }
        SocketHandler.inspectMap(tile.y, tile.x);
        return true;
    }

    return {
        INSPECTABLE_GLYPHS,
        clientToWorldTile,
        tryInspectAt,
    };
})();

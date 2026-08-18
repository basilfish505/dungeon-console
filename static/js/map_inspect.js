// map_inspect.js — resolve map taps to inspectable cells (extensible by glyph/kind)
const MapInspect = (function () {
    /** Glyphs that may be inspected (client-side hint; server validates). */
    const INSPECTABLE_GLYPHS = {
        '&': 'monster',
        '=': 'shop',
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

    function entityKindAt(worldY, worldX) {
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

    /**
     * If the tile under the pointer is inspectable, emit inspect_map.
     * @returns {boolean} true if the tap was consumed as an inspect attempt
     */
    function tryInspectAt(clientX, clientY) {
        if (typeof InspectUI !== 'undefined' && InspectUI.isOpen()) {
            return true;
        }
        if (typeof InventoryUI !== 'undefined' && InventoryUI.isOpen()) {
            return true;
        }
        const tile = clientToWorldTile(clientX, clientY);
        if (!tile) {
            return false;
        }
        const ch = viewportCharAt(tile.y, tile.x);
        const entityKind = entityKindAt(tile.y, tile.x);
        if (!ch && !entityKind) {
            return false;
        }
        if (!INSPECTABLE_GLYPHS[ch] && entityKind !== 'npc' && entityKind !== 'shop') {
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

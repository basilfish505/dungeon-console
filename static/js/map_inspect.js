// map_inspect.js — resolve map taps to inspectable cells (extensible by glyph/kind)
const MapInspect = (function () {
    /** Glyphs that may be inspected (client-side hint; server validates). */
    const INSPECTABLE_GLYPHS = {
        '&': 'monster',
        '@': 'player',
        '=': 'shop',
    };

    function sliceOrigin(st) {
        st = st || MapView.getState();
        return {
            y: Number.isFinite(st.mapOriginY) ? (st.mapOriginY | 0) : (st.cameraY | 0),
            x: Number.isFinite(st.mapOriginX) ? (st.mapOriginX | 0) : (st.cameraX | 0),
        };
    }

    function clientToWorldTile(clientX, clientY) {
        if (typeof MapView === 'undefined' || !MapView.captureZoomAnchor) {
            return null;
        }
        const anchor = MapView.captureZoomAnchor(clientX, clientY);
        if (!anchor) {
            return null;
        }
        // Painted map uses mapOrigin, while captureZoomAnchor is camera-relative.
        // Convert so taps match what is on screen.
        const st = MapView.getState();
        const origin = sliceOrigin(st);
        const th = Math.max(1e-6, st.tileH);
        const tw = Math.max(1e-6, st.tileW);
        const localY = anchor.localY;
        const localX = anchor.localX;
        return {
            y: Math.floor(origin.y + localY / th),
            x: Math.floor(origin.x + localX / tw),
            localX: localX,
            localY: localY,
        };
    }

    function viewportCharAt(worldY, worldX) {
        const st = MapView.getState();
        const map = st.lastMap;
        if (!map || !map.length) {
            return null;
        }
        const origin = sliceOrigin(st);
        const vy = worldY - origin.y;
        const vx = worldX - origin.x;
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
        const origin = sliceOrigin(st);
        const vy = worldY - origin.y;
        const vx = worldX - origin.x;
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
        const origin = sliceOrigin(st);
        for (let i = 0; i < ents.length; i++) {
            const e = ents[i];
            if (!e) {
                continue;
            }
            if (origin.y + (e.vy | 0) === worldY && origin.x + (e.vx | 0) === worldX) {
                return e.kind || null;
            }
        }
        return null;
    }

    /** Local / overlay actor tile (optimistic presentation), if any. */
    function presentationKindAt(worldY, worldX) {
        if (typeof PlayerPresentation === 'undefined') {
            return null;
        }
        if (PlayerPresentation.tilePos && typeof MapView !== 'undefined') {
            const st = MapView.getState();
            if (st.playerId) {
                const t = PlayerPresentation.tilePos(st.playerId);
                if (t && (t.y | 0) === worldY && (t.x | 0) === worldX) {
                    return 'player';
                }
            }
        }
        if (PlayerPresentation.sample) {
            const samples = PlayerPresentation.sample();
            for (let i = 0; i < samples.length; i++) {
                const p = samples[i];
                if (!p) {
                    continue;
                }
                if ((p.visualY | 0) === worldY && (p.visualX | 0) === worldX) {
                    return p.kind || null;
                }
            }
        }
        const st = MapView.getState();
        if ((st.playerY | 0) === worldY && (st.playerX | 0) === worldX) {
            return 'player';
        }
        return null;
    }

    /** True if the tap hit the local player's ack'd or presentation tile. */
    function isTapOnLocalPlayer(worldY, worldX) {
        if (typeof MapView === 'undefined') {
            return false;
        }
        const st = MapView.getState();
        if ((st.playerY | 0) === worldY && (st.playerX | 0) === worldX) {
            return true;
        }
        if (typeof PlayerPresentation === 'undefined' || !st.playerId) {
            return false;
        }
        if (PlayerPresentation.tilePos) {
            const t = PlayerPresentation.tilePos(st.playerId);
            if (t && (t.y | 0) === worldY && (t.x | 0) === worldX) {
                return true;
            }
        }
        if (PlayerPresentation.visualPos) {
            const v = PlayerPresentation.visualPos(st.playerId);
            if (v && Math.floor(v.y) === worldY && Math.floor(v.x) === worldX) {
                return true;
            }
        }
        return false;
    }

    function isInspectable(ch, entityKind) {
        if (INSPECTABLE_GLYPHS[ch]) {
            return true;
        }
        return (
            entityKind === 'npc'
            || entityKind === 'shop'
            || entityKind === 'monster'
            || entityKind === 'player'
        );
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
        if (typeof Combat !== 'undefined' && Combat.isOpen && Combat.isOpen()) {
            return true;
        }
        const tile = clientToWorldTile(clientX, clientY);
        if (!tile) {
            return false;
        }
        const onSelf = isTapOnLocalPlayer(tile.y, tile.x);
        const ch = viewportCharAt(tile.y, tile.x);
        const entityKind = entityKindAt(tile.y, tile.x) || presentationKindAt(tile.y, tile.x);
        if (!onSelf && !ch && !entityKind) {
            return false;
        }
        if (!onSelf && !isInspectable(ch, entityKind)) {
            return false;
        }
        // Only inspect currently visible cells (explored memory may still show terrain)
        if (!onSelf && fogAt(tile.y, tile.x) !== 'visible') {
            return false;
        }
        if (typeof SocketHandler === 'undefined' || !SocketHandler.inspectMap) {
            return false;
        }
        // Always inspect using server-acked coords for self (optimistic sprite may differ).
        if (onSelf) {
            const st = MapView.getState();
            SocketHandler.inspectMap(st.playerY | 0, st.playerX | 0);
            return true;
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

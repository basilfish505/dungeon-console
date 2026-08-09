// map_renderer.js — canvas map paint (terrain + monster sprites under ASCII)
const MapRenderer = (function () {
    const FOG_COLORS = {
        visible: '#00ff00',
        explored: '#006600',
        unexplored: '#001100',
    };
    const BG = '#000000';
    const FONT_STACK = "'Courier New', Courier, monospace";
    /** Explored tiles: dim to approximate explored green vs bright visible. */
    const EXPLORED_TERRAIN_ALPHA = 0.4;

    let canvasEl = null;
    let ctx = null;
    let assetsHooked = false;

    function ensureCanvas() {
        if (canvasEl && ctx) {
            return canvasEl;
        }
        canvasEl = document.getElementById('map-display');
        if (!canvasEl) {
            return null;
        }
        if (canvasEl.tagName !== 'CANVAS') {
            console.warn('MapRenderer expects #map-display to be a <canvas>');
            return null;
        }
        ctx = canvasEl.getContext('2d');
        return canvasEl;
    }

    function graphicsEnabled() {
        return typeof TileAssets !== 'undefined' && TileAssets.GRAPHICS_TERRAIN_ENABLED;
    }

    function hookTileAssets() {
        if (assetsHooked) {
            return;
        }
        assetsHooked = true;
        if (typeof TileAssets !== 'undefined') {
            TileAssets.preload();
            TileAssets.setOnReady(function () {
                if (typeof MapView !== 'undefined' && MapView.getState) {
                    render(MapView.getState());
                }
            });
        }
        if (typeof MonsterAssets !== 'undefined') {
            MonsterAssets.preloadKnown();
            MonsterAssets.setOnReady(function () {
                if (typeof MapView !== 'undefined' && MapView.getState) {
                    render(MapView.getState());
                }
            });
        }
    }

    function clearCanvas() {
        const el = ensureCanvas();
        if (!el || !ctx) {
            return;
        }
        const w = el.width;
        const h = el.height;
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.fillStyle = BG;
        ctx.fillRect(0, 0, w, h);
    }

    function drawTerrain(key, dx, dy, dw, dh, fogState) {
        const img = TileAssets.getImage(key);
        if (!img) {
            return false;
        }
        const explored = fogState === 'explored';
        if (explored) {
            ctx.save();
            ctx.globalAlpha = EXPLORED_TERRAIN_ALPHA;
        }
        ctx.drawImage(img, dx, dy, dw, dh);
        if (explored) {
            ctx.restore();
        }
        return true;
    }

    function drawMonsterSprite(typeId, spriteUrl, dx, dy, dw, dh, fogState) {
        if (typeof MonsterAssets === 'undefined') {
            return false;
        }
        MonsterAssets.ensureType(typeId, spriteUrl, null);
        const img = MonsterAssets.getSprite(typeId, spriteUrl);
        if (!img) {
            return false;
        }
        const explored = fogState === 'explored';
        if (explored) {
            ctx.save();
            ctx.globalAlpha = EXPLORED_TERRAIN_ALPHA;
        }
        ctx.drawImage(img, dx, dy, dw, dh);
        if (explored) {
            ctx.restore();
        }
        return true;
    }

    function entityAt(entities, vy, vx) {
        if (!entities || !entities.length) {
            return null;
        }
        for (let i = 0; i < entities.length; i++) {
            const e = entities[i];
            if (e && (e.vy | 0) === vy && (e.vx | 0) === vx) {
                return e;
            }
        }
        return null;
    }

    function render(state) {
        const el = ensureCanvas();
        if (!el || !ctx || !state) {
            return;
        }

        hookTileAssets();

        const paneW = Math.max(1, state.paneW | 0);
        const paneH = Math.max(1, state.paneH | 0);
        const dpr = Math.max(1, window.devicePixelRatio || 1);

        el.style.width = paneW + 'px';
        el.style.height = paneH + 'px';
        const bw = Math.max(1, Math.floor(paneW * dpr));
        const bh = Math.max(1, Math.floor(paneH * dpr));
        if (el.width !== bw || el.height !== bh) {
            el.width = bw;
            el.height = bh;
        }

        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.fillStyle = BG;
        ctx.fillRect(0, 0, paneW, paneH);

        const mapData = state.lastMap;
        if (!mapData || !mapData.length) {
            return;
        }

        const useGraphics = graphicsEnabled();
        if (useGraphics && !TileAssets.isReady()) {
            return;
        }

        const tw = Math.max(1, state.tileW);
        const th = Math.max(1, state.tileH);
        const fog = state.lastFog;
        const entities = state.lastEntities || [];
        const fontPx = Math.max(1, Math.floor(th));

        ctx.font = fontPx + 'px ' + FONT_STACK;
        ctx.textBaseline = 'top';
        ctx.textAlign = 'left';

        for (let y = 0; y < mapData.length; y++) {
            const row = mapData[y];
            const fogRow = fog && fog[y] ? fog[y] : null;
            const py = Math.floor(y * th);
            if (py >= paneH) {
                break;
            }
            const dh = Math.max(1, Math.floor((y + 1) * th) - py);
            for (let x = 0; x < row.length; x++) {
                const ch = row[x];
                if (ch === ' ' || ch === '\u00a0') {
                    continue;
                }
                const px = Math.floor(x * tw);
                if (px >= paneW) {
                    break;
                }
                const fogState = fogRow ? (fogRow[x] || 'visible') : 'visible';
                if (fogState === 'unexplored') {
                    continue;
                }
                const dw = Math.max(1, Math.floor((x + 1) * tw) - px);

                let drewMonsterSprite = false;
                if (useGraphics) {
                    const terrainKey = TileAssets.terrainKeyForCell(ch);
                    const drewTerrain = terrainKey
                        ? drawTerrain(terrainKey, px, py, dw, dh, fogState)
                        : false;
                    if (TileAssets.isTerrainOnly(ch) && drewTerrain) {
                        continue;
                    }
                    if (ch === '&') {
                        const ent = entityAt(entities, y, x);
                        if (ent && ent.kind === 'monster') {
                            drewMonsterSprite = drawMonsterSprite(
                                ent.type_id, ent.sprite, px, py, dw, dh, fogState
                            );
                        }
                        if (drewMonsterSprite) {
                            continue;
                        }
                    }
                }
                ctx.fillStyle = FOG_COLORS[fogState] || FOG_COLORS.visible;
                ctx.fillText(ch, px, py);
            }
        }
    }

    return { render, clearCanvas };
})();

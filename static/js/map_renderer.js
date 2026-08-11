// map_renderer.js — canvas map paint (terrain + monster/player sprites under ASCII)
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
        function paint() {
            if (typeof MapView !== 'undefined' && MapView.paint) {
                MapView.paint();
            } else if (typeof MapView !== 'undefined' && MapView.getState) {
                render(MapView.getState());
            }
        }
        if (typeof TileAssets !== 'undefined') {
            TileAssets.preload();
            TileAssets.setOnReady(paint);
        }
        if (typeof MonsterAssets !== 'undefined') {
            MonsterAssets.preloadKnown();
            MonsterAssets.setOnReady(paint);
        }
        if (typeof PlayerAssets !== 'undefined') {
            PlayerAssets.preload();
            PlayerAssets.setOnReady(paint);
        }
        if (typeof PlayerPresentation !== 'undefined') {
            PlayerPresentation.setOnFrame(paint);
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

    function drawActorImage(img, sx, sy, sw, sh, cx, cy, dw, dh, flip, pose) {
        pose = pose || { bob: 0, scaleX: 1, scaleY: 1 };
        const bobPx = (pose.bob || 0) * dh;
        ctx.save();
        ctx.translate(cx, cy);
        ctx.scale(flip ? -1 : 1, 1);
        ctx.translate(0, -bobPx);
        ctx.scale(pose.scaleX || 1, pose.scaleY || 1);
        ctx.drawImage(img, sx, sy, sw, sh, -dw / 2, -dh, dw, dh);
        ctx.restore();
    }

    function drawActorOverlays(state, tw, th, drawCamY, drawCamX) {
        if (typeof PlayerPresentation === 'undefined') {
            return;
        }
        const samples = PlayerPresentation.sample();
        const dw = Math.max(1, Math.round(tw));
        const dh = Math.max(1, Math.round(th));
        for (let i = 0; i < samples.length; i++) {
            const p = samples[i];
            const cx = (p.visualX + 0.5 - drawCamX) * tw;
            const cy = (p.visualY + 1 - drawCamY) * th;

            if (p.kind === 'monster') {
                if (typeof MonsterAssets === 'undefined') {
                    continue;
                }
                MonsterAssets.ensureType(p.typeId, p.sprite, null);
                const img = MonsterAssets.getSprite(p.typeId, p.sprite);
                if (!img) {
                    continue;
                }
                const artFacing = MonsterAssets.defaultFacing
                    ? MonsterAssets.defaultFacing(p.typeId)
                    : 'left';
                const flip = p.facing && artFacing && p.facing !== artFacing;
                const pose = MonsterAssets.walkPose
                    ? MonsterAssets.walkPose(p.clip, p.clipElapsedMs)
                    : null;
                drawActorImage(
                    img, 0, 0, img.naturalWidth, img.naturalHeight,
                    cx, cy, dw, dh, flip, pose
                );
                continue;
            }

            if (typeof PlayerAssets === 'undefined') {
                continue;
            }
            const frame = PlayerAssets.getFrame(p.appearanceId, p.clip, p.clipElapsedMs);
            if (!frame || !frame.img) {
                continue;
            }
            const artFacing = PlayerAssets.defaultFacing(p.appearanceId);
            const flip = p.facing && artFacing && p.facing !== artFacing;
            drawActorImage(
                frame.img, frame.sx, frame.sy, frame.sw, frame.sh,
                cx, cy, dw, dh, flip, null
            );
        }
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
        const sliceY = state.cameraY | 0;
        const sliceX = state.cameraX | 0;
        const drawCamY = Number.isFinite(state.drawCamY) ? state.drawCamY : sliceY;
        const drawCamX = Number.isFinite(state.drawCamX) ? state.drawCamX : sliceX;
        const fontPx = Math.max(1, Math.floor(th));
        const overlayActors = useGraphics && typeof PlayerPresentation !== 'undefined';

        ctx.font = fontPx + 'px ' + FONT_STACK;
        ctx.textBaseline = 'top';
        ctx.textAlign = 'left';

        for (let y = 0; y < mapData.length; y++) {
            const row = mapData[y];
            const fogRow = fog && fog[y] ? fog[y] : null;
            const worldY = sliceY + y;
            const py = (worldY - drawCamY) * th;
            if (py >= paneH) {
                continue;
            }
            if (py + th <= 0) {
                continue;
            }
            const dh = th;
            for (let x = 0; x < row.length; x++) {
                const ch = row[x];
                if (ch === ' ' || ch === '\u00a0') {
                    continue;
                }
                const worldX = sliceX + x;
                const px = (worldX - drawCamX) * tw;
                if (px >= paneW || px + tw <= 0) {
                    continue;
                }
                const fogState = fogRow ? (fogRow[x] || 'visible') : 'visible';
                if (fogState === 'unexplored') {
                    continue;
                }
                const dw = tw;

                let drewEntitySprite = false;
                if (useGraphics) {
                    const ent = (ch === '@' || ch === '&') ? entityAt(entities, y, x) : null;
                    const terrainCh = (ent && ent.under) ? ent.under : ch;
                    const terrainKey = TileAssets.terrainKeyForCell(terrainCh);
                    const drewTerrain = terrainKey
                        ? drawTerrain(terrainKey, px, py, dw, dh, fogState)
                        : false;
                    if (TileAssets.isTerrainOnly(ch) && drewTerrain) {
                        continue;
                    }
                    if (ch === '&' && overlayActors) {
                        continue;
                    }
                    if (ch === '&') {
                        if (ent && ent.kind === 'monster') {
                            drewEntitySprite = drawMonsterSprite(
                                ent.type_id, ent.sprite, px, py, dw, dh, fogState
                            );
                        }
                        if (drewEntitySprite) {
                            continue;
                        }
                    }
                    if (ch === '@' && overlayActors) {
                        continue;
                    }
                }
                ctx.fillStyle = FOG_COLORS[fogState] || FOG_COLORS.visible;
                ctx.fillText(ch, px, py);
            }
        }

        if (overlayActors) {
            drawActorOverlays(state, tw, th, drawCamY, drawCamX);
        }
    }

    return { render, clearCanvas };
})();

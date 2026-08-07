// map_renderer.js — canvas map paint (no per-tile DOM; FOW-friendly)
const MapRenderer = (function () {
    const FOG_COLORS = {
        visible: '#00ff00',
        explored: '#006600',
        unexplored: '#001100',
    };
    const BG = '#000000';
    const FONT_STACK = "'Courier New', Courier, monospace";

    let canvasEl = null;
    let ctx = null;

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

    function render(state) {
        const el = ensureCanvas();
        if (!el || !ctx || !state) {
            return;
        }

        const paneW = Math.max(1, state.paneW | 0);
        const paneH = Math.max(1, state.paneH | 0);
        const dpr = Math.max(1, window.devicePixelRatio || 1);

        // CSS size = pane; backing store scaled for sharpness
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

        const tw = Math.max(1, state.tileW);
        const th = Math.max(1, state.tileH);
        const fog = state.lastFog;
        const fontPx = Math.max(1, Math.floor(th));

        ctx.font = fontPx + 'px ' + FONT_STACK;
        ctx.textBaseline = 'top';
        ctx.textAlign = 'left';

        for (let y = 0; y < mapData.length; y++) {
            const row = mapData[y];
            const fogRow = fog && fog[y] ? fog[y] : null;
            const py = y * th;
            if (py >= paneH) {
                break;
            }
            for (let x = 0; x < row.length; x++) {
                const ch = row[x];
                if (ch === ' ' || ch === '\u00a0') {
                    continue;
                }
                const px = x * tw;
                if (px >= paneW) {
                    break;
                }
                const fogState = fogRow ? (fogRow[x] || 'visible') : 'visible';
                if (fogState === 'unexplored') {
                    continue;
                }
                ctx.fillStyle = FOG_COLORS[fogState] || FOG_COLORS.visible;
                ctx.fillText(ch, px, py);
            }
        }
    }

    return { render, clearCanvas };
})();

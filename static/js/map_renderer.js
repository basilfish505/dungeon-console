// map_renderer.js — single <pre> renderer filling the map pane
const MapRenderer = (function () {
    const FOG_COLORS = {
        visible: '#00ff00',
        explored: '#006600',
        unexplored: '#001100',
    };

    let displayEl = null;

    function ensureEl() {
        if (!displayEl) {
            displayEl = document.getElementById('map-display');
        }
        return displayEl;
    }

    function escapeHtml(ch) {
        if (ch === '&') return '&amp;';
        if (ch === '<') return '&lt;';
        if (ch === '>') return '&gt;';
        if (ch === ' ') return '\u00a0';
        return ch;
    }

    function hasNonVisibleFog(fog) {
        if (!fog || !fog.length) {
            return false;
        }
        for (let y = 0; y < fog.length; y++) {
            const row = fog[y];
            for (let x = 0; x < row.length; x++) {
                if (row[x] && row[x] !== 'visible') {
                    return true;
                }
            }
        }
        return false;
    }

    function render(state) {
        const el = ensureEl();
        if (!el || !state) {
            return;
        }

        // Use measured tile size so max zoom (10-across) fills the pane
        const size = state.tileH || state.tileW || 12;

        el.style.fontSize = size + 'px';
        el.style.lineHeight = '1';
        el.style.width = '100%';
        el.style.height = '100%';

        const mapData = state.lastMap;
        if (!mapData || !mapData.length) {
            el.textContent = '';
            return;
        }

        const fog = state.lastFog;
        if (hasNonVisibleFog(fog)) {
            const parts = [];
            for (let y = 0; y < mapData.length; y++) {
                if (y > 0) {
                    parts.push('\n');
                }
                const row = mapData[y];
                const fogRow = fog[y] || [];
                for (let x = 0; x < row.length; x++) {
                    const stateName = fogRow[x] || 'visible';
                    const color = FOG_COLORS[stateName] || FOG_COLORS.visible;
                    parts.push(
                        '<span style="color:' + color + '">' +
                        escapeHtml(row[x]) +
                        '</span>'
                    );
                }
            }
            el.innerHTML = parts.join('');
        } else {
            el.textContent = mapData.map(function (row) {
                return row.join('');
            }).join('\n');
        }
    }

    return { render };
})();

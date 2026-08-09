// tile_assets.js — terrain tile registry + image cache (floor / boulder stage 1)
const TileAssets = (function () {
    const GRAPHICS_TERRAIN_ENABLED = true;

    const TERRAIN = {
        '#': { key: 'boulder', url: '/static/tiles/boulder.png' },
        '.': { key: 'floor', url: '/static/tiles/floor.png' },
        '\u2191': { key: 'stairsup', url: '/static/tiles/stairsup.png' }, // ↑
        '\u2193': { key: 'stairsdown', url: '/static/tiles/stairsdown.png' }, // ↓
    };

    /** Cells that sit on walkable floor (draw floor under ASCII). */
    const FLOOR_UNDER = {
        '@': true,
        '&': true,
    };

    const cache = Object.create(null);
    const failed = Object.create(null);
    let preloadStarted = false;
    let allSettled = false;
    const readyCallbacks = [];

    function terrainEntries() {
        const seen = Object.create(null);
        const keys = [];
        Object.keys(TERRAIN).forEach(function (ch) {
            const entry = TERRAIN[ch];
            if (!entry || seen[entry.key]) {
                return;
            }
            seen[entry.key] = true;
            keys.push(entry);
        });
        return keys;
    }

    function isImageReady(img) {
        return !!(img && img.complete && img.naturalWidth);
    }

    function keySettled(key) {
        return isImageReady(cache[key]) || !!failed[key];
    }

    function checkAllSettled() {
        if (allSettled) {
            return true;
        }
        const entries = terrainEntries();
        if (!preloadStarted || !entries.length) {
            return false;
        }
        for (let i = 0; i < entries.length; i++) {
            if (!keySettled(entries[i].key)) {
                return false;
            }
        }
        allSettled = true;
        const cbs = readyCallbacks.splice(0, readyCallbacks.length);
        for (let i = 0; i < cbs.length; i++) {
            cbs[i]();
        }
        return true;
    }

    function setOnReady(fn) {
        if (typeof fn !== 'function') {
            return;
        }
        if (allSettled || checkAllSettled()) {
            fn();
            return;
        }
        readyCallbacks.push(fn);
    }

    function loadOne(key, url) {
        if (cache[key]) {
            return cache[key];
        }
        const img = new Image();
        img.onload = function () {
            checkAllSettled();
        };
        img.onerror = function () {
            failed[key] = true;
            console.warn('TileAssets: failed to load', url);
            checkAllSettled();
        };
        img.src = url;
        cache[key] = img;
        // HTTP cache may complete synchronously
        if (isImageReady(img)) {
            checkAllSettled();
        }
        return img;
    }

    function preload() {
        if (preloadStarted) {
            return;
        }
        preloadStarted = true;
        terrainEntries().forEach(function (entry) {
            loadOne(entry.key, entry.url);
        });
        checkAllSettled();
    }

    function getImage(key) {
        const img = cache[key];
        if (!isImageReady(img)) {
            return null;
        }
        return img;
    }

    /** True once every terrain image has loaded or failed (safe to paint). */
    function isReady() {
        if (!GRAPHICS_TERRAIN_ENABLED) {
            return true;
        }
        return checkAllSettled();
    }

    /**
     * @returns {'boulder'|'floor'|'stairsup'|'stairsdown'|null}
     */
    function terrainKeyForCell(ch) {
        if (!ch) {
            return null;
        }
        if (TERRAIN[ch]) {
            return TERRAIN[ch].key;
        }
        if (FLOOR_UNDER[ch]) {
            return 'floor';
        }
        return null;
    }

    /** Glyph fully replaced by a graphic (no ASCII overlay when PNG drew). */
    function isTerrainOnly(ch) {
        return ch === '#' || ch === '.' || ch === '\u2191' || ch === '\u2193';
    }

    // Start fetch as soon as this script runs (before join / first map paint)
    if (GRAPHICS_TERRAIN_ENABLED) {
        preload();
    }

    return {
        GRAPHICS_TERRAIN_ENABLED,
        TERRAIN,
        preload,
        getImage,
        terrainKeyForCell,
        isTerrainOnly,
        isReady,
        setOnReady,
    };
})();

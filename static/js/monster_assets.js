// monster_assets.js — sprite (map) + portrait (combat) cache by type_id
const MonsterAssets = (function () {
    const GRAPHICS_MONSTERS_ENABLED = true;

    /** Fallback registry when server does not send URLs (Troll first). */
    const DEFAULTS = {
        troll: {
            sprite: '/static/monsters/sprites/troll.png',
            portrait: '/static/monsters/portraits/troll.png',
        },
    };

    const spriteCache = Object.create(null);
    const portraitCache = Object.create(null);
    const failed = Object.create(null);
    const readyCallbacks = [];
    let pending = 0;

    function isImageReady(img) {
        return !!(img && img.complete && img.naturalWidth);
    }

    function notifyReady() {
        if (pending > 0) {
            return;
        }
        const cbs = readyCallbacks.splice(0, readyCallbacks.length);
        for (let i = 0; i < cbs.length; i++) {
            cbs[i]();
        }
    }

    function loadInto(cache, key, url) {
        if (!key || !url) {
            return null;
        }
        const cacheKey = key + '|' + url;
        if (cache[cacheKey]) {
            return cache[cacheKey];
        }
        if (failed[cacheKey]) {
            return null;
        }
        const img = new Image();
        pending += 1;
        img.onload = function () {
            pending = Math.max(0, pending - 1);
            notifyReady();
        };
        img.onerror = function () {
            failed[cacheKey] = true;
            pending = Math.max(0, pending - 1);
            console.warn('MonsterAssets: failed to load', url);
            notifyReady();
        };
        img.src = url;
        cache[cacheKey] = img;
        if (isImageReady(img)) {
            pending = Math.max(0, pending - 1);
            notifyReady();
        }
        return img;
    }

    function urlsFor(typeId, spriteUrl, portraitUrl) {
        const def = DEFAULTS[typeId] || {};
        return {
            sprite: spriteUrl || def.sprite || null,
            portrait: portraitUrl || def.portrait || null,
        };
    }

    function ensureType(typeId, spriteUrl, portraitUrl) {
        if (!GRAPHICS_MONSTERS_ENABLED || !typeId) {
            return;
        }
        const urls = urlsFor(typeId, spriteUrl, portraitUrl);
        if (urls.sprite) {
            loadInto(spriteCache, typeId, urls.sprite);
        }
        if (urls.portrait) {
            loadInto(portraitCache, typeId, urls.portrait);
        }
    }

    function preloadKnown() {
        Object.keys(DEFAULTS).forEach(function (typeId) {
            ensureType(typeId);
        });
    }

    function getSprite(typeId, spriteUrl) {
        if (!GRAPHICS_MONSTERS_ENABLED || !typeId) {
            return null;
        }
        const urls = urlsFor(typeId, spriteUrl, null);
        if (!urls.sprite) {
            return null;
        }
        const img = loadInto(spriteCache, typeId, urls.sprite);
        return isImageReady(img) ? img : null;
    }

    function getPortrait(typeId, portraitUrl) {
        if (!GRAPHICS_MONSTERS_ENABLED || !typeId) {
            return null;
        }
        const urls = urlsFor(typeId, null, portraitUrl);
        if (!urls.portrait) {
            return null;
        }
        const img = loadInto(portraitCache, typeId, urls.portrait);
        return isImageReady(img) ? img : null;
    }

    function setOnReady(fn) {
        if (typeof fn !== 'function') {
            return;
        }
        if (pending <= 0) {
            fn();
            return;
        }
        readyCallbacks.push(fn);
    }

    if (GRAPHICS_MONSTERS_ENABLED) {
        preloadKnown();
    }

    return {
        GRAPHICS_MONSTERS_ENABLED,
        ensureType,
        preloadKnown,
        getSprite,
        getPortrait,
        setOnReady,
    };
})();

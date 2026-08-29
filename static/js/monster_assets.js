// monster_assets.js — sprite (map) + portrait (combat) cache by type_id
const MonsterAssets = (function () {
    const GRAPHICS_MONSTERS_ENABLED = true;

    /** Fallback registry when server does not send URLs (Troll first). */
    const DEFAULTS = {
        troll: {
            sprite: '/static/monsters/sprites/troll.png',
            portrait: '/static/monsters/portraits/troll.png',
            defaultFacing: 'left',
        },
        skeleton: {
            sprite: '/static/monsters/sprites/skeleton.png',
            portrait: '/static/monsters/portraits/skeleton.png',
            defaultFacing: 'left',
        },
    };

    /** One footfall; two per 250ms tile. */
    const WALK_STEP_MS = 125;

    const spriteCache = Object.create(null);
    const portraitCache = Object.create(null);
    const failed = Object.create(null);
    const readyCallbacks = [];
    let pending = 0;
    let flushScheduled = false;

    function isImageReady(img) {
        return !!(img && img.complete && img.naturalWidth);
    }

    /**
     * Monster art loads lazily per type, so subscribers stay registered: a
     * batch that arrives later (new level, new species) must be able to
     * trigger another repaint. Deferred so a burst of loads coalesces into
     * one callback and cannot re-enter a render already in progress.
     */
    function notifyReady() {
        if (pending > 0 || flushScheduled || !readyCallbacks.length) {
            return;
        }
        flushScheduled = true;
        const flush = function () {
            flushScheduled = false;
            if (pending > 0) {
                return;
            }
            for (let i = 0; i < readyCallbacks.length; i++) {
                readyCallbacks[i]();
            }
        };
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(flush);
        } else {
            setTimeout(flush, 0);
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

    function defaultFacing(typeId) {
        const def = DEFAULTS[typeId] || {};
        return def.defaultFacing || 'left';
    }

    /**
     * Procedural step on a single standing sprite (no walk-sheet yet).
     * Returns fractions of the dest box: bob up from feet, squash on plant.
     */
    function walkPose(clipName, elapsedMs) {
        if (clipName !== 'walk') {
            return { bob: 0, scaleX: 1, scaleY: 1 };
        }
        const t = elapsedMs > 0 ? elapsedMs : 0;
        const cycle = (t % WALK_STEP_MS) / WALK_STEP_MS;
        const lift = Math.sin(cycle * Math.PI);
        return {
            bob: lift * 0.12,
            scaleX: 1 + 0.06 * (1 - lift),
            scaleY: 1 - 0.08 * (1 - lift),
        };
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
        readyCallbacks.push(fn);
        notifyReady();
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
        defaultFacing,
        walkPose,
        setOnReady,
    };
})();

// player_assets.js — appearance clips under /static/player/sprites/
const PlayerAssets = (function () {
    const DEFAULT_APPEARANCE = 'peasant';

    const APPEARANCES = {
        peasant: {
            defaultFacing: 'left',
            clips: {
                idle: {
                    frames: ['/static/player/sprites/player_walk1.png'],
                },
                walk: {
                    fps: 12,
                    frames: [
                        '/static/player/sprites/player_walk1.png',
                        '/static/player/sprites/player_walk2.png',
                        '/static/player/sprites/player_walk3.png',
                    ],
                },
            },
        },
    };

    const cache = Object.create(null);
    const readyCallbacks = [];
    let pending = 0;

    function ready(img) {
        return !!(img && img.complete && img.naturalWidth);
    }

    function flushReady() {
        if (pending > 0) return;
        const cbs = readyCallbacks.splice(0, readyCallbacks.length);
        for (let i = 0; i < cbs.length; i++) cbs[i]();
    }

    function load(url) {
        if (!url) return null;
        if (cache[url]) return cache[url];
        const img = new Image();
        pending += 1;
        img.onload = img.onerror = function () {
            pending = Math.max(0, pending - 1);
            if (!img.naturalWidth) console.warn('PlayerAssets: failed', url);
            flushReady();
        };
        img.src = url;
        cache[url] = img;
        if (ready(img)) {
            pending = Math.max(0, pending - 1);
            flushReady();
        }
        return img;
    }

    function getAppearance(appearanceId) {
        return APPEARANCES[appearanceId] || APPEARANCES[DEFAULT_APPEARANCE];
    }

    function defaultFacing(appearanceId) {
        const app = getAppearance(appearanceId);
        return (app && app.defaultFacing) || 'left';
    }

    function framePayload(img) {
        if (!ready(img)) {
            return null;
        }
        return {
            img: img,
            sx: 0,
            sy: 0,
            sw: img.naturalWidth,
            sh: img.naturalHeight,
        };
    }

    function getFrame(appearanceId, clipName, elapsedMs) {
        const app = getAppearance(appearanceId);
        const clips = (app && app.clips) || {};
        let clip = clips[clipName] || clips.idle;
        let frames = clip && clip.frames ? clip.frames : [];
        if (!frames.length && clipName !== 'idle') {
            clip = clips.idle;
            frames = clip && clip.frames ? clip.frames : [];
        }
        if (!frames.length) {
            return null;
        }
        const fps = clip.fps || 6;
        let idx = 0;
        if (frames.length > 1 && fps > 0) {
            const t = elapsedMs > 0 ? elapsedMs : 0;
            idx = Math.floor((t / 1000) * fps) % frames.length;
        }
        const img = load(frames[idx]);
        const payload = framePayload(img);
        if (payload) {
            return payload;
        }
        if (clipName !== 'idle') {
            return getFrame(appearanceId, 'idle', 0);
        }
        return null;
    }

    function preloadAppearance(appearanceId) {
        const app = getAppearance(appearanceId);
        const clips = (app && app.clips) || {};
        Object.keys(clips).forEach(function (name) {
            const frames = clips[name].frames || [];
            for (let i = 0; i < frames.length; i++) {
                load(frames[i]);
            }
        });
    }

    function preload() {
        Object.keys(APPEARANCES).forEach(preloadAppearance);
    }

    function setOnReady(fn) {
        if (typeof fn !== 'function') return;
        if (pending <= 0) { fn(); return; }
        readyCallbacks.push(fn);
    }

    preload();

    return {
        APPEARANCES,
        DEFAULT_APPEARANCE,
        getFrame,
        defaultFacing,
        preload,
        setOnReady,
    };
})();

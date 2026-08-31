// sound.js — silent unlock + preloaded Web Audio playback (no join blip)
//
// iPad Safari often re-suspends AudioContext after Join; resume alone is not
// enough. Re-unlock on every user gesture and tick a silent buffer so unlock
// sticks across devices.
const Sound = (function () {
    let ctx = null;
    let silentBuf = null;
    let gestureBound = false;
    const buffers = {};
    const loading = {};
    const PATHS = {
        hit: '/static/sounds/damage.mp3',
        victory: '/static/sounds/victory.mp3',
        stairs: '/static/sounds/stairs.mp3',
        playerMiss: '/static/sounds/playerMiss.mp3',
        monsterMiss: '/static/sounds/monsterMiss.mp3',
        levelUp: '/static/sounds/levelUp.mp3',
        killmonster: '/static/sounds/killmonster.mp3',
        enterbattle: '/static/sounds/enterbattle.mp3',
        spell: '/static/sounds/spell.mp3',
        runblock: '/static/sounds/runblock.mp3',
        escape: '/static/sounds/escape.mp3',
    };

    function audioContext() {
        if (!ctx) {
            ctx = new (window.AudioContext || window.webkitAudioContext)();
        }
        return ctx;
    }

    function ensureSilentBuffer(c) {
        if (silentBuf) {
            return silentBuf;
        }
        // One sample of silence — start() during a gesture is what iOS wants.
        silentBuf = c.createBuffer(1, 1, c.sampleRate || 22050);
        return silentBuf;
    }

    function tickSilent(c) {
        try {
            const src = c.createBufferSource();
            src.buffer = ensureSilentBuffer(c);
            src.connect(c.destination);
            src.start(0);
        } catch (e) {
            // Ignore — unlock still attempted via resume().
        }
    }

    function unlock() {
        const c = audioContext();
        const after = function () {
            tickSilent(c);
        };
        if (c.state === 'suspended') {
            c.resume().then(after).catch(function () {});
        } else {
            after();
        }
        return c;
    }

    function bindGestureUnlock() {
        if (gestureBound) {
            return;
        }
        gestureBound = true;
        const opts = { capture: true, passive: true };
        const onGesture = function () {
            unlock();
        };
        // pointerdown covers mouse + most touch; touchstart catches older iOS.
        document.addEventListener('pointerdown', onGesture, opts);
        document.addEventListener('touchstart', onGesture, opts);
        document.addEventListener('keydown', onGesture, opts);
    }

    function load(name, url) {
        if (buffers[name]) {
            return Promise.resolve(buffers[name]);
        }
        if (loading[name]) {
            return loading[name];
        }
        loading[name] = fetch(url)
            .then(function (r) {
                return r.arrayBuffer();
            })
            .then(function (data) {
                return audioContext().decodeAudioData(data);
            })
            .then(function (buf) {
                buffers[name] = buf;
                delete loading[name];
                return buf;
            })
            .catch(function () {
                delete loading[name];
                return null;
            });
        return loading[name];
    }

    // Call from a user gesture (Join / Attack). Does not play any audible sound.
    function warm() {
        bindGestureUnlock();
        unlock();
        Object.keys(PATHS).forEach(function (name) {
            load(name, PATHS[name]);
        });
    }

    function start(buf) {
        const c = audioContext();
        const playNow = function () {
            if (c.state === 'suspended') {
                return;
            }
            const src = c.createBufferSource();
            src.buffer = buf;
            const gain = c.createGain();
            gain.gain.value = 0.85;
            src.connect(gain);
            gain.connect(c.destination);
            src.start(c.currentTime);
        };
        // start() while suspended is often dropped; wait for resume first
        if (c.state === 'suspended') {
            c.resume().then(function () {
                tickSilent(c);
                playNow();
            }).catch(function () {});
            return;
        }
        playNow();
    }

    const playGen = {};

    function duration(name) {
        const buf = buffers[name];
        return buf ? buf.duration : 0;
    }

    function play(name, onStart) {
        bindGestureUnlock();
        unlock();
        const url = PATHS[name];
        if (!url) {
            return 0;
        }

        const gen = (playGen[name] = (playGen[name] || 0) + 1);
        const ready = buffers[name];
        if (ready) {
            start(ready);
            if (typeof onStart === 'function') {
                onStart(ready.duration);
            }
            return ready.duration;
        }

        // First play may race preload — wait for decode, then play if still current.
        // Allow a longer window so slower iPad / Render fetches still hear the clip.
        const requestedAt = (typeof performance !== 'undefined' && performance.now)
            ? performance.now() : Date.now();
        load(name, url).then(function (buf) {
            if (!buf || playGen[name] !== gen) {
                return;
            }
            const now = (typeof performance !== 'undefined' && performance.now)
                ? performance.now() : Date.now();
            if (now - requestedAt > 2500) {
                return;
            }
            start(buf);
            if (typeof onStart === 'function') {
                onStart(buf.duration);
            }
        });
        return 0;
    }

    // Install gesture unlock early so the first tap after load re-arms audio.
    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', bindGestureUnlock);
        } else {
            bindGestureUnlock();
        }
    }

    return { warm: warm, play: play, duration: duration, unlock: unlock };
})();

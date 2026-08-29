// sound.js — silent unlock + preloaded Web Audio playback (no join blip)
const Sound = (function () {
    let ctx = null;
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
    };

    function audioContext() {
        if (!ctx) {
            ctx = new (window.AudioContext || window.webkitAudioContext)();
        }
        return ctx;
    }

    function unlock() {
        const c = audioContext();
        if (c.state === 'suspended') {
            c.resume().catch(() => {});
        }
    }

    function load(name, url) {
        if (buffers[name]) {
            return Promise.resolve(buffers[name]);
        }
        if (loading[name]) {
            return loading[name];
        }
        loading[name] = fetch(url)
            .then(r => r.arrayBuffer())
            .then(data => audioContext().decodeAudioData(data))
            .then(buf => {
                buffers[name] = buf;
                delete loading[name];
                return buf;
            })
            .catch(() => {
                delete loading[name];
                return null;
            });
        return loading[name];
    }

    // Call from a user gesture (Join / Attack). Does not play any audible sound.
    function warm() {
        unlock();
        Object.keys(PATHS).forEach(name => {
            load(name, PATHS[name]);
        });
    }

    function start(buf) {
        const c = audioContext();
        const playNow = function () {
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
            c.resume().then(playNow).catch(() => {});
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
        unlock();
        const url = PATHS[name];
        if (!url) return 0;

        const gen = (playGen[name] = (playGen[name] || 0) + 1);
        const ready = buffers[name];
        if (ready) {
            start(ready);
            if (typeof onStart === 'function') onStart(ready.duration);
            return ready.duration;
        }

        // First play may race preload — wait for decode, then play if still current
        const requestedAt = (typeof performance !== 'undefined' && performance.now)
            ? performance.now() : Date.now();
        load(name, url).then(buf => {
            if (!buf || playGen[name] !== gen) return;
            const now = (typeof performance !== 'undefined' && performance.now)
                ? performance.now() : Date.now();
            // Too late to stay in sync with the attack that requested it
            if (now - requestedAt > 500) return;
            start(buf);
            if (typeof onStart === 'function') onStart(buf.duration);
        });
        return 0;
    }

    return { warm, play, duration };
})();

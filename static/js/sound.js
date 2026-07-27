// sound.js — silent unlock + preloaded Web Audio playback (no join blip)
const Sound = (function () {
    let ctx = null;
    const buffers = {};
    const PATHS = {
        hit: '/static/sounds/damage.mp3',
        victory: '/static/sounds/victory.mp3'
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
        return fetch(url)
            .then(r => r.arrayBuffer())
            .then(data => audioContext().decodeAudioData(data))
            .then(buf => { buffers[name] = buf; })
            .catch(() => {});
    }

    // Call from a user gesture (Join / Attack). Does not play any audible sound.
    function warm() {
        unlock();
        Object.keys(PATHS).forEach(name => {
            if (!buffers[name]) {
                load(name, PATHS[name]);
            }
        });
    }

    function play(name) {
        const buf = buffers[name];
        if (!buf) {
            warm();
            return;
        }
        const c = audioContext();
        if (c.state === 'suspended') {
            c.resume().catch(() => {});
        }
        const src = c.createBufferSource();
        src.buffer = buf;
        const gain = c.createGain();
        gain.gain.value = 0.85;
        src.connect(gain);
        gain.connect(c.destination);
        src.start(0);
    }

    return { warm, play };
})();

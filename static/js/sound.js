// sound.js — silent unlock + preloaded Web Audio playback (no join blip)
const Sound = (function () {
    let ctx = null;
    const buffers = {};
    const loading = {};
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

    function play(name) {
        unlock();
        const url = PATHS[name];
        if (!url) return;

        const ready = buffers[name];
        if (ready) {
            start(ready);
            return;
        }

        // First play may race preload — wait for decode, then play
        load(name, url).then(buf => {
            if (buf) start(buf);
        });
    }

    return { warm, play };
})();

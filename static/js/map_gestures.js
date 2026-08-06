// map_gestures.js — map-pane-only pinch / wheel → discrete zoom (no drag-pan)
const MapGestures = (function () {
    const PINCH_THRESHOLD = 1.12;
    const WHEEL_COOLDOWN_MS = 80;

    let paneEl = null;
    let active = false;
    let pinchStartDist = 0;
    let pinchBaseIndex = 0;
    let lastWheelAt = 0;

    function distance(t0, t1) {
        const dx = t0.clientX - t1.clientX;
        const dy = t0.clientY - t1.clientY;
        return Math.hypot(dx, dy);
    }

    function onTouchStart(e) {
        if (!active || e.touches.length !== 2) {
            return;
        }
        e.preventDefault();
        pinchStartDist = distance(e.touches[0], e.touches[1]);
        pinchBaseIndex = MapView.getState().zoomIndex;
    }

    function onTouchMove(e) {
        if (!active || e.touches.length !== 2 || pinchStartDist <= 0) {
            return;
        }
        e.preventDefault();
        const dist = distance(e.touches[0], e.touches[1]);
        const ratio = dist / pinchStartDist;
        let steps = 0;
        if (ratio >= PINCH_THRESHOLD) {
            steps = Math.floor(Math.log(ratio) / Math.log(PINCH_THRESHOLD));
        } else if (ratio <= 1 / PINCH_THRESHOLD) {
            steps = -Math.floor(Math.log(1 / ratio) / Math.log(PINCH_THRESHOLD));
        }
        if (steps !== 0) {
            MapView.setZoomIndex(pinchBaseIndex + steps);
        }
    }

    function onTouchEnd(e) {
        if (e.touches.length < 2) {
            pinchStartDist = 0;
        }
    }

    function onWheel(e) {
        if (!active) {
            return;
        }
        e.preventDefault();
        const now = Date.now();
        if (now - lastWheelAt < WHEEL_COOLDOWN_MS) {
            return;
        }
        lastWheelAt = now;
        if (e.deltaY < 0) {
            MapView.zoomBy(1);
        } else if (e.deltaY > 0) {
            MapView.zoomBy(-1);
        }
    }

    function init(options) {
        options = options || {};
        paneEl = options.paneEl || document.getElementById('map-pane');
        if (!paneEl) {
            return;
        }
        active = true;
        paneEl.addEventListener('touchstart', onTouchStart, { passive: false });
        paneEl.addEventListener('touchmove', onTouchMove, { passive: false });
        paneEl.addEventListener('touchend', onTouchEnd, { passive: true });
        paneEl.addEventListener('touchcancel', onTouchEnd, { passive: true });
        paneEl.addEventListener('wheel', onWheel, { passive: false });
    }

    function destroy() {
        active = false;
        if (!paneEl) {
            return;
        }
        paneEl.removeEventListener('touchstart', onTouchStart);
        paneEl.removeEventListener('touchmove', onTouchMove);
        paneEl.removeEventListener('touchend', onTouchEnd);
        paneEl.removeEventListener('touchcancel', onTouchEnd);
        paneEl.removeEventListener('wheel', onWheel);
    }

    return { init, destroy };
})();

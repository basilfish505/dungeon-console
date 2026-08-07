// map_gestures.js — map-pane pinch/wheel zoom + one-finger/mouse drag pan
const MapGestures = (function () {
    const PINCH_THRESHOLD = 1.12;
    const WHEEL_COOLDOWN_MS = 80;
    const PAN_THRESHOLD_PX = 6;

    let paneEl = null;
    let active = false;
    let pinchStartDist = 0;
    let pinchBaseIndex = 0;
    let lastWheelAt = 0;

    let pointerId = null;
    let panLastX = 0;
    let panLastY = 0;
    let panAccX = 0;
    let panAccY = 0;
    let panning = false;

    function distance(t0, t1) {
        const dx = t0.clientX - t1.clientX;
        const dy = t0.clientY - t1.clientY;
        return Math.hypot(dx, dy);
    }

    function endPan() {
        pointerId = null;
        panning = false;
        panAccX = 0;
        panAccY = 0;
    }

    function midpoint(t0, t1) {
        return {
            clientX: (t0.clientX + t1.clientX) / 2,
            clientY: (t0.clientY + t1.clientY) / 2,
        };
    }

    function onTouchStart(e) {
        if (!active) {
            return;
        }
        if (e.touches.length === 2) {
            endPan();
            e.preventDefault();
            pinchStartDist = distance(e.touches[0], e.touches[1]);
            pinchBaseIndex = MapView.getState().zoomIndex;
        }
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
            const before = MapView.getState().zoomIndex;
            const focus = midpoint(e.touches[0], e.touches[1]);
            MapView.setZoomIndex(pinchBaseIndex + steps, focus);
            const after = MapView.getState().zoomIndex;
            // Ratchet baseline after each committed step so finger-lift jitter
            // (distance shrinks as digits leave the screen) cannot rewind zoom.
            if (after !== before || after !== pinchBaseIndex) {
                pinchBaseIndex = after;
                pinchStartDist = dist;
            }
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
        // Zoom toward cursor (falls back to pane centre inside MapView if needed)
        const focus = { clientX: e.clientX, clientY: e.clientY };
        if (e.deltaY < 0) {
            MapView.zoomBy(1, focus);
        } else if (e.deltaY > 0) {
            MapView.zoomBy(-1, focus);
        }
    }

    function onPointerDown(e) {
        if (!active || !paneEl) {
            return;
        }
        // One pointer only; ignore while pinching
        if (pinchStartDist > 0 || (e.pointerType === 'touch' && e.isPrimary === false)) {
            return;
        }
        if (pointerId !== null) {
            return;
        }
        pointerId = e.pointerId;
        panLastX = e.clientX;
        panLastY = e.clientY;
        panAccX = 0;
        panAccY = 0;
        panning = false;
        try {
            paneEl.setPointerCapture(e.pointerId);
        } catch (err) {
            /* ignore */
        }
    }

    function onPointerMove(e) {
        if (!active || e.pointerId !== pointerId) {
            return;
        }
        if (pinchStartDist > 0) {
            return;
        }
        const dx = e.clientX - panLastX;
        const dy = e.clientY - panLastY;
        panLastX = e.clientX;
        panLastY = e.clientY;
        panAccX += dx;
        panAccY += dy;

        if (!panning) {
            if (Math.hypot(panAccX, panAccY) < PAN_THRESHOLD_PX) {
                return;
            }
            panning = true;
        }

        e.preventDefault();
        const st = MapView.getState();
        const tw = Math.max(1, st.tileW);
        const th = Math.max(1, st.tileH);

        // Drag map with finger: content follows pointer → camera opposite
        let tileDx = 0;
        let tileDy = 0;
        while (panAccX >= tw) {
            panAccX -= tw;
            tileDx -= 1;
        }
        while (panAccX <= -tw) {
            panAccX += tw;
            tileDx += 1;
        }
        while (panAccY >= th) {
            panAccY -= th;
            tileDy -= 1;
        }
        while (panAccY <= -th) {
            panAccY += th;
            tileDy += 1;
        }
        if (tileDx !== 0 || tileDy !== 0) {
            MapView.panBy(tileDy, tileDx);
        }
    }

    function onPointerUp(e) {
        if (e.pointerId === pointerId) {
            endPan();
        }
    }

    function init(options) {
        options = options || {};
        paneEl = options.paneEl || document.getElementById('map-pane');
        if (!paneEl) {
            return;
        }
        active = true;
        paneEl.style.touchAction = 'none';
        paneEl.addEventListener('touchstart', onTouchStart, { passive: false });
        paneEl.addEventListener('touchmove', onTouchMove, { passive: false });
        paneEl.addEventListener('touchend', onTouchEnd, { passive: true });
        paneEl.addEventListener('touchcancel', onTouchEnd, { passive: true });
        paneEl.addEventListener('wheel', onWheel, { passive: false });
        paneEl.addEventListener('pointerdown', onPointerDown);
        paneEl.addEventListener('pointermove', onPointerMove, { passive: false });
        paneEl.addEventListener('pointerup', onPointerUp);
        paneEl.addEventListener('pointercancel', onPointerUp);
        paneEl.addEventListener('lostpointercapture', onPointerUp);
    }

    function destroy() {
        active = false;
        endPan();
        if (!paneEl) {
            return;
        }
        paneEl.removeEventListener('touchstart', onTouchStart);
        paneEl.removeEventListener('touchmove', onTouchMove);
        paneEl.removeEventListener('touchend', onTouchEnd);
        paneEl.removeEventListener('touchcancel', onTouchEnd);
        paneEl.removeEventListener('wheel', onWheel);
        paneEl.removeEventListener('pointerdown', onPointerDown);
        paneEl.removeEventListener('pointermove', onPointerMove);
        paneEl.removeEventListener('pointerup', onPointerUp);
        paneEl.removeEventListener('pointercancel', onPointerUp);
        paneEl.removeEventListener('lostpointercapture', onPointerUp);
    }

    return { init, destroy };
})();

// map_gestures.js — two-finger pan + pinch/wheel zoom + one-finger swipe-to-walk + tap inspect
const MapGestures = (function () {
    const PINCH_THRESHOLD = 1.12;
    const WHEEL_COOLDOWN_MS = 80;
    const PAN_THRESHOLD_PX = 6;
    const WALK_THRESHOLD_PX = 14;
    /** Recent finger travel before the walk direction updates (allows zigzags). */
    const TURN_THRESHOLD_PX = 16;
    const DELTA_TO_DIR = {
        '-1,0': 'n',
        '-1,1': 'ne',
        '0,1': 'e',
        '1,1': 'se',
        '1,0': 's',
        '1,-1': 'sw',
        '0,-1': 'west',
        '-1,-1': 'nw',
    };

    let paneEl = null;
    let active = false;
    let pinchStartDist = 0;
    let pinchBaseIndex = 0;
    let lastWheelAt = 0;

    const activePointers = new Map();
    let twoFingerIds = null;
    let twoFinger = false;
    let lastMidX = 0;
    let lastMidY = 0;
    /** After a two-finger gesture, ignore walk until all fingers lift. */
    let inhibitWalk = false;

    let pointerId = null;
    let pointerType = null;
    let panLastX = 0;
    let panLastY = 0;
    let panAccX = 0;
    let panAccY = 0;
    let panning = false;

    let downX = 0;
    let downY = 0;
    let walkLastX = 0;
    let walkLastY = 0;
    let walkAccX = 0;
    let walkAccY = 0;
    let walkActive = false;
    let skipInspect = false;

    function inspectUiOpen() {
        if (typeof InspectUI !== 'undefined' && InspectUI.isOpen()) {
            return true;
        }
        if (typeof InventoryUI !== 'undefined' && InventoryUI.isOpen()) {
            return true;
        }
        return false;
    }

    function isFinger(type) {
        return type === 'touch' || type === 'pen';
    }

    function vectorToDir(dx, dy) {
        if (dx === 0 && dy === 0) {
            return null;
        }
        const ax = Math.abs(dx);
        const ay = Math.abs(dy);
        // tan(22.5°) ≈ 0.414 — eight 45° sectors
        const sx = ax > ay * 0.414 ? (dx > 0 ? 1 : -1) : 0;
        const sy = ay > ax * 0.414 ? (dy > 0 ? 1 : -1) : 0;
        return DELTA_TO_DIR[sy + ',' + sx] || null;
    }

    function stopWalkStick() {
        walkActive = false;
        walkAccX = 0;
        walkAccY = 0;
        if (typeof MovementController !== 'undefined' && MovementController.setStickDir) {
            MovementController.setStickDir(null);
        }
    }

    function resetPointerState() {
        pointerId = null;
        pointerType = null;
        panning = false;
        walkActive = false;
        panAccX = 0;
        panAccY = 0;
        walkAccX = 0;
        walkAccY = 0;
    }

    function applyPanPixels(dx, dy) {
        panAccX += dx;
        panAccY += dy;
        if (!panning) {
            if (Math.hypot(panAccX, panAccY) < PAN_THRESHOLD_PX) {
                return;
            }
            panning = true;
        }
        const st = MapView.getState();
        const tw = Math.max(1, st.tileW);
        const th = Math.max(1, st.tileH);
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

    function fingerEntries() {
        const list = [];
        activePointers.forEach(function (p, id) {
            if (isFinger(p.type)) {
                list.push({ id: id, x: p.x, y: p.y });
            }
        });
        return list;
    }

    function endTwoFinger() {
        twoFinger = false;
        twoFingerIds = null;
        pinchStartDist = 0;
        panning = false;
        panAccX = 0;
        panAccY = 0;
    }

    function beginTwoFinger(fingers) {
        stopWalkStick();
        resetPointerState();
        skipInspect = true;
        inhibitWalk = true;
        twoFinger = true;
        twoFingerIds = [fingers[0].id, fingers[1].id];
        const a = fingers[0];
        const b = fingers[1];
        pinchStartDist = Math.hypot(a.x - b.x, a.y - b.y);
        pinchBaseIndex = MapView.getState().zoomIndex;
        lastMidX = (a.x + b.x) / 2;
        lastMidY = (a.y + b.y) / 2;
        panAccX = 0;
        panAccY = 0;
        panning = false;
    }

    function handleTwoFingerMove() {
        if (!twoFingerIds) {
            return;
        }
        const a = activePointers.get(twoFingerIds[0]);
        const b = activePointers.get(twoFingerIds[1]);
        if (!a || !b) {
            endTwoFinger();
            return;
        }
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinchStartDist > 0) {
            const ratio = dist / pinchStartDist;
            let steps = 0;
            if (ratio >= PINCH_THRESHOLD) {
                steps = Math.floor(Math.log(ratio) / Math.log(PINCH_THRESHOLD));
            } else if (ratio <= 1 / PINCH_THRESHOLD) {
                steps = -Math.floor(Math.log(1 / ratio) / Math.log(PINCH_THRESHOLD));
            }
            if (steps !== 0) {
                const before = MapView.getState().zoomIndex;
                const focus = {
                    clientX: (a.x + b.x) / 2,
                    clientY: (a.y + b.y) / 2,
                };
                MapView.setZoomIndex(pinchBaseIndex + steps, focus);
                const after = MapView.getState().zoomIndex;
                if (after !== before || after !== pinchBaseIndex) {
                    pinchBaseIndex = after;
                    pinchStartDist = dist;
                }
            }
        }
        const midX = (a.x + b.x) / 2;
        const midY = (a.y + b.y) / 2;
        applyPanPixels(midX - lastMidX, midY - lastMidY);
        lastMidX = midX;
        lastMidY = midY;
    }

    function preventBrowserGesture(e) {
        if (e.touches && e.touches.length >= 2) {
            e.preventDefault();
        }
    }

    function onWheel(e) {
        if (!active || inspectUiOpen()) {
            return;
        }
        e.preventDefault();
        const now = Date.now();
        if (now - lastWheelAt < WHEEL_COOLDOWN_MS) {
            return;
        }
        lastWheelAt = now;
        const focus = { clientX: e.clientX, clientY: e.clientY };
        if (e.deltaY < 0) {
            MapView.zoomBy(1, focus);
        } else if (e.deltaY > 0) {
            MapView.zoomBy(-1, focus);
        }
    }

    function handleWalkMove(e) {
        const dx = e.clientX - walkLastX;
        const dy = e.clientY - walkLastY;
        walkLastY = e.clientY;
        walkLastX = e.clientX;
        walkAccX += dx;
        walkAccY += dy;

        if (!walkActive) {
            if (Math.hypot(e.clientX - downX, e.clientY - downY) < WALK_THRESHOLD_PX) {
                return;
            }
            walkActive = true;
            skipInspect = true;
            const dir = vectorToDir(e.clientX - downX, e.clientY - downY);
            if (typeof MovementController !== 'undefined' && MovementController.setStickDir) {
                MovementController.setStickDir(dir);
            }
            walkAccX = 0;
            walkAccY = 0;
            return;
        }

        if (Math.hypot(walkAccX, walkAccY) < TURN_THRESHOLD_PX) {
            return;
        }
        const dir = vectorToDir(walkAccX, walkAccY);
        if (typeof MovementController !== 'undefined' && MovementController.setStickDir) {
            MovementController.setStickDir(dir);
        }
        walkAccX = 0;
        walkAccY = 0;
    }

    function handleMousePan(e) {
        const dx = e.clientX - panLastX;
        const dy = e.clientY - panLastY;
        panLastX = e.clientX;
        panLastY = e.clientY;
        applyPanPixels(dx, dy);
        if (panning) {
            e.preventDefault();
            skipInspect = true;
        }
    }

    function beginOnePointer(e) {
        pointerId = e.pointerId;
        pointerType = e.pointerType;
        downX = e.clientX;
        downY = e.clientY;
        panLastX = e.clientX;
        panLastY = e.clientY;
        walkLastX = e.clientX;
        walkLastY = e.clientY;
        panAccX = 0;
        panAccY = 0;
        walkAccX = 0;
        walkAccY = 0;
        panning = false;
        walkActive = false;
        skipInspect = false;
        try {
            paneEl.setPointerCapture(e.pointerId);
        } catch (err) {
            /* ignore */
        }
    }

    function onPointerDown(e) {
        if (!active || !paneEl || inspectUiOpen()) {
            return;
        }
        e.preventDefault();
        activePointers.set(e.pointerId, {
            x: e.clientX,
            y: e.clientY,
            type: e.pointerType,
        });
        try {
            paneEl.setPointerCapture(e.pointerId);
        } catch (err) {
            /* ignore */
        }

        const fingers = fingerEntries();
        if (fingers.length >= 2) {
            if (!twoFinger) {
                beginTwoFinger(fingers);
            }
            return;
        }
        if (twoFinger || inhibitWalk && isFinger(e.pointerType)) {
            return;
        }
        if (pointerId !== null) {
            return;
        }
        beginOnePointer(e);
    }

    function onPointerMove(e) {
        const rec = activePointers.get(e.pointerId);
        if (rec) {
            rec.x = e.clientX;
            rec.y = e.clientY;
        }
        if (!active || inspectUiOpen()) {
            return;
        }
        if (twoFinger) {
            e.preventDefault();
            handleTwoFingerMove();
            return;
        }
        if (e.pointerId !== pointerId) {
            return;
        }
        if (isFinger(pointerType)) {
            e.preventDefault();
            handleWalkMove(e);
        } else {
            handleMousePan(e);
        }
    }

    function finishOnePointer(e) {
        if (e.pointerId !== pointerId) {
            return;
        }
        const wasWalk = walkActive;
        const wasPan = panning;
        const type = pointerType;
        const upX = e.clientX;
        const upY = e.clientY;
        const startX = downX;
        const startY = downY;
        const allowInspect = e.type !== 'lostpointercapture' && e.type !== 'pointercancel';
        const flickDx = upX - startX;
        const flickDy = upY - startY;
        const flickDist = Math.hypot(flickDx, flickDy);

        stopWalkStick();
        resetPointerState();

        if (inspectUiOpen() || twoFinger) {
            return;
        }

        if (!wasWalk && !wasPan && allowInspect && isFinger(type)
                && flickDist >= WALK_THRESHOLD_PX) {
            const dir = vectorToDir(flickDx, flickDy);
            if (dir && typeof MovementController !== 'undefined' && MovementController.pressDir) {
                MovementController.pressDir(dir);
                MovementController.releaseDir(dir);
            }
            return;
        }

        if (!wasWalk && !wasPan && allowInspect && !skipInspect
                && typeof MapInspect !== 'undefined' && MapInspect.tryInspectAt) {
            MapInspect.tryInspectAt(upX, upY);
        }
    }

    function onPointerUp(e) {
        activePointers.delete(e.pointerId);
        if (twoFingerIds && (e.pointerId === twoFingerIds[0] || e.pointerId === twoFingerIds[1])) {
            endTwoFinger();
        }
        if (activePointers.size === 0) {
            inhibitWalk = false;
        }
        finishOnePointer(e);
    }

    function init(options) {
        options = options || {};
        paneEl = options.paneEl || document.getElementById('map-pane');
        if (!paneEl) {
            return;
        }
        active = true;
        paneEl.style.touchAction = 'none';
        paneEl.addEventListener('touchstart', preventBrowserGesture, { passive: false });
        paneEl.addEventListener('touchmove', preventBrowserGesture, { passive: false });
        paneEl.addEventListener('wheel', onWheel, { passive: false });
        paneEl.addEventListener('pointerdown', onPointerDown);
        paneEl.addEventListener('pointermove', onPointerMove, { passive: false });
        paneEl.addEventListener('pointerup', onPointerUp);
        paneEl.addEventListener('pointercancel', onPointerUp);
        paneEl.addEventListener('lostpointercapture', onPointerUp);
    }

    function destroy() {
        active = false;
        stopWalkStick();
        resetPointerState();
        endTwoFinger();
        inhibitWalk = false;
        activePointers.clear();
        if (!paneEl) {
            return;
        }
        paneEl.removeEventListener('touchstart', preventBrowserGesture);
        paneEl.removeEventListener('touchmove', preventBrowserGesture);
        paneEl.removeEventListener('wheel', onWheel);
        paneEl.removeEventListener('pointerdown', onPointerDown);
        paneEl.removeEventListener('pointermove', onPointerMove);
        paneEl.removeEventListener('pointerup', onPointerUp);
        paneEl.removeEventListener('pointercancel', onPointerUp);
        paneEl.removeEventListener('lostpointercapture', onPointerUp);
    }

    return { init, destroy };
})();

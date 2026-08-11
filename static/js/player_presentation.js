// player_presentation.js — visual waypoint tween + facing + clips (client-only)
const PlayerPresentation = (function () {
    const MOVE_MS = 250;
    /** Send the next step this many ms before the current tween ends (seamless hold-to-walk). */
    const PIPELINE_LEAD_MS = 80;
    /** Safety: revert optimistic step if no move_result arrives. */
    const ACK_MS = 600;

    const DIR_DELTA = {
        w: { dy: -1, dx: 0 },
        s: { dy: 1, dx: 0 },
        a: { dy: 0, dx: -1 },
        d: { dy: 0, dx: 1 },
    };

    const actors = Object.create(null);
    /** id -> timestamp until which a sent move is awaiting move_result */
    const localAckUntil = Object.create(null);
    let rafId = null;
    let onFrame = null;

    function lerp(a, b, t) {
        return a + (b - a) * t;
    }

    function makeActor(id, appearanceId, sprite) {
        return {
            id: id,
            /** Latest intent (optimistic or confirmed). */
            tileY: 0,
            tileX: 0,
            /** Last server-confirmed tile — used to revert failed predictions. */
            confirmedY: 0,
            confirmedX: 0,
            visualY: 0,
            visualX: 0,
            fromY: 0,
            fromX: 0,
            toY: 0,
            toX: 0,
            startMs: 0,
            moving: false,
            queue: [],
            facing: 'left',
            clip: 'idle',
            clipStartMs: 0,
            onArrive: null,
            appearanceId: appearanceId || 'peasant',
            sprite: sprite || null,
            dungeonLevel: null,
            /** Unconfirmed optimistic destination, or null. */
            predicted: null,
        };
    }

    function fireArrive(actor) {
        const cb = actor.onArrive;
        actor.onArrive = null;
        if (typeof cb === 'function') {
            cb();
        }
    }

    function setIdle(actor, y, x, now) {
        actor.visualY = y;
        actor.visualX = x;
        actor.fromY = y;
        actor.fromX = x;
        actor.toY = y;
        actor.toX = x;
        actor.moving = false;
        actor.clip = 'idle';
        actor.clipStartMs = now;
    }

    function beginSegment(actor, toY, toX, now) {
        actor.fromY = actor.visualY;
        actor.fromX = actor.visualX;
        actor.toY = toY;
        actor.toX = toX;
        actor.startMs = now;
        actor.moving = true;
        actor.clip = 'walk';
        actor.clipStartMs = now;
    }

    function advanceQueue(actor, now) {
        if (actor.queue.length === 0) {
            setIdle(actor, actor.tileY, actor.tileX, now);
            fireArrive(actor);
            return;
        }
        const next = actor.queue.shift();
        beginSegment(actor, next.y, next.x, now);
    }

    function sampleVisual(actor, now) {
        if (!actor.moving) {
            return;
        }
        const t = Math.min(1, (now - actor.startMs) / MOVE_MS);
        actor.visualY = lerp(actor.fromY, actor.toY, t);
        actor.visualX = lerp(actor.fromX, actor.toX, t);
        if (t >= 1) {
            actor.visualY = actor.toY;
            actor.visualX = actor.toX;
            advanceQueue(actor, now);
        }
    }

    function segmentProgress(actor, now) {
        if (!actor.moving) {
            return 1;
        }
        return Math.min(1, (now - actor.startMs) / MOVE_MS);
    }

    function snap(actor, tileY, tileX, now) {
        actor.tileY = tileY;
        actor.tileX = tileX;
        actor.confirmedY = tileY;
        actor.confirmedX = tileX;
        actor.queue = [];
        actor.predicted = null;
        setIdle(actor, tileY, tileX, now);
        fireArrive(actor);
    }

    function snapTo(id, tileY, tileX) {
        const actor = actors[String(id)];
        const now = performance.now();
        if (!actor) {
            return;
        }
        actor.onArrive = null;
        delete localAckUntil[String(id)];
        snap(actor, tileY | 0, tileX | 0, now);
    }

    /**
     * Cancel an optimistic step and return the sprite to the last confirmed tile.
     */
    function revertPrediction(actor, now) {
        actor.predicted = null;
        actor.queue = [];
        actor.onArrive = null;
        const ty = actor.confirmedY;
        const tx = actor.confirmedX;
        actor.tileY = ty;
        actor.tileX = tx;
        const dist = Math.max(Math.abs(actor.visualY - ty), Math.abs(actor.visualX - tx));
        if (dist < 0.05) {
            setIdle(actor, ty, tx, now);
            return;
        }
        updateFacing(actor, ty - actor.visualY, tx - actor.visualX);
        beginSegment(actor, ty, tx, now);
        kick();
    }

    function expireStaleAcks(now) {
        for (const id in localAckUntil) {
            if (now < localAckUntil[id]) {
                continue;
            }
            delete localAckUntil[id];
            const actor = actors[id];
            if (actor && actor.predicted) {
                revertPrediction(actor, now);
            }
        }
    }

    /**
     * Walk from current visual pos to a tile, then run onDone.
     * Used for stair approach on the old map before swapping levels.
     */
    function walkToThen(id, tileY, tileX, onDone) {
        id = String(id);
        const actor = actors[id];
        const now = performance.now();
        tileY = tileY | 0;
        tileX = tileX | 0;
        if (!actor) {
            if (typeof onDone === 'function') {
                onDone();
            }
            return;
        }
        delete localAckUntil[id];
        actor.predicted = null;
        actor.queue = [];
        actor.onArrive = typeof onDone === 'function' ? onDone : null;
        updateFacing(actor, tileY - actor.visualY, tileX - actor.visualX);
        actor.tileY = tileY;
        actor.tileX = tileX;
        actor.confirmedY = tileY;
        actor.confirmedX = tileX;
        const dist = Math.max(Math.abs(tileY - actor.visualY), Math.abs(tileX - actor.visualX));
        if (dist < 0.05) {
            snap(actor, tileY, tileX, now);
            return;
        }
        beginSegment(actor, tileY, tileX, now);
        kick();
    }

    function updateFacing(actor, dy, dx) {
        if (dx < 0) {
            actor.facing = 'left';
        } else if (dx > 0) {
            actor.facing = 'right';
        }
    }

    function headingMatches(actor, tileY, tileX) {
        if (actor.moving && actor.toY === tileY && actor.toX === tileX) {
            return true;
        }
        for (let i = 0; i < actor.queue.length; i++) {
            const q = actor.queue[i];
            if (q.y === tileY && q.x === tileX) {
                return true;
            }
        }
        return Math.abs(actor.visualY - tileY) < 0.05 && Math.abs(actor.visualX - tileX) < 0.05;
    }

    function confirmTile(actor, tileY, tileX) {
        actor.tileY = tileY;
        actor.tileX = tileX;
        actor.confirmedY = tileY;
        actor.confirmedX = tileX;
        actor.predicted = null;
    }

    function sync(entities, cameraY, cameraX, localPlayer) {
        const now = performance.now();
        expireStaleAcks(now);
        const seen = Object.create(null);
        const camY = cameraY | 0;
        const camX = cameraX | 0;
        const list = entities || [];
        const localId = localPlayer && localPlayer.id != null ? String(localPlayer.id) : null;
        const localPos = localPlayer && localPlayer.pos ? localPlayer.pos : null;

        for (let i = 0; i < list.length; i++) {
            const e = list[i];
            if (!e || e.kind !== 'player' || e.id == null || e.id === '') {
                continue;
            }
            const id = String(e.id);
            let tileY = camY + (e.vy | 0);
            let tileX = camX + (e.vx | 0);
            // Absolute pos is stable across zoom/pan; vy/vx are camera-relative
            if (localId && id === localId && localPos) {
                tileY = localPos[0] | 0;
                tileX = localPos[1] | 0;
            }
            seen[id] = true;

            let actor = actors[id];
            if (!actor) {
                actor = makeActor(id, e.appearance_id, e.sprite);
                actors[id] = actor;
                snap(actor, tileY, tileX, now);
                continue;
            }

            actor.appearanceId = e.appearance_id || actor.appearanceId;
            if (e.sprite) {
                actor.sprite = e.sprite;
            }

            const newLevel = localPlayer && localPlayer.dungeon_level;
            if (id === localId && actor.dungeonLevel != null && newLevel != null
                && (newLevel | 0) !== actor.dungeonLevel) {
                // Level already applied by MapView — never tween on the new floor
                actor.dungeonLevel = newLevel | 0;
                delete localAckUntil[id];
                snap(actor, tileY, tileX, now);
                continue;
            }
            if (id === localId && newLevel != null) {
                actor.dungeonLevel = newLevel | 0;
            }

            // While an optimistic step is in flight, ignore stale snapshots that
            // still show the old tile. Confirm only when server matches prediction.
            if (id === localId && actor.predicted) {
                if (tileY === actor.predicted.y && tileX === actor.predicted.x) {
                    confirmTile(actor, tileY, tileX);
                    delete localAckUntil[id];
                }
                continue;
            }

            if (actor.confirmedY === tileY && actor.confirmedX === tileX
                && actor.tileY === tileY && actor.tileX === tileX) {
                continue;
            }

            const dy = tileY - actor.tileY;
            const dx = tileX - actor.tileX;
            const dist = Math.max(Math.abs(dy), Math.abs(dx));
            updateFacing(actor, dy, dx);
            confirmTile(actor, tileY, tileX);
            delete localAckUntil[id];

            if (dist > 1) {
                snap(actor, tileY, tileX, now);
                continue;
            }

            if (dist === 0 || headingMatches(actor, tileY, tileX)) {
                continue;
            }

            actor.queue = [];
            beginSegment(actor, tileY, tileX, now);
            kick();
        }

        for (const id in actors) {
            if (!seen[id]) {
                delete actors[id];
                delete localAckUntil[id];
            }
        }
    }

    function actorBusy(actor) {
        return !!(actor && (actor.moving || actor.queue.length));
    }

    function anyMoving(now) {
        now = now == null ? performance.now() : now;
        expireStaleAcks(now);
        for (const id in actors) {
            if (actorBusy(actors[id])) {
                return true;
            }
        }
        return false;
    }

    function canPipeline(actor, now) {
        if (!actor) {
            return false;
        }
        if (actor.predicted) {
            return false;
        }
        if (actor.queue.length > 0) {
            return false;
        }
        if (!actor.moving) {
            return true;
        }
        const remaining = MOVE_MS - (now - actor.startMs);
        return remaining <= PIPELINE_LEAD_MS;
    }

    function isBusy(id) {
        if (id == null || id === '') {
            return false;
        }
        id = String(id);
        const now = performance.now();
        expireStaleAcks(now);
        return !canPipeline(actors[id], now);
    }

    /**
     * Call before sending a local move. Starts the walk tween immediately
     * (client-side prediction). Returns false if still busy / awaiting ack.
     */
    function beginLocalStep(id, direction) {
        if (id == null || id === '') {
            return false;
        }
        id = String(id);
        const delta = DIR_DELTA[direction];
        if (!delta) {
            return false;
        }
        const now = performance.now();
        expireStaleAcks(now);
        const actor = actors[id];
        if (!actor || !canPipeline(actor, now)) {
            return false;
        }

        const toY = actor.tileY + delta.dy;
        const toX = actor.tileX + delta.dx;
        actor.predicted = { y: toY, x: toX };
        actor.tileY = toY;
        actor.tileX = toX;
        localAckUntil[id] = now + ACK_MS;
        updateFacing(actor, delta.dy, delta.dx);

        if (actor.moving || actor.queue.length) {
            actor.queue.push({ y: toY, x: toX });
        } else {
            beginSegment(actor, toY, toX, now);
        }
        kick();
        return true;
    }

    /**
     * Server ack for a local move attempt. If the player did not change tiles
     * (blocked wall, combat bump, etc.), revert the optimistic tween.
     */
    function ackLocalStep(id, moved, pos) {
        if (id == null || id === '') {
            return;
        }
        id = String(id);
        const actor = actors[id];
        const now = performance.now();
        delete localAckUntil[id];
        if (!actor || !actor.predicted) {
            return;
        }
        if (moved && pos && pos.length >= 2) {
            const py = pos[0] | 0;
            const px = pos[1] | 0;
            if (actor.predicted.y === py && actor.predicted.x === px) {
                confirmTile(actor, py, px);
                return;
            }
        }
        revertPrediction(actor, now);
    }

    function sample(now) {
        now = now == null ? performance.now() : now;
        expireStaleAcks(now);
        const out = [];
        for (const id in actors) {
            const actor = actors[id];
            sampleVisual(actor, now);
            const progress = actor.moving ? segmentProgress(actor, now) : 0;
            out.push({
                id: actor.id,
                visualY: actor.visualY,
                visualX: actor.visualX,
                facing: actor.facing,
                clip: actor.clip,
                clipElapsedMs: now - actor.clipStartMs,
                moveProgress: progress,
                appearanceId: actor.appearanceId,
                sprite: actor.sprite,
            });
        }
        return out;
    }

    function setClip(id, clipName) {
        const actor = actors[String(id)];
        if (!actor || !clipName) {
            return;
        }
        actor.clip = clipName;
        actor.clipStartMs = performance.now();
    }

    function setOnFrame(fn) {
        onFrame = typeof fn === 'function' ? fn : null;
    }

    function kick() {
        if (rafId !== null) {
            return;
        }
        function tick() {
            rafId = null;
            if (onFrame) {
                onFrame();
            }
            if (anyMoving()) {
                rafId = requestAnimationFrame(tick);
            }
        }
        rafId = requestAnimationFrame(tick);
    }

    return {
        MOVE_MS,
        sync,
        sample,
        anyMoving,
        isBusy,
        beginLocalStep,
        ackLocalStep,
        walkToThen,
        snapTo,
        setClip,
        setOnFrame,
        kick,
    };
})();

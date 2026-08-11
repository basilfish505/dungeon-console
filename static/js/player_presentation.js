// player_presentation.js — visual waypoint tween + facing + clips (client-only)
const PlayerPresentation = (function () {
    const MOVE_MS = 250;

    const actors = Object.create(null);
    /** id -> timestamp until which a sent move is awaiting game_state */
    const localAckUntil = Object.create(null);
    const ACK_MS = 400;
    let rafId = null;
    let onFrame = null;

    function lerp(a, b, t) {
        return a + (b - a) * t;
    }

    function makeActor(id, appearanceId, sprite) {
        return {
            id: id,
            tileY: 0,
            tileX: 0,
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

    function snap(actor, tileY, tileX, now) {
        actor.tileY = tileY;
        actor.tileX = tileX;
        actor.queue = [];
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
        snap(actor, tileY | 0, tileX | 0, now);
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
        actor.queue = [];
        actor.onArrive = typeof onDone === 'function' ? onDone : null;
        updateFacing(actor, tileY - actor.visualY, tileX - actor.visualX);
        actor.tileY = tileY;
        actor.tileX = tileX;
        const dist = Math.max(Math.abs(tileY - actor.visualY), Math.abs(tileX - actor.visualX));
        if (dist < 0.05) {
            snap(actor, tileY, tileX, now);
            return;
        }
        beginSegment(actor, tileY, tileX, now);
    }

    function updateFacing(actor, dy, dx) {
        if (dx < 0) {
            actor.facing = 'left';
        } else if (dx > 0) {
            actor.facing = 'right';
        }
    }

    function sync(entities, cameraY, cameraX, localPlayer) {
        const now = performance.now();
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

            if (actor.tileY === tileY && actor.tileX === tileX) {
                continue;
            }

            const dy = tileY - actor.tileY;
            const dx = tileX - actor.tileX;
            const dist = Math.max(Math.abs(dy), Math.abs(dx));
            actor.tileY = tileY;
            actor.tileX = tileX;
            updateFacing(actor, dy, dx);
            delete localAckUntil[id];

            if (dist > 1) {
                snap(actor, tileY, tileX, now);
                continue;
            }

            if (actor.moving || actor.queue.length) {
                actor.queue.push({ y: tileY, x: tileX });
            } else {
                beginSegment(actor, tileY, tileX, now);
            }
        }

        for (const id in actors) {
            if (!seen[id]) {
                delete actors[id];
            }
        }
    }

    function actorBusy(actor) {
        return !!(actor && (actor.moving || actor.queue.length));
    }

    function anyMoving(now) {
        now = now == null ? performance.now() : now;
        for (const id in actors) {
            if (actorBusy(actors[id])) {
                return true;
            }
        }
        return false;
    }

    function isBusy(id) {
        if (id == null || id === '') {
            return false;
        }
        id = String(id);
        const until = localAckUntil[id];
        if (until && performance.now() < until) {
            return true;
        }
        if (until) {
            delete localAckUntil[id];
        }
        return actorBusy(actors[id]);
    }

    /** Call before sending a local move. Returns false if still walking / awaiting ack. */
    function beginLocalStep(id) {
        if (id == null || id === '' || isBusy(id)) {
            return false;
        }
        localAckUntil[String(id)] = performance.now() + ACK_MS;
        return true;
    }

    function sample(now) {
        now = now == null ? performance.now() : now;
        const out = [];
        for (const id in actors) {
            const actor = actors[id];
            sampleVisual(actor, now);
            out.push({
                id: actor.id,
                visualY: actor.visualY,
                visualX: actor.visualX,
                facing: actor.facing,
                clip: actor.clip,
                clipElapsedMs: now - actor.clipStartMs,
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
        rafId = requestAnimationFrame(function () {
            rafId = null;
            if (onFrame) {
                onFrame();
            }
        });
    }

    return {
        MOVE_MS,
        sync,
        sample,
        anyMoving,
        isBusy,
        beginLocalStep,
        walkToThen,
        snapTo,
        setClip,
        setOnFrame,
        kick,
    };
})();

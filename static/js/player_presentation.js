// player_presentation.js — visual waypoint tween + facing + clips (client-only)
const PlayerPresentation = (function () {
    const MOVE_MS = 250;
    /** Soft-lock failsafe if a move never gets game_state (rejected / dropped). */
    const ACK_FAILSAFE_MS = 500;
    const IDLE_GRACE_MS = 80;
    const PIPELINE_T = 0.9;

    const actors = Object.create(null);
    /** id -> timestamp until which a sent move is awaiting game_state */
    const localAckUntil = Object.create(null);
    let rafId = null;
    let onFrame = null;

    function lerp(a, b, t) {
        return a + (b - a) * t;
    }

    function clamp01(t) {
        if (t <= 0) return 0;
        if (t >= 1) return 1;
        return t;
    }

    function makeActor(id, appearanceId, sprite, extras) {
        extras = extras || {};
        return {
            id: id,
            kind: extras.kind || 'player',
            typeId: extras.typeId || null,
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
            idleAt: 0,
            onArrive: null,
            appearanceId: appearanceId || 'peasant',
            sprite: sprite || null,
            dungeonLevel: null,
            present: true,
        };
    }

    function fireArrive(actor) {
        const cb = actor.onArrive;
        actor.onArrive = null;
        if (typeof cb === 'function') {
            cb();
        }
    }

    function setIdle(actor, y, x, now, keepWalk) {
        actor.visualY = y;
        actor.visualX = x;
        actor.fromY = y;
        actor.fromX = x;
        actor.toY = y;
        actor.toX = x;
        actor.moving = false;
        if (keepWalk) {
            actor.clip = 'walk';
            actor.idleAt = now;
        } else {
            actor.clip = 'idle';
            actor.clipStartMs = now;
            actor.idleAt = 0;
        }
    }

    function beginSegment(actor, toY, toX, now) {
        actor.fromY = actor.visualY;
        actor.fromX = actor.visualX;
        actor.toY = toY;
        actor.toX = toX;
        actor.startMs = now;
        actor.moving = true;
        actor.idleAt = 0;
        if (actor.clip !== 'walk') {
            actor.clip = 'walk';
            actor.clipStartMs = now;
        }
    }

    function advanceQueue(actor, now) {
        if (actor.queue.length === 0) {
            setIdle(actor, actor.tileY, actor.tileX, now, true);
            fireArrive(actor);
            return;
        }
        const next = actor.queue.shift();
        beginSegment(actor, next.y, next.x, now);
    }

    function segmentT(actor, now) {
        if (!actor.moving) {
            return actor.idleAt ? 1 : 0;
        }
        const dur = MOVE_MS > 0 ? MOVE_MS : 1;
        return clamp01((now - actor.startMs) / dur);
    }

    function sampleVisual(actor, now) {
        if (!actor.moving) {
            if (actor.clip === 'walk' && actor.idleAt && (now - actor.idleAt) >= IDLE_GRACE_MS) {
                actor.clip = 'idle';
                actor.clipStartMs = now;
                actor.idleAt = 0;
            }
            return;
        }
        const t = segmentT(actor, now);
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
        setIdle(actor, tileY, tileX, now, false);
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
        kick();
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
            if (!e || (e.kind !== 'player' && e.kind !== 'monster') || e.id == null || e.id === '') {
                continue;
            }
            const isMonster = e.kind === 'monster';
            const id = isMonster ? ('m:' + String(e.id)) : String(e.id);
            let tileY = camY + (e.vy | 0);
            let tileX = camX + (e.vx | 0);
            if (!isMonster && localId && id === localId && localPos) {
                tileY = localPos[0] | 0;
                tileX = localPos[1] | 0;
            }
            seen[id] = true;

            let actor = actors[id];
            if (!actor) {
                actor = makeActor(id, e.appearance_id, e.sprite, {
                    kind: e.kind,
                    typeId: e.type_id || null,
                });
                actors[id] = actor;
                snap(actor, tileY, tileX, now);
                continue;
            }

            actor.kind = e.kind || actor.kind;
            actor.typeId = e.type_id || actor.typeId;
            actor.appearanceId = e.appearance_id || actor.appearanceId;
            if (e.sprite) {
                actor.sprite = e.sprite;
            }

            const newLevel = localPlayer && localPlayer.dungeon_level;
            if (id === localId && actor.dungeonLevel != null && newLevel != null
                && (newLevel | 0) !== actor.dungeonLevel) {
                actor.dungeonLevel = newLevel | 0;
                delete localAckUntil[id];
                actor.present = true;
                snap(actor, tileY, tileX, now);
                continue;
            }
            if (id === localId && newLevel != null) {
                actor.dungeonLevel = newLevel | 0;
            }

            // Left the viewport (or LOS) and came back: show current tile, do not replay.
            if (!actor.present) {
                actor.present = true;
                delete localAckUntil[id];
                snap(actor, tileY, tileX, now);
                continue;
            }
            actor.present = true;

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

            const isLocal = !isMonster && localId && id === localId;
            const visualDist = Math.max(
                Math.abs(tileY - actor.visualY),
                Math.abs(tileX - actor.visualX)
            );
            if (dist > 1 || (!isLocal && visualDist > 1)) {
                snap(actor, tileY, tileX, now);
                continue;
            }

            if (actor.moving || actor.queue.length) {
                if (isLocal) {
                    actor.queue.push({ y: tileY, x: tileX });
                } else {
                    // Remotes: at most one pending step; never replay a backlog.
                    actor.queue = [{ y: tileY, x: tileX }];
                }
            } else {
                beginSegment(actor, tileY, tileX, now);
            }
        }

        for (const id in actors) {
            if (seen[id]) {
                continue;
            }
            if (localId && id === localId) {
                continue;
            }
            // Keep a hidden stub so the next sighting snaps instead of tweening.
            const actor = actors[id];
            if (actor) {
                actor.present = false;
                actor.queue = [];
                actor.moving = false;
                actor.clip = 'idle';
                actor.idleAt = 0;
            }
        }

        if (anyMoving() || anyWalkGrace()) {
            kick();
        }
    }

    function actorBusy(actor) {
        return !!(actor && (actor.moving || actor.queue.length));
    }

    function anyWalkGrace() {
        const now = performance.now();
        for (const id in actors) {
            const actor = actors[id];
            if (actor && actor.present && actor.clip === 'walk' && actor.idleAt
                && (now - actor.idleAt) < IDLE_GRACE_MS) {
                return true;
            }
        }
        return false;
    }

    function anyMoving() {
        for (const id in actors) {
            const actor = actors[id];
            if (actor && actor.present && actorBusy(actor)) {
                return true;
            }
        }
        return anyWalkGrace();
    }

    function isBusy(id) {
        if (id == null || id === '') {
            return false;
        }
        id = String(id);
        const until = localAckUntil[id];
        const now = performance.now();
        if (until && now < until) {
            return true;
        }
        if (until) {
            delete localAckUntil[id];
        }
        return actorBusy(actors[id]);
    }

    function isMoving(id) {
        if (id == null || id === '') {
            return false;
        }
        return actorBusy(actors[String(id)]);
    }

    function progress(id) {
        if (id == null || id === '') {
            return 0;
        }
        const actor = actors[String(id)];
        if (!actor) {
            return 0;
        }
        return segmentT(actor, performance.now());
    }

    function visualPos(id) {
        if (id == null || id === '') {
            return null;
        }
        const actor = actors[String(id)];
        if (!actor) {
            return null;
        }
        if (!actor.moving) {
            return { y: actor.visualY, x: actor.visualX };
        }
        const now = performance.now();
        const t = segmentT(actor, now);
        return {
            y: lerp(actor.fromY, actor.toY, t),
            x: lerp(actor.fromX, actor.toX, t),
        };
    }

    /**
     * Gate a local move emit. Ack clears on game_state tile sync (or failsafe).
     * Does not re-arm emits solely because a short timeout elapsed.
     * @param {string} id
     * @param {{ pipeline?: boolean }} [opts]
     */
    function beginLocalStep(id, opts) {
        opts = opts || {};
        if (id == null || id === '') {
            return false;
        }
        id = String(id);
        const now = performance.now();
        const until = localAckUntil[id];
        if (until && now < until) {
            return false;
        }
        if (until) {
            delete localAckUntil[id];
        }
        const actor = actors[id];
        if (actorBusy(actor)) {
            if (!opts.pipeline || actor.queue.length > 0 || segmentT(actor, now) < PIPELINE_T) {
                return false;
            }
        }
        localAckUntil[id] = now + ACK_FAILSAFE_MS;
        return true;
    }

    function sample(now) {
        now = now == null ? performance.now() : now;
        const out = [];
        for (const id in actors) {
            const actor = actors[id];
            if (!actor.present) {
                continue;
            }
            sampleVisual(actor, now);
            out.push({
                id: actor.id,
                kind: actor.kind || 'player',
                typeId: actor.typeId,
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
        rafId = requestAnimationFrame(function tick() {
            rafId = null;
            if (onFrame) {
                onFrame();
            }
            if (anyMoving() || anyWalkGrace()) {
                rafId = requestAnimationFrame(tick);
            }
        });
    }

    return {
        MOVE_MS,
        PIPELINE_T,
        ACK_FAILSAFE_MS,
        sync,
        sample,
        anyMoving,
        isBusy,
        isMoving,
        progress,
        visualPos,
        beginLocalStep,
        walkToThen,
        snapTo,
        setClip,
        setOnFrame,
        kick,
    };
})();

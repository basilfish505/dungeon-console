// player_presentation.js — snap-to-tile facing + clips (no walk tween)
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
            facing: 'left',
            clip: 'idle',
            clipStartMs: 0,
            idleAt: 0,
            appearanceId: appearanceId || 'peasant',
            sprite: sprite || null,
            dungeonLevel: null,
            interiorId: null,
            present: true,
        };
    }

    function setIdle(actor, y, x, now, keepWalk) {
        actor.visualY = y;
        actor.visualX = x;
        if (keepWalk) {
            actor.clip = 'walk';
            actor.idleAt = now;
        } else {
            actor.clip = 'idle';
            actor.clipStartMs = now;
            actor.idleAt = 0;
        }
    }

    function snap(actor, tileY, tileX, now, walked) {
        actor.tileY = tileY;
        actor.tileX = tileX;
        setIdle(actor, tileY, tileX, now, !!walked);
        if (walked) {
            kick();
        }
    }

    function snapTo(id, tileY, tileX) {
        const actor = actors[String(id)];
        const now = performance.now();
        if (!actor) {
            return;
        }
        snap(actor, tileY | 0, tileX | 0, now, false);
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
        updateFacing(actor, tileY - actor.visualY, tileX - actor.visualX);
        const dist = Math.max(Math.abs(tileY - actor.tileY), Math.abs(tileX - actor.tileX));
        snap(actor, tileY, tileX, now, dist >= 1);
        if (typeof onDone === 'function') {
            onDone();
        }
    }

    function updateFacing(actor, dy, dx) {
        if (dx < 0) {
            actor.facing = 'left';
        } else if (dx > 0) {
            actor.facing = 'right';
        }
    }

    function expireWalkClip(actor, now) {
        if (actor.clip === 'walk' && actor.idleAt && (now - actor.idleAt) >= IDLE_GRACE_MS) {
            actor.clip = 'idle';
            actor.clipStartMs = now;
            actor.idleAt = 0;
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
                snap(actor, tileY, tileX, now, false);
                continue;
            }

            actor.kind = e.kind || actor.kind;
            actor.typeId = e.type_id || actor.typeId;
            actor.appearanceId = e.appearance_id || actor.appearanceId;
            if (e.sprite) {
                actor.sprite = e.sprite;
            }

            const newLevel = localPlayer && localPlayer.dungeon_level;
            const newInterior = localPlayer ? (localPlayer.interior_id || null) : null;
            if (id === localId && actor.dungeonLevel != null && newLevel != null
                && (newLevel | 0) !== actor.dungeonLevel) {
                actor.dungeonLevel = newLevel | 0;
                actor.interiorId = newInterior;
                delete localAckUntil[id];
                actor.present = true;
                snap(actor, tileY, tileX, now, false);
                continue;
            }
            if (id === localId && actor.interiorId !== newInterior
                && actor.interiorId !== undefined) {
                actor.interiorId = newInterior;
                delete localAckUntil[id];
                actor.present = true;
                snap(actor, tileY, tileX, now, false);
                continue;
            }
            if (id === localId && newLevel != null) {
                actor.dungeonLevel = newLevel | 0;
            }
            if (id === localId) {
                actor.interiorId = newInterior;
            }

            if (!actor.present) {
                actor.present = true;
                delete localAckUntil[id];
                snap(actor, tileY, tileX, now, false);
                continue;
            }
            actor.present = true;

            if (actor.tileY === tileY && actor.tileX === tileX) {
                if (!isMonster && localId && id === localId) {
                    delete localAckUntil[id];
                }
                continue;
            }

            const dy = tileY - actor.tileY;
            const dx = tileX - actor.tileX;
            updateFacing(actor, dy, dx);
            delete localAckUntil[id];
            snap(actor, tileY, tileX, now, true);
        }

        for (const id in actors) {
            if (seen[id]) {
                continue;
            }
            if (localId && id === localId) {
                continue;
            }
            const actor = actors[id];
            if (actor) {
                actor.present = false;
                actor.clip = 'idle';
                actor.idleAt = 0;
            }
        }

        if (anyWalkGrace()) {
            kick();
        }
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
        return false;
    }

    function isMoving(id) {
        return isBusy(id);
    }

    function progress(id) {
        return isBusy(id) ? 0 : 1;
    }

    function tilePos(id) {
        if (id == null || id === '') {
            return null;
        }
        const actor = actors[String(id)];
        if (!actor) {
            return null;
        }
        return { y: actor.tileY, x: actor.tileX };
    }

    function visualPos(id) {
        return tilePos(id);
    }

    /**
     * Gate a local move emit. Ack clears on game_state tile sync (or failsafe).
     * @param {string} id
     * @param {{ pipeline?: boolean }} [opts]
     */
    function beginLocalStep(id, opts) {
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
        localAckUntil[id] = now + ACK_FAILSAFE_MS;
        return true;
    }

    /** Snap the local player one tile immediately (before game_state). */
    function predictLocalStep(id, dy, dx) {
        if (id == null || id === '') {
            return false;
        }
        id = String(id);
        const actor = actors[id];
        if (!actor) {
            return false;
        }
        dy = dy | 0;
        dx = dx | 0;
        if (Math.max(Math.abs(dy), Math.abs(dx)) !== 1) {
            return false;
        }
        const toY = actor.tileY + dy;
        const toX = actor.tileX + dx;
        if (actor.tileY === toY && actor.tileX === toX) {
            return false;
        }
        updateFacing(actor, dy, dx);
        snap(actor, toY, toX, performance.now(), true);
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
            expireWalkClip(actor, now);
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
            if (anyWalkGrace()) {
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
        isBusy,
        isMoving,
        progress,
        visualPos,
        tilePos,
        beginLocalStep,
        predictLocalStep,
        walkToThen,
        snapTo,
        setOnFrame,
        kick,
    };
})();

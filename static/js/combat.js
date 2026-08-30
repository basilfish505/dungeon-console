// combat.js - Full-screen combat UI and actions
const Combat = (function () {
    const MAX_COMBAT_LOG_LINES = 12;
    /** Every battle message stays on the status bar at least this long. */
    const STATUS_HOLD_MS = 1000;
    /** Brief beat so the killing blow's 0 HP registers before the card breaks. */
    const DEFEAT_HOLD_MS = 140;
    const DEFEAT_SMASH_MS = 650;
    const CARD_SHAKE_MS = 280;

    const elements = {
        overlay: document.getElementById('combat-overlay'),
        screen: document.getElementById('combat-screen'),
        status: document.getElementById('combat-status'),
        roster: document.getElementById('combat-roster'),
        selfCard: document.getElementById('combat-self'),
        combatLog: document.getElementById('combat-log'),
        opponentThinking: document.getElementById('opponent-thinking'),
        attackBtn: document.getElementById('attack-btn'),
        defendBtn: document.getElementById('defend-btn'),
        spellBtn: document.getElementById('spell-btn'),
        itemBtn: document.getElementById('item-btn'),
        runBtn: document.getElementById('run-btn'),
        spellCancelBtn: document.getElementById('spell-cancel-btn'),
        mapPeekBtn: document.getElementById('map-peek-btn'),
        mobileControls: document.getElementById('mobile-controls'),
    };

    let currentBattle = {
        battleId: null,
        opponents: [],
        combatants: [],
        selectedTarget: null,
        pendingSpellPick: null,
        viewerId: null,
        selfHp: null,
        selfMhp: null,
        selfMp: null,
        selfMmp: null,
        selfLevel: null,
        selfName: null,
    };
    let combatLogLines = [];
    let countdownTimer = null;
    let countdownActive = false;
    let statusHoldUntil = 0;
    let statusHoldTimer = null;
    let countdownRemaining = 0;
    let countdownYourTurn = false;
    let countdownActivePlayer = null;
    let open = false;
    let mobileWasVisible = false;
    let mapPeekActive = false;
    /** Monster ids currently playing the smash FX. */
    const dyingMonsters = new Set();
    /** key -> { card, placeholder, index } for cards frozen mid-smash. */
    const dyingCards = new Map();
    /** Keys of monsters that joined mid-smash; revealed once it finishes. */
    const deferredJoins = new Set();
    /** Play enterbattle after death FX so it does not overlap killmonster. */
    let pendingEnterBattleSound = false;
    /** Display order of opponent keys, so cards keep their slots. */
    let rosterOrder = [];
    /** Hold next-turn highlight until attack/spell FX finishes. */
    let pendingTurnNotification = null;
    let fxHoldTimer = null;
    let fxHoldUntil = 0;
    /** Monster keys waiting for spell FX before smash/death sound. */
    const pendingSpellDefeats = new Set();

    function endMapPeek() {
        if (!mapPeekActive) {
            return;
        }
        mapPeekActive = false;
        if (elements.overlay) {
            elements.overlay.classList.remove('combat-map-peek');
        }
        if (elements.mapPeekBtn) {
            elements.mapPeekBtn.classList.remove('active');
        }
    }

    function refreshMapDuringPeek() {
        if (typeof MapView !== 'undefined' && MapView.getState) {
            const st = MapView.getState();
            if (typeof SocketHandler !== 'undefined' && SocketHandler.setViewport) {
                SocketHandler.setViewport(st.visibleRows, st.visibleCols);
            }
        }
        if (typeof UI !== 'undefined' && UI.requestMapUpdate) {
            UI.requestMapUpdate('combat-map-peek');
        }
        if (typeof MapView !== 'undefined' && MapView.paint) {
            MapView.paint();
        }
    }

    function startMapPeek(e) {
        if (!open || mapPeekActive || !elements.overlay) {
            return;
        }
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        mapPeekActive = true;
        elements.overlay.classList.add('combat-map-peek');
        if (elements.mapPeekBtn) {
            elements.mapPeekBtn.classList.add('active');
            if (e && elements.mapPeekBtn.setPointerCapture && e.pointerId != null) {
                try {
                    elements.mapPeekBtn.setPointerCapture(e.pointerId);
                } catch (_err) {
                    // Ignore capture failures on unsupported browsers.
                }
            }
        }
        refreshMapDuringPeek();
    }

    function bindMapPeek() {
        const btn = elements.mapPeekBtn;
        if (!btn) {
            return;
        }
        btn.addEventListener('pointerdown', startMapPeek);
        btn.addEventListener('pointerup', endMapPeek);
        btn.addEventListener('pointercancel', endMapPeek);
        btn.addEventListener('lostpointercapture', endMapPeek);
        btn.addEventListener('contextmenu', function (e) {
            e.preventDefault();
        });
    }

    function stripHtml(html) {
        const tmp = document.createElement('div');
        tmp.innerHTML = html;
        return (tmp.textContent || tmp.innerText || '').replace(/\s+/g, ' ').trim();
    }

    function escapeHtml(text) {
        return String(text == null ? '' : text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function isOpen() {
        return open;
    }

    function showOverlay() {
        if (!elements.overlay) return;
        const shell = document.getElementById('game-shell');
        if (shell && shell.hidden) {
            return; // Still on the login screen; nothing to overlay yet.
        }
        const opening = !open;
        elements.overlay.hidden = false;
        elements.overlay.setAttribute('aria-hidden', 'false');
        elements.overlay.style.display = '';
        open = true;
        if (elements.mobileControls) {
            if (opening) {
                mobileWasVisible = elements.mobileControls.style.display !== 'none';
            }
            elements.mobileControls.style.display = 'none';
        }
    }

    function hideOverlay() {
        endMapPeek();
        if (!elements.overlay) return;
        elements.overlay.hidden = true;
        elements.overlay.setAttribute('aria-hidden', 'true');
        elements.overlay.style.display = 'none';
        open = false;
        if (typeof CombatSocial !== 'undefined' && CombatSocial.hide) {
            CombatSocial.hide();
        }
        if (elements.mobileControls) {
            const shell = document.getElementById('game-shell');
            if (shell && !shell.hidden) {
                elements.mobileControls.style.display = 'grid';
            }
        }
        mobileWasVisible = false;
    }

    function renderCombatLog() {
        if (!elements.combatLog) return;
        elements.combatLog.innerHTML = combatLogLines
            .map(line => `<div class="combat-log-line">${escapeHtml(line)}</div>`)
            .join('');
        elements.combatLog.scrollTop = elements.combatLog.scrollHeight;
    }

    function clearCombatLog() {
        combatLogLines = [];
        renderCombatLog();
    }

    function appendCombatLog(message) {
        if (!message) return;
        const text = stripHtml(message);
        if (!text) return;
        if (/^\d+s\)?$/.test(text) || text.indexOf('to take their turn') !== -1) return;
        if (text.indexOf("It's your turn to act!") === 0 && text.indexOf('(') !== -1) return;
        if (combatLogLines.length && combatLogLines[combatLogLines.length - 1] === text) return;
        combatLogLines.push(text);
        while (combatLogLines.length > MAX_COMBAT_LOG_LINES) {
            combatLogLines.shift();
        }
        renderCombatLog();
    }

    function shakeCombatWindow() {
        const target = elements.screen || elements.overlay;
        if (!target) return;
        target.classList.remove('combat-shake');
        void target.offsetWidth;
        target.classList.add('combat-shake');
        setTimeout(() => target.classList.remove('combat-shake'), 500);
    }

    function shakeCombatantCard(key) {
        const el = findCardEl(key);
        if (!el) return;
        el.classList.remove('combat-card-shake');
        void el.offsetWidth;
        el.classList.add('combat-card-shake');
        if (el._shakeTimer) {
            clearTimeout(el._shakeTimer);
        }
        el._shakeTimer = setTimeout(function () {
            el.classList.remove('combat-card-shake');
        }, CARD_SHAKE_MS);
    }

    function playHitShake(key) {
        const me = currentBattle.viewerId
            || (document.getElementById('player-id') || {}).value;
        if (sameCombatant(me, key)) {
            shakeCombatWindow();
            return;
        }
        shakeCombatantCard(key);
    }

    function flashSpellScreen(seconds) {
        let el = document.getElementById('spell-flash');
        if (!el) {
            el = document.createElement('div');
            el.id = 'spell-flash';
            el.className = 'spell-flash';
            el.setAttribute('aria-hidden', 'true');
            document.body.appendChild(el);
        }
        const ms = Math.max(400, Math.round((seconds || 1.2) * 1000));
        el.style.setProperty('--spell-flash-ms', ms + 'ms');
        el.classList.remove('is-on');
        void el.offsetWidth;
        el.classList.add('is-on');
        if (el._spellFlashTimer) {
            clearTimeout(el._spellFlashTimer);
        }
        el._spellFlashTimer = setTimeout(function () {
            el.classList.remove('is-on');
        }, ms);
    }

    function playSpellCastFx(onEnded) {
        const fallback = 1.2;
        let endedScheduled = false;
        const afterSound = function (seconds) {
            if (endedScheduled) return;
            endedScheduled = true;
            if (typeof onEnded !== 'function') return;
            setTimeout(onEnded, Math.round((seconds || fallback) * 1000));
        };
        if (typeof Sound === 'undefined' || !Sound.play) {
            flashSpellScreen(fallback);
            afterSound(fallback);
            return;
        }
        // Flash starts when the clip starts so the white-out matches the sound.
        Sound.play('spell', function (seconds) {
            flashSpellScreen(seconds || fallback);
            afterSound(seconds);
        });
    }

    function findCardEl(key) {
        if (!elements.roster || !key) return null;
        const cards = elements.roster.querySelectorAll('.combat-card[data-key]');
        for (let i = 0; i < cards.length; i++) {
            if (cards[i].getAttribute('data-key') === String(key)) {
                return cards[i];
            }
        }
        return null;
    }

    function removeOpponentByKey(key) {
        currentBattle.opponents = currentBattle.opponents.filter(
            o => !sameCombatant(o, key)
        );
        if (currentBattle.combatants) {
            currentBattle.combatants = currentBattle.combatants.filter(
                c => !sameCombatant(c, key)
            );
        }
        if (sameCombatant(currentBattle.selectedTarget, key)) {
            currentBattle.selectedTarget = null;
        }
    }

    function spawnSmashShards(card) {
        const rect = card.getBoundingClientRect();
        if (rect.width < 4 || rect.height < 4) return;

        const portrait = card.querySelector('.combat-card-portrait');
        const src = portrait && portrait.getAttribute('src');
        const layer = document.createElement('div');
        layer.className = 'combat-smash-layer';
        layer.style.left = rect.left + 'px';
        layer.style.top = rect.top + 'px';
        layer.style.width = rect.width + 'px';
        layer.style.height = rect.height + 'px';

        const cols = 3;
        const rows = 3;
        const sw = rect.width / cols;
        const sh = rect.height / rows;

        for (let r = 0; r < rows; r++) {
            for (let c = 0; c < cols; c++) {
                const shard = document.createElement('div');
                shard.className = 'combat-smash-shard';
                shard.style.width = sw + 'px';
                shard.style.height = sh + 'px';
                shard.style.left = (c * sw) + 'px';
                shard.style.top = (r * sh) + 'px';
                if (src) {
                    shard.style.backgroundImage = 'url("' + src.replace(/"/g, '\\"') + '")';
                    shard.style.backgroundSize = rect.width + 'px ' + rect.height + 'px';
                    shard.style.backgroundPosition = (-c * sw) + 'px ' + (-r * sh) + 'px';
                }
                const angle = Math.atan2(
                    (r + 0.5) / rows - 0.5,
                    (c + 0.5) / cols - 0.5
                );
                const dist = 48 + Math.random() * 72;
                const dx = Math.cos(angle) * dist + (Math.random() * 20 - 10);
                const dy = Math.sin(angle) * dist + 24 + Math.random() * 40;
                const rot = (Math.random() * 280 - 140) + 'deg';
                shard.style.setProperty('--dx', dx.toFixed(1) + 'px');
                shard.style.setProperty('--dy', dy.toFixed(1) + 'px');
                shard.style.setProperty('--rot', rot);
                shard.style.animationDelay = (Math.random() * 0.05).toFixed(3) + 's';
                layer.appendChild(shard);
            }
        }

        document.body.appendChild(layer);
        setTimeout(function () {
            if (layer.parentNode) layer.parentNode.removeChild(layer);
        }, DEFEAT_SMASH_MS + 80);
    }

    function detachDyingCard(key) {
        const entry = dyingCards.get(key);
        if (!entry) return;
        dyingCards.delete(key);
        if (entry.card.parentNode) entry.card.parentNode.removeChild(entry.card);
        if (entry.placeholder.parentNode) {
            entry.placeholder.parentNode.removeChild(entry.placeholder);
        }
    }

    function finishMonsterDefeat(key) {
        const entry = dyingCards.get(key);
        const slot = entry ? entry.index : rosterOrder.length;
        dyingMonsters.delete(key);
        detachDyingCard(key);
        removeOpponentByKey(key);
        // Monsters that arrived mid-smash take the slot just vacated.
        if (deferredJoins.size && !dyingMonsters.size) {
            const revealed = Array.from(deferredJoins);
            deferredJoins.clear();
            rosterOrder = rosterOrder.filter(k => revealed.indexOf(k) === -1);
            rosterOrder.splice(Math.min(slot, rosterOrder.length), 0, ...revealed);
        }
        renderRoster();
        if (pendingEnterBattleSound && !dyingMonsters.size) {
            pendingEnterBattleSound = false;
            if (typeof Sound !== 'undefined') Sound.play('enterbattle');
        }
    }

    /**
     * Lift the card out of the grid and fix it at the coordinates it occupied
     * on death, so a monster joining mid-FX cannot reflow the smash elsewhere.
     * A same-size placeholder keeps the surrounding cards still.
     */
    function pinDyingCard(key, card) {
        const rect = card.getBoundingClientRect();
        const siblings = Array.prototype.slice.call(
            elements.roster.querySelectorAll('.combat-card')
        );
        const index = Math.max(0, siblings.indexOf(card));

        const placeholder = document.createElement('div');
        placeholder.className = 'combat-card-placeholder';
        placeholder.style.height = rect.height + 'px';
        placeholder.setAttribute('aria-hidden', 'true');
        card.parentNode.insertBefore(placeholder, card);

        card.classList.add('combat-card-pinned');
        card.style.left = rect.left + 'px';
        card.style.top = rect.top + 'px';
        card.style.width = rect.width + 'px';
        card.style.height = rect.height + 'px';
        document.body.appendChild(card);

        dyingCards.set(key, { card, placeholder, index });
    }

    function playMonsterDefeat(key) {
        if (!key || dyingMonsters.has(key)) return;
        dyingMonsters.add(key);

        const card = findCardEl(key);
        if (!card) {
            finishMonsterDefeat(key);
            return;
        }

        card.classList.add('combat-card-defeated');
        pinDyingCard(key, card);
        // The roster no longer owns this card; the placeholder holds its slot.
        removeOpponentByKey(key);
        renderRoster();
        if (typeof Sound !== 'undefined' && Sound.warm) {
            Sound.warm();
        }

        setTimeout(function () {
            if (!dyingMonsters.has(key)) return;
            if (typeof Sound !== 'undefined') Sound.play('killmonster');
            spawnSmashShards(card);
            card.classList.add('combat-card-smashing');
            setTimeout(function () {
                finishMonsterDefeat(key);
            }, DEFEAT_SMASH_MS);
        }, DEFEAT_HOLD_MS);
    }

    function stopCountdown() {
        countdownActive = false;
        if (statusHoldTimer) {
            clearTimeout(statusHoldTimer);
            statusHoldTimer = null;
        }
        if (countdownTimer) {
            clearInterval(countdownTimer);
            countdownTimer = null;
        }
    }

    function setStatus(html) {
        if (elements.status) {
            elements.status.innerHTML = html;
        }
    }

    /** Paint a battle message and keep it readable before the timer takes over. */
    function showStatusMessage(html) {
        setStatus(html);
        statusHoldUntil = Date.now() + STATUS_HOLD_MS;
    }

    function statusHoldRemaining() {
        return statusHoldUntil - Date.now();
    }

    function renderCountdownMessage() {
        const holdLeft = statusHoldRemaining();
        if (holdLeft > 0) {
            if (!statusHoldTimer) {
                statusHoldTimer = setTimeout(function () {
                    statusHoldTimer = null;
                    if (countdownActive) {
                        renderCountdownMessage();
                    }
                }, holdLeft);
            }
            return;
        }
        const secs = Math.max(0, countdownRemaining);
        if (elements.opponentThinking) {
            elements.opponentThinking.style.display = 'none';
        }
        if (countdownYourTurn) {
            setStatus(`Your turn <span class="combat-countdown">(${secs}s)</span>`);
        } else {
            setStatus(
                `Waiting for ${escapeHtml(displayNameForActorId(countdownActivePlayer))} ` +
                `<span class="combat-countdown">(${secs}s)</span>`
            );
        }
    }

    function startCountdown(seconds, isYourTurn, activePlayer) {
        stopCountdown();
        if (!seconds || seconds <= 0) {
            return;
        }
        countdownRemaining = seconds;
        countdownYourTurn = !!isYourTurn;
        countdownActivePlayer = activePlayer || null;
        countdownActive = true;
        renderCountdownMessage();
        countdownTimer = setInterval(function () {
            countdownRemaining -= 1;
            renderCountdownMessage();
            if (countdownRemaining <= 0) {
                stopCountdown();
            }
        }, 1000);
    }

    function updateButtonStates(isYourTurn) {
        const disableAll = isYourTurn === false;
        const pickingSpell = !!currentBattle.pendingSpellPick;
        if (elements.attackBtn) elements.attackBtn.disabled = disableAll || pickingSpell;
        if (elements.defendBtn) elements.defendBtn.disabled = disableAll || pickingSpell;
        if (elements.spellBtn) {
            const noSpell = (typeof SpellUI === 'undefined')
                || !SpellUI.hasCastable
                || !SpellUI.hasCastable();
            elements.spellBtn.disabled = disableAll || noSpell || pickingSpell;
        }
        if (elements.itemBtn) elements.itemBtn.disabled = disableAll || pickingSpell;
        if (elements.runBtn) elements.runBtn.disabled = true;
        syncSpellCancelBtn();
        if (elements.opponentThinking) {
            elements.opponentThinking.style.display = 'none';
        }
        if (disableAll && !countdownActive && statusHoldRemaining() <= 0) {
            setStatus("Waiting for opponent's move...");
        }
        if (elements.overlay) {
            elements.overlay.classList.toggle('combat-your-turn', !!isYourTurn);
        }
    }

    function syncSpellCancelBtn() {
        if (!elements.spellCancelBtn) {
            return;
        }
        const picking = !!currentBattle.pendingSpellPick;
        elements.spellCancelBtn.hidden = !picking;
        elements.spellCancelBtn.disabled = !picking;
        if (elements.overlay) {
            elements.overlay.classList.toggle('combat-spell-picking', picking);
        }
    }
    function hpBarClass(pct) {
        if (pct <= 0.25) return 'hp-low';
        if (pct <= 0.6) return 'hp-hurt';
        return 'hp-ok';
    }

    function hpBarHtml(hp, mhp) {
        let cur = Number(hp);
        let max = Number(mhp);
        if (!Number.isFinite(cur)) cur = 0;
        if (!Number.isFinite(max) || max <= 0) max = Math.max(cur, 1);
        const pct = Math.max(0, Math.min(1, cur / max));
        const width = Math.round(pct * 100);
        const cls = hpBarClass(pct);
        return (
            `<div class="combat-hpbar ${cls}" role="progressbar" ` +
            `aria-valuenow="${escapeHtml(cur)}" aria-valuemin="0" aria-valuemax="${escapeHtml(max)}">` +
            `<div class="combat-hpbar-fill" style="width:${width}%"></div>` +
            `<span class="combat-hpbar-text">${escapeHtml(cur)} / ${escapeHtml(max)}</span>` +
            `</div>`
        );
    }

    function mpBarHtml(mp, mmp) {
        let cur = Number(mp);
        let max = Number(mmp);
        if (!Number.isFinite(cur)) cur = 0;
        if (!Number.isFinite(max) || max < 0) max = 0;
        if (max <= 0) {
            return (
                `<div class="combat-mpbar combat-mpbar-empty">` +
                `<span class="combat-hpbar-text">MP ${escapeHtml(cur)}</span>` +
                `</div>`
            );
        }
        const pct = Math.max(0, Math.min(1, cur / max));
        const width = Math.round(pct * 100);
        return (
            `<div class="combat-mpbar" role="progressbar">` +
            `<div class="combat-mpbar-fill" style="width:${width}%"></div>` +
            `<span class="combat-hpbar-text">${escapeHtml(cur)} / ${escapeHtml(max)}</span>` +
            `</div>`
        );
    }

    function combatantKey(c) {
        if (!c) return null;
        if (c.is_monster) return c.monster_id || c.id;
        return c.id;
    }

    function sameCombatant(a, b) {
        const ka = typeof a === 'string' ? a : combatantKey(a);
        const kb = typeof b === 'string' ? b : combatantKey(b);
        return !!ka && ka === kb;
    }

    function displayName(c) {
        if (!c) return 'Unknown';
        return c.name || c.id || 'Unknown';
    }

    function displayNameForActorId(actorId) {
        if (!actorId) return 'opponent';
        const fromCombatants = (currentBattle.combatants || []).find(
            c => sameCombatant(c, actorId)
        );
        if (fromCombatants) return displayName(fromCombatants);
        const fromOpponents = (currentBattle.opponents || []).find(
            o => sameCombatant(o, actorId)
        );
        if (fromOpponents) return displayName(fromOpponents);
        return String(actorId);
    }

    function portraitUrl(c) {
        if (!c) return null;
        if (c.portrait) return c.portrait;
        if (c.is_monster && c.type_id) {
            return '/static/monsters/portraits/' + c.type_id + '.png';
        }
        return c.sprite || null;
    }

    function parseHpString(value) {
        if (value == null) return null;
        if (typeof value === 'number') {
            return { hp: value, mhp: value };
        }
        const text = String(value);
        const m = text.match(/^(\d+)\s*\/\s*(\d+)$/);
        if (m) {
            return { hp: Number(m[1]), mhp: Number(m[2]) };
        }
        const n = Number(text);
        if (Number.isFinite(n)) {
            return { hp: n, mhp: n };
        }
        return null;
    }

    function syncSelfFromCombatants() {
        const viewer = currentBattle.viewerId;
        if (!viewer || !currentBattle.combatants) return;
        const me = currentBattle.combatants.find(
            c => !c.is_monster && c.id === viewer
        );
        if (!me) return;
        currentBattle.selfName = displayName(me);
        currentBattle.selfLevel = me.level;
        currentBattle.selfHp = me.hp;
        currentBattle.selfMhp = me.mhp;
        currentBattle.selfMp = me.mp;
        currentBattle.selfMmp = me.mmp;
    }

    function renderSelfCard() {
        if (!elements.selfCard) return;
        const name = currentBattle.selfName
            || currentBattle.viewerId
            || (document.getElementById('player-id') || {}).value
            || 'You';
        const level = currentBattle.selfLevel != null ? currentBattle.selfLevel : '?';
        const hp = currentBattle.selfHp != null ? currentBattle.selfHp : '?';
        const mhp = currentBattle.selfMhp != null ? currentBattle.selfMhp : '?';
        const mp = currentBattle.selfMp != null ? currentBattle.selfMp : 0;
        const mmp = currentBattle.selfMmp != null ? currentBattle.selfMmp : 0;
        const turn = (currentBattle.combatants || []).some(
            c => !c.is_monster && c.id === currentBattle.viewerId && c.is_current_turn
        );
        const defending = (currentBattle.combatants || []).some(
            c => !c.is_monster && c.id === currentBattle.viewerId && c.defending
        );
        const pickingSelf = !!(currentBattle.pendingSpellPick
            && currentBattle.viewerId
            && sameCombatant(currentBattle.selectedTarget, currentBattle.viewerId));
        let cls = 'combat-self' + (turn ? ' current-turn' : '');
        if (currentBattle.pendingSpellPick) {
            cls += ' combat-self-pickable';
        }
        if (pickingSelf) {
            cls += ' selected-target';
        }
        elements.selfCard.className = cls;
        elements.selfCard.innerHTML =
            `<div class="combat-self-meta">` +
            `<span class="combat-self-name">${escapeHtml(name)}</span>` +
            `<span class="combat-level-badge">Lv ${escapeHtml(level)}</span>` +
            (defending ? '<span class="combat-badge-defend">Defend</span>' : '') +
            (turn ? '<span class="combat-badge-turn">Your turn</span>' : '') +
            `</div>` +
            hpBarHtml(hp, mhp) +
            mpBarHtml(mp, mmp);
        if (currentBattle.pendingSpellPick) {
            elements.selfCard.setAttribute('role', 'button');
            elements.selfCard.setAttribute('tabindex', '0');
            elements.selfCard.setAttribute('aria-label', 'Cast on yourself');
            elements.selfCard.onclick = function (e) {
                e.preventDefault();
                e.stopPropagation();
                confirmSpellTarget(currentBattle.viewerId);
            };
            elements.selfCard.onkeydown = function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    confirmSpellTarget(currentBattle.viewerId);
                }
            };
        } else {
            elements.selfCard.removeAttribute('role');
            elements.selfCard.removeAttribute('tabindex');
            elements.selfCard.removeAttribute('aria-label');
            elements.selfCard.onclick = null;
            elements.selfCard.onkeydown = null;
        }
    }

    function confirmSpellTarget(targetId) {
        const pending = currentBattle.pendingSpellPick;
        if (!pending || !pending.spellId || !targetId) {
            return;
        }
        currentBattle.pendingSpellPick = null;
        if (window.socket) {
            window.socket.emit('combat_action', {
                action: 'spell',
                spell_id: pending.spellId,
                target_id: targetId,
            });
        }
        renderRoster();
        syncSpellCancelBtn();
    }

    function cancelSpellPick(opts) {
        opts = opts || {};
        if (!currentBattle.pendingSpellPick) {
            return false;
        }
        currentBattle.pendingSpellPick = null;
        renderRoster();
        syncSpellCancelBtn();
        if (!opts.silent) {
            showStatusMessage(opts.message || 'Spell cancelled.');
        }
        if (opts.reopenPicker) {
            openSpellPicker();
        }
        return true;
    }

    function openSpellPicker() {
        if (typeof SpellUI === 'undefined' || !SpellUI.open) {
            return;
        }
        SpellUI.open({
            onCancel: function () {
                showStatusMessage('Spell cancelled.');
            },
            onPick: function (spellId) {
                const spells = (typeof SpellUI.getSpells === 'function')
                    ? SpellUI.getSpells()
                    : [];
                const def = spells.find(function (s) {
                    return s && s.spell_id === spellId;
                });
                const mode = def && def.target_mode;
                if (mode === 'single_any') {
                    currentBattle.pendingSpellPick = { spellId: spellId };
                    currentBattle.selectedTarget = null;
                    renderRoster();
                    syncSpellCancelBtn();
                    updateButtonStates(true);
                    showStatusMessage(
                        'Choose a target (tap a card, including yourself). Back to cancel.'
                    );
                    appendCombatLog('Choose a spell target.');
                    return;
                }
                if (window.socket) {
                    window.socket.emit('combat_action', {
                        action: 'spell',
                        spell_id: spellId,
                        target_id: currentBattle.selectedTarget,
                    });
                }
            },
        });
    }
    function inspectTarget(combatant, ev) {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
        if (!combatant) return;
        const tid = combatantKey(combatant);
        if (typeof SocketHandler !== 'undefined' && SocketHandler.inspectCombatant) {
            SocketHandler.inspectCombatant(tid);
        }
    }

    function selectTarget(combatant) {
        if (!combatant) return;
        const key = combatantKey(combatant);
        if (currentBattle.pendingSpellPick) {
            // Living targets only for heal / single_any.
            if (Number(combatant.hp) <= 0) {
                return;
            }
            confirmSpellTarget(key);
            return;
        }
        currentBattle.selectedTarget = key;
        renderRoster();
    }

    function cardHtml(opponent) {
        const name = displayName(opponent);
        const level = opponent.level != null ? opponent.level : '?';
        const key = combatantKey(opponent);
        const selected = sameCombatant(currentBattle.selectedTarget, opponent);
        const url = portraitUrl(opponent);
        let classes = 'combat-card';
        if (opponent.is_monster) classes += ' combat-card-enemy';
        else classes += ' combat-card-player';
        if (selected) classes += ' selected-target';
        if (opponent.is_current_turn) classes += ' current-turn';
        if (opponent.defending) classes += ' defending';

        const portrait = url
            ? `<div class="combat-card-portrait-wrap" data-select-area="1">` +
              `<img class="combat-card-portrait" src="${escapeHtml(url)}" alt="" draggable="false">` +
              `<span class="combat-card-info-btn" role="button" tabindex="0" aria-label="Inspect ${escapeHtml(name)}">` +
              `<span class="combat-card-info" aria-hidden="true">i</span>` +
              `</span>` +
              `</div>`
            : `<div class="combat-card-portrait-wrap combat-card-portrait-empty" data-select-area="1">` +
              `<span class="combat-card-info-btn" role="button" tabindex="0" aria-label="Inspect ${escapeHtml(name)}">` +
              `<span class="combat-card-info" aria-hidden="true">i</span>` +
              `</span>` +
              `</div>`;

        const turnLabel = opponent.is_monster ? 'Attacking' : 'Their turn';
        const isAlly = !opponent.is_monster && Array.isArray(opponent.ally_of)
            && opponent.ally_of.indexOf(currentBattle.viewerId) !== -1;
        const badges =
            (opponent.is_current_turn ? `<span class="combat-badge-turn">${turnLabel}</span>` : '') +
            (opponent.defending ? '<span class="combat-badge-defend">Defend</span>' : '') +
            (isAlly ? '<span class="combat-card-ally-badge">Ally</span>' : '');

        return (
            `<div class="${classes}" data-id="${escapeHtml(key || '')}" data-key="${escapeHtml(key || '')}" tabindex="0">` +
            portrait +
            `<div class="combat-card-body" data-select-area="1">` +
            `<div class="combat-card-header">` +
            `<span class="combat-card-name">${escapeHtml(name)}</span>` +
            `<span class="combat-level-badge">Lv ${escapeHtml(level)}</span>` +
            `</div>` +
            hpBarHtml(opponent.hp, opponent.mhp) +
            (badges ? `<div class="combat-card-badges">${badges}</div>` : '') +
            `</div>` +
            `</div>`
        );
    }

    function isInfoButtonTarget(target) {
        return !!(target && target.closest && target.closest('.combat-card-info-btn'));
    }

    function bindRosterEvents() {
        if (!elements.roster) return;
        elements.roster.querySelectorAll('.combat-card').forEach(function (el) {
            const key = el.getAttribute('data-key') || el.getAttribute('data-id');
            const opponent = currentBattle.opponents.find(o => sameCombatant(o, key));
            const infoBtn = el.querySelector('.combat-card-info-btn');

            function onSelect(ev) {
                if (isInfoButtonTarget(ev.target)) {
                    return;
                }
                if (ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                }
                selectTarget(opponent);
            }

            function onInspect(ev) {
                if (ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                }
                inspectTarget(opponent, ev);
            }

            if (infoBtn) {
                infoBtn.addEventListener('pointerup', onInspect);
                infoBtn.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter' || e.key === ' ') {
                        onInspect(e);
                    }
                });
            }

            el.querySelectorAll('[data-select-area]').forEach(function (area) {
                area.addEventListener('pointerup', onSelect);
            });

            el.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    if (isInfoButtonTarget(e.target)) {
                        return;
                    }
                    e.preventDefault();
                    selectTarget(opponent);
                }
            });
        });
    }

    /**
     * Opponents to draw right now, in stable display order. Monsters that
     * joined while a card is smashing are held back until it finishes.
     */
    function visibleOpponents() {
        const list = currentBattle.opponents.filter(
            o => !deferredJoins.has(combatantKey(o))
        );
        list.sort(function (a, b) {
            const ia = rosterOrder.indexOf(combatantKey(a));
            const ib = rosterOrder.indexOf(combatantKey(b));
            if (ia === ib) return 0;
            if (ia === -1) return 1;
            if (ib === -1) return -1;
            return ia - ib;
        });
        return list;
    }

    function renderRoster() {
        if (!elements.roster) return;

        const visible = visibleOpponents();

        // Drop selection if that combatant left; default to whoever remains
        const selectionValid = visible.some(
            o => sameCombatant(o, currentBattle.selectedTarget)
        );
        if (!selectionValid) {
            currentBattle.selectedTarget = null;
        }
        if (!currentBattle.selectedTarget && visible.length > 0) {
            currentBattle.selectedTarget = combatantKey(visible[0]);
        }

        if (!visible.length && !dyingCards.size) {
            elements.roster.innerHTML = '<div class="combat-roster-empty">No opponents</div>';
        } else {
            const frag = document.createDocumentFragment();
            visible.forEach(function (opponent) {
                const wrap = document.createElement('div');
                wrap.innerHTML = cardHtml(opponent);
                if (wrap.firstChild) frag.appendChild(wrap.firstChild);
            });
            elements.roster.innerHTML = '';
            elements.roster.appendChild(frag);
            // Re-hold each smashing card's slot so live cards keep their spots.
            dyingCards.forEach(function (entry) {
                const at = Math.min(entry.index, elements.roster.children.length);
                elements.roster.insertBefore(
                    entry.placeholder, elements.roster.children[at] || null
                );
            });
            bindRosterEvents();
        }

        rosterOrder = visible.map(combatantKey);

        const selected = visible.find(
            o => sameCombatant(o, currentBattle.selectedTarget)
        );
        if (selected && selected.is_monster && selected.type_id && typeof MonsterAssets !== 'undefined') {
            MonsterAssets.ensureType(selected.type_id, null, selected.portrait || null);
        }

        renderSelfCard();
        syncSpellCancelBtn();
    }

    function ingestCombatants(list, viewerId) {
        if (Array.isArray(list)) {
            currentBattle.combatants = list;
        }
        if (viewerId) {
            currentBattle.viewerId = viewerId;
        }
        if (!currentBattle.viewerId) {
            const el = document.getElementById('player-id');
            if (el && el.value) currentBattle.viewerId = el.value;
        }
        syncSelfFromCombatants();
        if (typeof CombatSocial !== 'undefined' && CombatSocial.updateAvailability) {
            CombatSocial.updateAvailability(
                currentBattle.combatants,
                currentBattle.viewerId
            );
        }
    }

    /**
     * Adopt a server opponent list. While a card is smashing, anyone new is
     * held back so the roster never grows past the slot count it had at death.
     */
    function applyOpponents(list) {
        const incoming = list || [];
        if (dyingMonsters.size) {
            incoming.forEach(function (o) {
                const key = combatantKey(o);
                if (key && rosterOrder.indexOf(key) === -1) {
                    deferredJoins.add(key);
                }
            });
        }
        deferredJoins.forEach(function (key) {
            if (!incoming.some(o => sameCombatant(o, key))) {
                deferredJoins.delete(key);
            }
        });
        currentBattle.opponents = incoming;
    }

    function opponentsFromCombatants(list, viewerId) {
        const me = viewerId || currentBattle.viewerId;
        return (list || []).filter(c => {
            if (c.is_monster) return true;
            return c.id !== me;
        });
    }

    function handleCombatStart(data) {
        Sound.warm();
        const isJoinRefresh = !!data.is_join_refresh;
        const wasOpen = open;
        const priorMonsterKeys = {};
        (currentBattle.opponents || []).forEach(function (o) {
            if (o && o.is_monster) {
                const key = combatantKey(o);
                if (key) priorMonsterKeys[key] = true;
            }
        });
        dyingMonsters.forEach(function (key) {
            priorMonsterKeys[key] = true;
        });
        deferredJoins.forEach(function (key) {
            priorMonsterKeys[key] = true;
        });
        if (!isJoinRefresh) {
            clearCombatLog();
        }
        currentBattle.battleId = data.battle_id;
        currentBattle.viewerId = data.viewer_id || currentBattle.viewerId;
        ingestCombatants(data.combatants, data.viewer_id);
        applyOpponents(data.opponents || opponentsFromCombatants(
            data.combatants, currentBattle.viewerId
        ));
        if (isJoinRefresh && wasOpen) {
            const newcomers = (currentBattle.opponents || []).some(function (o) {
                if (!o || !o.is_monster) return false;
                const key = combatantKey(o);
                return key && !priorMonsterKeys[key];
            });
            if (newcomers) {
                if (dyingMonsters.size) {
                    pendingEnterBattleSound = true;
                } else {
                    Sound.play('enterbattle');
                }
            }
        }
        if (!isJoinRefresh) {
            currentBattle.selectedTarget = null;
            resetPendingCombatAction();
        }
        showOverlay();
        renderRoster();
        updateButtonStates(data.your_turn);
        // A resume on a screen that never lost the battle is a silent refresh,
        // so a mobile socket blip does not spam the log.
        if (!data.is_resume || !wasOpen) {
            let startMsg;
            if (data.message) {
                startMsg = data.message;
            } else if (data.your_turn) {
                startMsg = "Combat has begun! It's your turn to act!";
            } else {
                startMsg = 'Combat has begun! Select your target and action.';
            }
            appendCombatLog(startMsg);
            showStatusMessage(startMsg);
        }
        if (data.turn_timeout) {
            startCountdown(data.turn_timeout, data.your_turn, data.active_player);
        }
    }

    function handleTargetRequest(data) {
        applyOpponents(data.targets || []);
        renderRoster();
        showStatusMessage('Select a target for your action.');
        appendCombatLog('Select a target for your action.');
    }

    function handleCombatAction(data) {
        // Action consumed the prior turn — drop its countdown so "Your turn"
        // cannot resurface after the status-hold while a monster acts.
        stopCountdown();
        beginCombatFxHold(data);
        if (data.play_spell_sound) {
            const spellKillKeys = [];
            if (data.combatants) {
                (data.combatants || []).forEach(function (c) {
                    if (c && c.is_monster && Number(c.hp) <= 0) {
                        const key = combatantKey(c);
                        if (key) {
                            spellKillKeys.push(key);
                            pendingSpellDefeats.add(key);
                        }
                    }
                });
            }
            playSpellCastFx(function () {
                if (data.play_hit_sound && typeof Sound !== 'undefined') {
                    Sound.play('hit');
                }
                if (data.shake_combat) {
                    playHitShake(data.shake_target);
                }
                // Let the impact land, then smash — not during the cast flash.
                const afterImpact = Math.max(
                    CARD_SHAKE_MS,
                    soundDurationMs('hit', 0.25)
                );
                setTimeout(function () {
                    spellKillKeys.forEach(function (key) {
                        pendingSpellDefeats.delete(key);
                        playMonsterDefeat(key);
                    });
                }, data.play_hit_sound || data.shake_combat ? afterImpact : 0);
            });
        } else if (data.play_hit_sound) {
            Sound.play('hit');
        }
        if (!data.play_spell_sound && data.play_miss_sound) {
            Sound.play(data.play_miss_sound);
        }

        updateButtonStates(data.your_turn);
        if (data.message) {
            showStatusMessage(data.message);
            appendCombatLog(data.message);
        }

        if (elements.opponentThinking) {
            elements.opponentThinking.style.display = 'none';
        }

        if (data.combatants) {
            const me = currentBattle.viewerId
                || (document.getElementById('player-id') || {}).value;
            ingestCombatants(data.combatants, me);
            applyOpponents(opponentsFromCombatants(data.combatants, me));
            // Do not paint the next actor's turn box while this hit is still playing.
            if (combatActionFxMs(data) > 0) {
                currentBattle.opponents.forEach(function (o) {
                    o.is_current_turn = false;
                });
                (currentBattle.combatants || []).forEach(function (c) {
                    c.is_current_turn = false;
                });
            }
            renderRoster();
            // Killing blow: HP paints at 0, then blood → smash during the pause.
            // Spell kills wait until cast + hit FX finish (scheduled above).
            if (!data.play_spell_sound) {
                (data.combatants || []).forEach(function (c) {
                    if (c && c.is_monster && Number(c.hp) <= 0) {
                        playMonsterDefeat(combatantKey(c));
                    }
                });
            }
        }
        if (data.your_hp) {
            const parsed = parseHpString(data.your_hp);
            if (parsed) {
                currentBattle.selfHp = parsed.hp;
                currentBattle.selfMhp = parsed.mhp;
                renderSelfCard();
            }
            const hp = document.getElementById('player-hp');
            if (hp) hp.textContent = data.your_hp;
        }
        if (data.your_mp) {
            const parsedMp = parseHpString(data.your_mp);
            if (parsedMp) {
                currentBattle.selfMp = parsedMp.hp;
                currentBattle.selfMmp = parsedMp.mhp;
                renderSelfCard();
            }
            const mp = document.getElementById('player-mp');
            if (mp) mp.textContent = data.your_mp;
        }
        // After roster/self redraw so the class is not wiped. Spells wait
        // until the hit clip so the twitch matches the impact.
        if (!data.play_spell_sound && data.shake_combat) {
            playHitShake(data.shake_target);
        }
    }

    function handleMonsterDeath(data) {
        if (data.message && !data.silent) {
            showStatusMessage(data.message);
            appendCombatLog(data.message);
        }
        const key = data.monster_id;
        // FX already running from the 0-HP combat_action — let smash finish.
        if (dyingMonsters.has(key)) return;
        // Spell cast still playing — defeat is scheduled after impact.
        if (pendingSpellDefeats.has(key)) return;
        // Still on roster (no prior FX) — play defeat, or drop immediately.
        if (currentBattle.opponents.some(o => sameCombatant(o, key))) {
            playMonsterDefeat(key);
            return;
        }
        removeOpponentByKey(key);
        renderRoster();
    }

    function handlePlayerDeath(data) {
        if (data.message) {
            showStatusMessage(data.message);
            appendCombatLog(data.message);
        }
        currentBattle.opponents = currentBattle.opponents.filter(
            o => o.is_monster || o.id !== data.player_id
        );
        renderRoster();
    }

    function handleCombatEnd(data) {
        stopCountdown();
        statusHoldUntil = 0;
        if (fxHoldTimer) {
            clearTimeout(fxHoldTimer);
            fxHoldTimer = null;
        }
        fxHoldUntil = 0;
        pendingTurnNotification = null;
        pendingSpellDefeats.clear();
        if (data.victory) Sound.play('victory');
        if (data.message) {
            appendCombatLog(data.message);
        }
        hideOverlay();
        Array.from(dyingCards.keys()).forEach(detachDyingCard);
        dyingMonsters.clear();
        deferredJoins.clear();
        pendingEnterBattleSound = false;
        rosterOrder = [];
        currentBattle = {
            battleId: null,
            opponents: [],
            combatants: [],
            selectedTarget: null,
            pendingSpellPick: null,
            viewerId: currentBattle.viewerId,
            selfHp: null,
            selfMhp: null,
            selfMp: null,
            selfMmp: null,
            selfLevel: null,
            selfName: null,
        };
        clearCombatLog();
        if (elements.roster) elements.roster.innerHTML = '';
        if (elements.selfCard) elements.selfCard.innerHTML = '';
        if (elements.status) elements.status.innerHTML = '';
        // Restoring the mobile pad changes the map pane size; force a fresh
        // viewport sync + paint so monsters aren't left blank until the next move.
        refreshMapAfterCombat();
    }

    function refreshMapAfterCombat() {
        if (typeof MapView !== 'undefined' && MapView.measureViewportNow) {
            const vp = MapView.measureViewportNow();
            if (vp && typeof SocketHandler !== 'undefined' && SocketHandler.setViewport) {
                SocketHandler.setViewport(vp.h, vp.w);
            }
        } else if (typeof UI !== 'undefined' && UI.requestMapUpdate) {
            UI.requestMapUpdate('combat-end');
        }
        if (typeof MapView !== 'undefined' && MapView.paint) {
            MapView.paint();
        }
    }

    function soundDurationMs(name, fallbackSec) {
        if (typeof Sound !== 'undefined' && Sound.duration) {
            const sec = Sound.duration(name);
            if (sec) return Math.round(sec * 1000);
        }
        return Math.round((fallbackSec || 0) * 1000);
    }

    function combatActionFxMs(data) {
        if (!data) return 0;
        let ms = 0;
        if (data.play_spell_sound) {
            ms += soundDurationMs('spell', 1.2);
        }
        if (data.play_hit_sound) {
            ms += Math.max(CARD_SHAKE_MS, soundDurationMs('hit', 0.35));
        } else if (data.play_miss_sound) {
            ms += soundDurationMs(data.play_miss_sound, 0.4);
        } else if (data.shake_combat) {
            ms += CARD_SHAKE_MS;
        }
        return ms;
    }

    function flushPendingTurnNotification() {
        if (fxHoldTimer) {
            clearTimeout(fxHoldTimer);
            fxHoldTimer = null;
        }
        fxHoldUntil = 0;
        const pending = pendingTurnNotification;
        pendingTurnNotification = null;
        if (pending) {
            applyTurnNotification(pending);
        }
    }

    function beginCombatFxHold(data) {
        const ms = combatActionFxMs(data);
        if (fxHoldTimer) {
            clearTimeout(fxHoldTimer);
            fxHoldTimer = null;
        }
        if (ms <= 0) {
            fxHoldUntil = 0;
            return;
        }
        const now = (typeof performance !== 'undefined' && performance.now)
            ? performance.now() : Date.now();
        fxHoldUntil = now + ms;
        fxHoldTimer = setTimeout(flushPendingTurnNotification, ms);
    }

    function handleTurnNotification(data) {
        const now = (typeof performance !== 'undefined' && performance.now)
            ? performance.now() : Date.now();
        if (fxHoldUntil && now < fxHoldUntil) {
            pendingTurnNotification = data;
            return;
        }
        applyTurnNotification(data);
    }

    function applyTurnNotification(data) {
        // Turn boundaries cancel in-progress spell targeting so a timed-out
        // pick does not stick into the next round.
        resetPendingCombatAction();

        if (data.message && data.message.indexOf('forfeited') !== -1) {
            stopCountdown();
            showStatusMessage(data.message);
            appendCombatLog(data.message);
        } else if (data.turn_timeout) {
            startCountdown(data.turn_timeout, data.your_turn, data.active_player);
        } else if (data.message) {
            stopCountdown();
            showStatusMessage(data.message);
            appendCombatLog(data.message);
            if (elements.opponentThinking) {
                elements.opponentThinking.style.display = 'none';
            }
        } else if (!data.your_turn) {
            // Monster (or other) turn with no status text — kill stale "Your turn" timer.
            stopCountdown();
        }

        updateButtonStates(data.your_turn);

        if (data.combatants) {
            ingestCombatants(data.combatants, currentBattle.viewerId);
            applyOpponents(opponentsFromCombatants(
                data.combatants, currentBattle.viewerId
            ));
        } else if (data.active_player && currentBattle.opponents) {
            currentBattle.opponents.forEach(o => {
                o.is_current_turn = sameCombatant(o, data.active_player);
            });
            (currentBattle.combatants || []).forEach(c => {
                c.is_current_turn = sameCombatant(c, data.active_player);
            });
        }
        renderRoster();
    }

    function resetPendingCombatAction() {
        if (currentBattle.pendingSpellPick) {
            cancelSpellPick({ silent: true });
        }
        if (typeof InteractionUI === 'undefined' || !InteractionUI.isOpen
            || !InteractionUI.isOpen() || !InteractionUI.hidePrompt) {
            return;
        }
        const titleEl = document.getElementById('interaction-title');
        const title = titleEl ? String(titleEl.textContent || '') : '';
        if (title === 'Cast Spell' || title === 'Spells') {
            InteractionUI.hidePrompt();
        }
    }

    function processCombatUpdate(data) {
        switch (data.type) {
            case 'combat_start': handleCombatStart(data); break;
            case 'target_request': handleTargetRequest(data); break;
            case 'combat_action': handleCombatAction(data); break;
            case 'monster_death': handleMonsterDeath(data); break;
            case 'player_death': handlePlayerDeath(data); break;
            case 'combat_end': handleCombatEnd(data); break;
            case 'turn_notification': handleTurnNotification(data); break;
        }
    }

    function sendAction(action) {
        Sound.warm();
        if (action === 'item') {
            if (typeof InventoryUI !== 'undefined') {
                InventoryUI.open({
                    context: 'combat',
                    selectable: true,
                    items: InventoryUI.getInventory(),
                });
            }
            return;
        }
        if (action === 'spell') {
            if (currentBattle.pendingSpellPick) {
                cancelSpellPick({ reopenPicker: true, silent: true });
                return;
            }
            openSpellPicker();
            return;
        }
        if (action === 'spell-cancel') {
            cancelSpellPick({ reopenPicker: true, silent: true });
            return;
        }
        if (window.socket) {
            window.socket.emit('combat_action', {
                action: action,
                target_id: currentBattle.selectedTarget
            });
        }
    }

    function bindScreenGuards() {
        if (!elements.screen) return;
        elements.screen.addEventListener('pointerdown', function (e) {
            e.stopPropagation();
        });
    }

    bindScreenGuards();
    bindMapPeek();

    /** Dev helper: play the defeat FX on a card without needing a real kill. */
    function previewDefeat(monsterId) {
        const key = monsterId || (currentBattle.opponents.find(o => o.is_monster)
            && combatantKey(currentBattle.opponents.find(o => o.is_monster)));
        if (!key) return false;
        playMonsterDefeat(key);
        return true;
    }

    function handleEscape() {
        if (currentBattle.pendingSpellPick) {
            cancelSpellPick({ reopenPicker: true, silent: true });
            return true;
        }
        return false;
    }

    return {
        processCombatUpdate,
        sendAction,
        isOpen,
        previewDefeat,
        appendLog: appendCombatLog,
        playSpellCastFx: playSpellCastFx,
        handleEscape: handleEscape,
    };
})();

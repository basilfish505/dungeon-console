// combat.js - Full-screen combat UI and actions
const Combat = (function () {
    const MAX_COMBAT_LOG_LINES = 12;
    /** Every battle message stays on the status bar at least this long. */
    const STATUS_HOLD_MS = 1000;

    const elements = {
        overlay: document.getElementById('combat-overlay'),
        screen: document.getElementById('combat-screen'),
        status: document.getElementById('combat-status'),
        roster: document.getElementById('combat-roster'),
        selfCard: document.getElementById('combat-self'),
        combatLog: document.getElementById('combat-log'),
        combatMessage: document.getElementById('combat-message'),
        opponentThinking: document.getElementById('opponent-thinking'),
        attackBtn: document.getElementById('attack-btn'),
        defendBtn: document.getElementById('defend-btn'),
        spellBtn: document.getElementById('spell-btn'),
        itemBtn: document.getElementById('item-btn'),
        runBtn: document.getElementById('run-btn'),
        mapPeekBtn: document.getElementById('map-peek-btn'),
        mobileControls: document.getElementById('mobile-controls'),
    };

    let currentBattle = {
        battleId: null,
        opponents: [],
        combatants: [],
        selectedTarget: null,
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
            .map(line => {
                const cls = /damage|hit|slay|defeat|miss/i.test(line)
                    ? 'combat-log-line combat-log-damage'
                    : 'combat-log-line';
                return `<div class="${cls}">${escapeHtml(line)}</div>`;
            })
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
        if (elements.combatMessage) {
            elements.combatMessage.innerHTML = html;
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
                `Waiting for ${escapeHtml(countdownActivePlayer || 'opponent')} ` +
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
        if (elements.attackBtn) elements.attackBtn.disabled = disableAll;
        if (elements.defendBtn) elements.defendBtn.disabled = disableAll;
        if (elements.spellBtn) elements.spellBtn.disabled = true;
        if (elements.itemBtn) elements.itemBtn.disabled = disableAll;
        if (elements.runBtn) elements.runBtn.disabled = true;
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

    function displayName(c) {
        if (!c) return 'Unknown';
        return c.name || c.id || 'Unknown';
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
        elements.selfCard.className = 'combat-self' + (turn ? ' current-turn' : '');
        elements.selfCard.innerHTML =
            `<div class="combat-self-meta">` +
            `<span class="combat-self-name">${escapeHtml(name)}</span>` +
            `<span class="combat-level-badge">Lv ${escapeHtml(level)}</span>` +
            (defending ? '<span class="combat-badge-defend">Defend</span>' : '') +
            (turn ? '<span class="combat-badge-turn">Your turn</span>' : '') +
            `</div>` +
            hpBarHtml(hp, mhp) +
            mpBarHtml(mp, mmp);
    }

    function inspectTarget(combatant, ev) {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
        if (!combatant) return;
        const tid = combatant.is_monster
            ? (combatant.monster_id || combatant.id)
            : combatant.id;
        if (typeof SocketHandler !== 'undefined' && SocketHandler.inspectCombatant) {
            SocketHandler.inspectCombatant(tid);
        }
    }

    function selectTarget(combatant) {
        if (!combatant) return;
        currentBattle.selectedTarget = combatant.id;
        renderRoster();
    }

    function cardHtml(opponent) {
        const name = displayName(opponent);
        const level = opponent.level != null ? opponent.level : '?';
        const turn = opponent.is_current_turn ? '→ ' : '';
        const selected = currentBattle.selectedTarget === opponent.id;
        const key = combatantKey(opponent);
        const url = portraitUrl(opponent);
        let classes = 'combat-card';
        if (opponent.is_monster) classes += ' combat-card-enemy';
        else classes += ' combat-card-player';
        if (selected) classes += ' selected-target';
        if (opponent.is_current_turn) classes += ' current-turn';
        if (opponent.defending) classes += ' defending';

        const portrait = url
            ? `<button type="button" class="combat-card-portrait-btn" data-inspect="1" aria-label="Inspect ${escapeHtml(name)}">` +
              `<img class="combat-card-portrait" src="${escapeHtml(url)}" alt="">` +
              `<span class="combat-card-info" aria-hidden="true">i</span>` +
              `</button>`
            : `<button type="button" class="combat-card-portrait-btn combat-card-portrait-empty" data-inspect="1" aria-label="Inspect ${escapeHtml(name)}">` +
              `<span class="combat-card-info" aria-hidden="true">i</span>` +
              `</button>`;

        return (
            `<div class="${classes}" data-id="${escapeHtml(opponent.id)}" data-key="${escapeHtml(key || '')}" role="button" tabindex="0">` +
            portrait +
            `<div class="combat-card-body">` +
            `<div class="combat-card-header">` +
            `<span class="combat-card-name">${turn}${escapeHtml(name)}</span>` +
            `<span class="combat-level-badge">Lv ${escapeHtml(level)}</span>` +
            `</div>` +
            hpBarHtml(opponent.hp, opponent.mhp) +
            (opponent.defending ? '<span class="combat-badge-defend">Defend</span>' : '') +
            `</div>` +
            `</div>`
        );
    }

    function bindRosterEvents() {
        if (!elements.roster) return;
        elements.roster.querySelectorAll('.combat-card').forEach(function (el) {
            const id = el.getAttribute('data-id');
            const opponent = currentBattle.opponents.find(o => o.id === id);
            el.addEventListener('click', function (e) {
                if (e.target && e.target.closest && e.target.closest('[data-inspect]')) {
                    inspectTarget(opponent, e);
                    return;
                }
                selectTarget(opponent);
            });
            el.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    selectTarget(opponent);
                }
            });
        });
    }

    function renderRoster() {
        if (!elements.roster) return;

        // Drop selection if that combatant left; default to whoever remains
        const selectionValid = currentBattle.opponents.some(
            o => o.id === currentBattle.selectedTarget
        );
        if (!selectionValid) {
            currentBattle.selectedTarget = null;
        }
        if (!currentBattle.selectedTarget && currentBattle.opponents.length > 0) {
            currentBattle.selectedTarget = currentBattle.opponents[0].id;
        }

        if (!currentBattle.opponents.length) {
            elements.roster.innerHTML = '<div class="combat-roster-empty">No opponents</div>';
        } else {
            elements.roster.innerHTML = currentBattle.opponents.map(cardHtml).join('');
            bindRosterEvents();
        }

        const selected = currentBattle.opponents.find(
            o => o.id === currentBattle.selectedTarget
        );
        if (selected && selected.is_monster && selected.type_id && typeof MonsterAssets !== 'undefined') {
            MonsterAssets.ensureType(selected.type_id, null, selected.portrait || null);
        }

        renderSelfCard();
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
        clearCombatLog();
        currentBattle.battleId = data.battle_id;
        currentBattle.viewerId = data.viewer_id || currentBattle.viewerId;
        ingestCombatants(data.combatants, data.viewer_id);
        currentBattle.opponents = data.opponents || opponentsFromCombatants(
            data.combatants, currentBattle.viewerId
        );
        currentBattle.selectedTarget = null;
        showOverlay();
        renderRoster();
        updateButtonStates(data.your_turn);
        const startMsg = data.your_turn
            ? "Combat has begun! It's your turn to act!"
            : 'Combat has begun! Select your target and action.';
        appendCombatLog(data.message || startMsg);
        showStatusMessage(data.message || startMsg);
        if (data.turn_timeout) {
            startCountdown(data.turn_timeout, data.your_turn, data.active_player);
        }
    }

    function handleTargetRequest(data) {
        currentBattle.opponents = data.targets || [];
        renderRoster();
        showStatusMessage('Select a target for your action.');
        appendCombatLog('Select a target for your action.');
    }

    function handleCombatAction(data) {
        if (data.play_hit_sound) Sound.play('hit');
        if (data.shake_combat) shakeCombatWindow();

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
            currentBattle.opponents = opponentsFromCombatants(data.combatants, me);
            renderRoster();
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
    }

    function handleMonsterDeath(data) {
        if (data.message && !data.silent) {
            showStatusMessage(data.message);
            appendCombatLog(data.message);
        }
        currentBattle.opponents = currentBattle.opponents.filter(
            o => !(o.is_monster && (
                o.id === data.monster_id
                || o.monster_id === data.monster_id
                || o.type_id === data.monster_id
            ))
        );
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
        if (data.victory) Sound.play('victory');
        if (data.message) {
            appendCombatLog(data.message);
        }
        hideOverlay();
        currentBattle = {
            battleId: null,
            opponents: [],
            combatants: [],
            selectedTarget: null,
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
    }

    function handleTurnNotification(data) {
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
        }

        updateButtonStates(data.your_turn);

        if (data.combatants) {
            ingestCombatants(data.combatants, currentBattle.viewerId);
            currentBattle.opponents = opponentsFromCombatants(
                data.combatants, currentBattle.viewerId
            );
        } else if (data.active_player && currentBattle.opponents) {
            currentBattle.opponents.forEach(o => {
                o.is_current_turn = (o.id === data.active_player);
            });
            (currentBattle.combatants || []).forEach(c => {
                c.is_current_turn = (c.id === data.active_player)
                    || (c.monster_id && c.monster_id === data.active_player);
            });
        }
        renderRoster();
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

    return { processCombatUpdate, sendAction, isOpen };
})();

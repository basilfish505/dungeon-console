// combat.js - Combat UI and actions
const Combat = (function () {
    const MAX_COMBAT_LOG_LINES = 12;

    const elements = {
        combatBox: document.getElementById('combat-box'),
        opponentName: document.getElementById('opponent-name'),
        opponentHP: document.getElementById('opponent-hp'),
        opponentPortrait: document.getElementById('opponent-portrait'),
        combatLog: document.getElementById('combat-log'),
        combatMessage: document.getElementById('combat-message'),
        opponentThinking: document.getElementById('opponent-thinking'),
        opponentsList: document.getElementById('opponents-list'),
        attackBtn: document.getElementById('attack-btn'),
        defendBtn: document.getElementById('defend-btn'),
        spellBtn: document.getElementById('spell-btn'),
        itemBtn: document.getElementById('item-btn'),
        runBtn: document.getElementById('run-btn')
    };

    let currentBattle = { battleId: null, opponents: [], selectedTarget: null };
    let combatLogLines = [];
    let countdownTimer = null;
    let countdownRemaining = 0;
    let countdownYourTurn = false;
    let countdownActivePlayer = null;

    function stripHtml(html) {
        const tmp = document.createElement('div');
        tmp.innerHTML = html;
        return (tmp.textContent || tmp.innerText || '').replace(/\s+/g, ' ').trim();
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
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
        // Skip noisy status/countdown lines
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
        if (!elements.combatBox) return;
        elements.combatBox.classList.remove('combat-shake');
        void elements.combatBox.offsetWidth;
        elements.combatBox.classList.add('combat-shake');
        setTimeout(() => elements.combatBox.classList.remove('combat-shake'), 500);
    }

    function stopCountdown() {
        if (countdownTimer) {
            clearInterval(countdownTimer);
            countdownTimer = null;
        }
    }

    function renderCountdownMessage() {
        const secs = Math.max(0, countdownRemaining);
        // Status line only — never mirror into opponent-thinking (avoids duplicate text)
        elements.opponentThinking.style.display = 'none';
        if (countdownYourTurn) {
            elements.combatMessage.innerHTML = `It's your turn to act! (${secs}s)`;
        } else {
            elements.combatMessage.innerHTML =
                `Waiting for ${countdownActivePlayer || 'opponent'} to take their turn... (${secs}s)`;
        }
    }

    function startCountdown(seconds, isYourTurn, activePlayer) {
        stopCountdown();
        if (!seconds || seconds <= 0) return;
        countdownRemaining = seconds;
        countdownYourTurn = !!isYourTurn;
        countdownActivePlayer = activePlayer || null;
        renderCountdownMessage();
        countdownTimer = setInterval(function () {
            countdownRemaining -= 1;
            renderCountdownMessage();
            if (countdownRemaining <= 0) stopCountdown();
        }, 1000);
    }

    function updateButtonStates(isYourTurn) {
        const disableAll = isYourTurn === false;
        elements.attackBtn.disabled = disableAll;
        elements.defendBtn.disabled = disableAll;
        elements.spellBtn.disabled = true;
        elements.itemBtn.disabled = disableAll;
        elements.runBtn.disabled = true;
        // Keep a single status line in #combat-message; hide the secondary thinking line
        elements.opponentThinking.style.display = 'none';
        if (disableAll && !countdownTimer) {
            elements.combatMessage.innerHTML = "Waiting for opponent's move...";
        }
    }

    function setOpponentPortrait(opponent) {
        const img = elements.opponentPortrait;
        if (!img) {
            return;
        }
        if (!opponent || !opponent.is_monster) {
            img.hidden = true;
            img.removeAttribute('src');
            return;
        }
        const typeId = opponent.type_id;
        const url = opponent.portrait || null;
        if (typeof MonsterAssets !== 'undefined' && typeId) {
            MonsterAssets.ensureType(typeId, null, url);
        }
        const resolved = url || (typeId ? '/static/monsters/portraits/' + typeId + '.png' : null);
        if (!resolved) {
            img.hidden = true;
            img.removeAttribute('src');
            return;
        }
        img.src = resolved;
        img.alt = (opponent.id || 'Monster') + ' portrait';
        img.hidden = false;
    }

    function updateOpponentsList() {
        if (!elements.opponentsList) {
            elements.opponentsList = document.createElement('div');
            elements.opponentsList.id = 'opponents-list';
            elements.opponentsList.className = 'opponents-list';
            elements.combatBox.appendChild(elements.opponentsList);
        }

        elements.opponentsList.innerHTML = '<h4>Combatants:</h4>';
        currentBattle.opponents.forEach((opponent, index) => {
            const el = document.createElement('div');
            el.className = 'opponent-entry';
            el.dataset.id = opponent.is_monster ? (opponent.monster_id || opponent.id) : opponent.id;
            if (currentBattle.selectedTarget === opponent.id) el.classList.add('selected-target');
            if (opponent.is_current_turn) el.classList.add('current-turn');

            const turn = opponent.is_current_turn ? '→ ' : '';
            const kind = opponent.is_monster ? ' (Monster)' : '';
            el.innerHTML =
                `<span class="opponent-name">${turn}${opponent.id}${kind}</span>` +
                `<span class="opponent-hp">HP: ${opponent.hp}</span>`;

            el.addEventListener('click', function () {
                currentBattle.selectedTarget = opponent.id;
                document.querySelectorAll('.opponent-entry').forEach(n => n.classList.remove('selected-target'));
                this.classList.add('selected-target');
                elements.opponentName.textContent = opponent.id;
                elements.opponentHP.textContent = opponent.hp;
                setOpponentPortrait(opponent);
            });
            elements.opponentsList.appendChild(el);
        });

        // Drop selection if that combatant left (e.g. eliminated); default to whoever remains
        const selectionValid = currentBattle.opponents.some(
            o => o.id === currentBattle.selectedTarget
        );
        if (!selectionValid) {
            currentBattle.selectedTarget = null;
        }

        if (!currentBattle.selectedTarget && currentBattle.opponents.length > 0) {
            currentBattle.selectedTarget = currentBattle.opponents[0].id;
            const first = elements.opponentsList.querySelector('.opponent-entry');
            if (first) first.classList.add('selected-target');
        }

        const selected = currentBattle.opponents.find(o => o.id === currentBattle.selectedTarget);
        if (selected) {
            elements.opponentName.textContent = selected.id;
            elements.opponentHP.textContent = selected.hp;
            setOpponentPortrait(selected);
        } else {
            setOpponentPortrait(null);
        }
    }

    function handleCombatStart(data) {
        Sound.warm();
        clearCombatLog();
        currentBattle.battleId = data.battle_id;
        currentBattle.opponents = data.opponents;
        elements.combatBox.style.display = 'block';
        updateOpponentsList();
        updateButtonStates(data.your_turn);
        const startMsg = data.your_turn
            ? "Combat has begun! It's your turn to act!"
            : 'Combat has begun! Select your target and action.';
        appendCombatLog(data.message || startMsg);
        if (data.turn_timeout) {
            startCountdown(data.turn_timeout, data.your_turn, data.active_player);
        } else {
            elements.combatMessage.innerHTML = startMsg;
        }
    }

    function handleTargetRequest(data) {
        currentBattle.opponents = data.targets;
        updateOpponentsList();
        elements.combatMessage.innerHTML = 'Select a target for your action.';
        appendCombatLog('Select a target for your action.');
    }

    function handleCombatAction(data) {
        // FX first — same flags for attacker and defender keep them in sync
        if (data.play_hit_sound) Sound.play('hit');
        if (data.shake_combat) shakeCombatWindow();

        updateButtonStates(data.your_turn);
        if (data.message) {
            elements.combatMessage.innerHTML = data.message;
            appendCombatLog(data.message);
        }

        elements.opponentThinking.style.display = 'none';

        if (data.combatants) {
            const me = document.getElementById('player-id').value;
            currentBattle.opponents = data.combatants.filter(c => c.id !== me);
            updateOpponentsList();
        }
        if (data.your_hp) {
            const hp = document.getElementById('player-hp');
            if (hp) hp.textContent = data.your_hp;
        }
    }

    function handleMonsterDeath(data) {
        elements.combatMessage.innerHTML = data.message;
        appendCombatLog(data.message);
        currentBattle.opponents = currentBattle.opponents.filter(
            o => !(o.is_monster && o.id === data.monster_id)
        );
        updateOpponentsList();
    }

    function handlePlayerDeath(data) {
        elements.combatMessage.innerHTML = data.message;
        appendCombatLog(data.message);
        currentBattle.opponents = currentBattle.opponents.filter(
            o => o.is_monster || o.id !== data.player_id
        );
        updateOpponentsList();
    }

    function handleCombatEnd(data) {
        stopCountdown();
        if (data.victory) Sound.play('victory');
        if (data.message) appendCombatLog(data.message);
        elements.combatBox.style.display = 'none';
        currentBattle = { battleId: null, opponents: [], selectedTarget: null };
        setOpponentPortrait(null);
        clearCombatLog();
    }

    function handleTurnNotification(data) {
        updateButtonStates(data.your_turn);
        if (data.message && data.message.indexOf('forfeited') !== -1) {
            stopCountdown();
            elements.combatMessage.innerHTML = data.message;
            appendCombatLog(data.message);
        } else if (data.turn_timeout) {
            startCountdown(data.turn_timeout, data.your_turn, data.active_player);
        } else if (data.message) {
            stopCountdown();
            elements.combatMessage.innerHTML = data.message;
            appendCombatLog(data.message);
            elements.opponentThinking.style.display = 'none';
        }

        if (data.active_player && currentBattle.opponents) {
            currentBattle.opponents.forEach(o => {
                o.is_current_turn = (o.id === data.active_player);
            });
            updateOpponentsList();
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
        if (window.socket) {
            window.socket.emit('combat_action', {
                action: action,
                target_id: currentBattle.selectedTarget
            });
        }
    }

    return { processCombatUpdate, sendAction };
})();

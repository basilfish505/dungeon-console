/**
 * ChestUI - "You found a Scroll of Town Recall and 87 PQG." take / leave prompt.
 *
 * The server sends the chest under the player in game_state (player.chest,
 * null when not on one) and owns the contents: each reward can only be claimed
 * once and other players share the same chest. A chest holds one to three
 * items plus maybe some PQG, and every reward gets its own Take / Leave pair.
 * Leaving a reward only hides it for this visit; it stays in the chest.
 * Stepping off the tile and back on shows what remains.
 */
const ChestUI = (function () {
    const PLACEHOLDER = '/static/items/sprites/placeholder.png';
    const PQG_KEY = 'pqg';
    const POLL_MS = 400;

    let chest = null;
    let left = Object.create(null);   // reward key -> left behind this visit
    let dismissedSlot = null;
    let busy = false;
    let note = '';
    let pollTimer = null;
    let keyHandlerBound = false;

    function el(id) {
        return document.getElementById(id);
    }

    function combatOpen() {
        return typeof Combat !== 'undefined' && Combat.isOpen && Combat.isOpen();
    }

    function isOpen() {
        const overlay = el('chest-prompt');
        return !!overlay && !overlay.hidden;
    }

    function hide() {
        const overlay = el('chest-prompt');
        if (!overlay) return;
        overlay.hidden = true;
        overlay.setAttribute('aria-hidden', 'true');
    }

    function iconUrl(item) {
        if (typeof ItemAssets !== 'undefined' && ItemAssets.getUrl) {
            return ItemAssets.getUrl(item.type_id, item.image);
        }
        return item.image || PLACEHOLDER;
    }

    function items() {
        return (chest && chest.items) || [];
    }

    /** Rewards still in the chest and not left behind by this player. */
    function pending() {
        const out = items().filter(function (item) { return !left[item.uid]; });
        if (chest && chest.pqg > 0 && !left[PQG_KEY]) {
            out.push({ uid: PQG_KEY });
        }
        return out;
    }

    function updateButtons() {
        const buttons = document.querySelectorAll('#chest-prompt .loot-btn');
        Array.prototype.forEach.call(buttons, function (btn) {
            btn.disabled = busy;
        });
    }

    function actionButtons(key, onTake) {
        const actions = document.createElement('div');
        actions.className = 'chest-row-actions';
        const take = document.createElement('button');
        take.type = 'button';
        take.className = 'loot-btn';
        take.textContent = 'Take';
        take.addEventListener('click', onTake);
        const skip = document.createElement('button');
        skip.type = 'button';
        skip.className = 'loot-btn loot-btn-discard';
        skip.textContent = 'Leave';
        skip.addEventListener('click', function () { leave(key); });
        actions.appendChild(take);
        actions.appendChild(skip);
        return actions;
    }

    function itemRow(item) {
        const row = document.createElement('div');
        row.className = 'chest-row';
        const icon = document.createElement('img');
        icon.className = 'loot-icon';
        icon.src = iconUrl(item);
        icon.alt = item.name || '';
        const label = document.createElement('span');
        label.className = 'chest-label';
        label.textContent = item.label;
        row.appendChild(icon);
        row.appendChild(label);
        row.appendChild(actionButtons(item.uid, function () {
            claim('item', item.uid);
        }));
        return row;
    }

    function show() {
        const overlay = el('chest-prompt');
        if (!overlay || !chest) return;
        const text = el('chest-prompt-text');
        if (text) text.textContent = chest.text || 'You found a treasure chest.';
        const noteEl = el('chest-prompt-note');
        if (noteEl) noteEl.textContent = note;

        const list = el('chest-items');
        if (list) {
            list.textContent = '';
            items().forEach(function (item) {
                if (!left[item.uid]) {
                    list.appendChild(itemRow(item));
                }
            });
        }

        const pqgRow = el('chest-pqg-row');
        const showPqg = !!(chest.pqg > 0 && !left[PQG_KEY]);
        if (pqgRow) {
            pqgRow.hidden = !showPqg;
            const label = el('chest-pqg-label');
            if (label) label.textContent = chest.pqg + ' PQG';
        }

        const wasHidden = overlay.hidden;
        overlay.hidden = false;
        overlay.setAttribute('aria-hidden', 'false');
        updateButtons();
        if (wasHidden) {
            const first = overlay.querySelector('.loot-btn');
            if (first && first.focus) first.focus({ preventScroll: true });
        }
    }

    function stopPolling() {
        if (!pollTimer) return;
        clearInterval(pollTimer);
        pollTimer = null;
    }

    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(render, POLL_MS);
    }

    /** Show the prompt while something is left to decide and no battle is on screen. */
    function render() {
        if (!chest || dismissedSlot === chest.slot_id || !pending().length) {
            if (chest && !pending().length) {
                dismissedSlot = chest.slot_id;
            }
            hide();
            stopPolling();
            return;
        }
        if (combatOpen()) {
            hide();
            startPolling();
            return;
        }
        stopPolling();
        show();
    }

    /** Called with every game_state: the chest under the player, or null. */
    function setChest(next) {
        if (!next) {
            reset();
            return;
        }
        if (!chest || chest.slot_id !== next.slot_id) {
            left = Object.create(null);
            busy = false;
            note = '';
        }
        chest = next;
        render();
    }

    function claim(what, itemId) {
        if (!chest || busy) return;
        if (typeof SocketHandler === 'undefined' || !SocketHandler.sendChestClaim) return;
        busy = true;
        updateButtons();
        SocketHandler.sendChestClaim({
            slot_id: chest.slot_id,
            what: what,
            item_id: itemId || null,
        });
    }

    function leave(key) {
        if (!chest || busy) return;
        left[key] = true;
        note = '';
        render();
    }

    /** Server answer to a claim. A full pack or a lost race leaves a note. */
    function handleResult(data) {
        busy = false;
        if (data && !data.ok && data.message) {
            note = data.message;
        } else {
            note = '';
        }
        render();
    }

    /** While the prompt is up, keys must not move the player; Escape leaves everything. */
    function onKeyDown(e) {
        if (!isOpen()) return;
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (e.key === 'Tab') {
            e.stopImmediatePropagation();
            return;
        }
        e.stopImmediatePropagation();
        e.preventDefault();
        if (e.repeat) return;
        if (e.key === 'Escape') {
            pending().forEach(function (reward) { left[reward.uid] = true; });
            render();
            return;
        }
        if (e.key === 'Enter' || e.key === ' ') {
            const active = document.activeElement;
            if (active && active.classList && active.classList.contains('loot-btn')) {
                active.click();
            }
        }
    }

    function init() {
        const takePqg = el('chest-take-pqg');
        if (takePqg) takePqg.addEventListener('click', function () { claim('pqg'); });
        const leavePqg = el('chest-leave-pqg');
        if (leavePqg) leavePqg.addEventListener('click', function () { leave(PQG_KEY); });
        if (!keyHandlerBound) {
            window.addEventListener('keydown', onKeyDown, true);
            keyHandlerBound = true;
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    /** Forget everything (character died / left the game). */
    function reset() {
        chest = null;
        left = Object.create(null);
        dismissedSlot = null;
        busy = false;
        note = '';
        stopPolling();
        hide();
    }

    return { setChest, handleResult, hide, reset, isOpen };
})();

/**
 * LootUI - "The goblin had a Ring of Strength +7." keep / discard prompt.
 *
 * Offers come from the server (player.pending_loot in game_state, and a
 * loot_offers event when a battle ends). The prompt waits until the combat
 * window is closed, shows one offer at a time, and cannot be dismissed
 * without answering. Pending offers are saved with the character, so they
 * come back after a reload.
 */
const LootUI = (function () {
    const PLACEHOLDER = '/static/items/sprites/placeholder.png';
    const POLL_MS = 400;

    let offers = [];
    let busy = false;
    let pollTimer = null;
    let note = '';
    let keyHandlerBound = false;

    function el(id) {
        return document.getElementById(id);
    }

    function combatOpen() {
        return typeof Combat !== 'undefined' && Combat.isOpen && Combat.isOpen();
    }

    function isOpen() {
        const overlay = el('loot-prompt');
        return !!overlay && !overlay.hidden;
    }

    function iconUrl(offer) {
        if (typeof ItemAssets !== 'undefined' && ItemAssets.getUrl) {
            return ItemAssets.getUrl(offer.type_id, offer.image);
        }
        return offer.image || PLACEHOLDER;
    }

    function hide() {
        const overlay = el('loot-prompt');
        if (!overlay) return;
        overlay.hidden = true;
        overlay.setAttribute('aria-hidden', 'true');
    }

    function show() {
        const overlay = el('loot-prompt');
        const offer = offers[0];
        if (!overlay || !offer) return;

        const text = el('loot-prompt-text');
        const noteEl = el('loot-prompt-note');
        const icon = el('loot-prompt-icon');
        const more = el('loot-prompt-more');
        if (text) {
            text.textContent = 'The ' + offer.monster_name + ' had a ' + offer.label + '.';
        }
        if (icon) {
            icon.src = iconUrl(offer);
            icon.alt = offer.name || '';
        }
        if (noteEl) {
            noteEl.textContent = note;
        }
        if (more) {
            more.textContent = offers.length > 1 ? (offers.length - 1) + ' more waiting' : '';
        }
        const wasHidden = overlay.hidden;
        overlay.hidden = false;
        overlay.setAttribute('aria-hidden', 'false');
        updateButtons();
        if (wasHidden) {
            const keep = el('loot-keep-btn');
            if (keep && keep.focus) keep.focus({ preventScroll: true });
        }
    }

    function updateButtons() {
        ['loot-keep-btn', 'loot-discard-btn'].forEach(function (id) {
            const btn = el(id);
            if (btn) btn.disabled = busy;
        });
    }

    /** Show the prompt when there is something to answer and no battle on screen. */
    function render() {
        if (!offers.length) {
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

    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(render, POLL_MS);
    }

    function stopPolling() {
        if (!pollTimer) return;
        clearInterval(pollTimer);
        pollTimer = null;
    }

    /** Replace the pending list (from game_state or a loot_offers event). */
    function setOffers(list) {
        if (!Array.isArray(list)) return;
        const firstBefore = offers.length ? offers[0].offer_id : null;
        offers = list.slice();
        const firstNow = offers.length ? offers[0].offer_id : null;
        if (firstBefore !== firstNow) {
            note = '';
            busy = false;
        }
        render();
    }

    function answer(action) {
        const offer = offers[0];
        if (!offer || busy) return;
        if (typeof SocketHandler === 'undefined' || !SocketHandler.sendLootDecision) return;
        busy = true;
        updateButtons();
        SocketHandler.sendLootDecision({ offer_id: offer.offer_id, action: action });
    }

    /** Server answer to keep / discard. A full pack leaves the offer up. */
    function handleResult(data) {
        busy = false;
        if (!data) {
            updateButtons();
            return;
        }
        if (data.ok) {
            offers = offers.filter(function (o) { return o.offer_id !== data.offer_id; });
            note = '';
        } else if (data.full) {
            note = data.message || 'Your pack is full.';
        } else if (data.message) {
            // Offer vanished (already answered elsewhere): drop it.
            offers = offers.filter(function (o) { return o.offer_id !== data.offer_id; });
            note = '';
        }
        render();
    }

    /** While the prompt is up, keys must not move the player or fire shortcuts. */
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
        if (e.key === 'Enter' || e.key === ' ') {
            const active = document.activeElement;
            if (active && (active.id === 'loot-keep-btn' || active.id === 'loot-discard-btn')) {
                active.click();
            }
        }
    }

    function init() {
        const keep = el('loot-keep-btn');
        const discard = el('loot-discard-btn');
        if (keep) keep.addEventListener('click', function () { answer('keep'); });
        if (discard) discard.addEventListener('click', function () { answer('discard'); });
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
        offers = [];
        busy = false;
        note = '';
        stopPolling();
        hide();
    }

    return { setOffers, handleResult, hide, reset, isOpen };
})();

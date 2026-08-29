// inventory_ui.js — 16-slot pack; hold-and-drag to reorder
const InventoryUI = (function () {
    const SLOT_COUNT = 16;
    const HOLD_MS = 280;
    const MOVE_CANCEL_PX = 14;
    // Actions are resolved per-item by category / equipped state.
    const ITEM_ACTIONS = [
        { id: 'use', label: 'Use' },
        { id: 'discard', label: 'Discard' },
    ];

    function actionsForItem(item) {
        if (!item) {
            return ITEM_ACTIONS.slice();
        }
        const cat = String(item.category || 'item').toLowerCase();
        const equipped = !!item.equipped;
        if (cat === 'weapon' || cat === 'armour') {
            if (equipped) {
                return [
                    { id: 'unequip', label: 'Unequip' },
                    { id: 'discard', label: 'Discard' },
                ];
            }
            return [
                { id: 'equip', label: 'Equip' },
                { id: 'discard', label: 'Discard' },
            ];
        }
        return ITEM_ACTIONS.slice();
    }
    let overlayEl = null;
    let gridEl = null;
    let detailEl = null;
    let titleEl = null;
    let context = 'exploration';
    let lastInventory = [];
    let spellsEl = null;
    let spellsListEl = null;
    let selectable = false;
    let viewingItem = null;

    let holdTimer = null;
    let pendingHold = null;
    let drag = null;
    let ghostEl = null;
    let suppressClick = false;

    function cacheDom() {
        if (overlayEl) {
            return;
        }
        overlayEl = document.getElementById('inventory-overlay');
        gridEl = document.getElementById('inventory-grid');
        detailEl = document.getElementById('inventory-detail');
        titleEl = document.getElementById('inventory-title');
        spellsEl = document.getElementById('action-spells');
        spellsListEl = document.getElementById('action-spells-list');
        const closeBtn = document.getElementById('inventory-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', close);
        }
        if (overlayEl) {
            overlayEl.addEventListener('click', function (e) {
                if (e.target === overlayEl) {
                    close();
                }
            });
        }
        const panelEl = document.getElementById('inventory-panel');
        if (panelEl) {
            panelEl.addEventListener('pointerdown', function (e) {
                e.stopPropagation();
            });
        }
        document.addEventListener('pointermove', onPointerMove);
        document.addEventListener('pointerup', onPointerUp);
        document.addEventListener('pointercancel', onPointerUp);
    }

    function normalizeSlots(items) {
        const slots = [];
        for (let i = 0; i < SLOT_COUNT; i++) {
            slots.push(null);
        }
        if (!Array.isArray(items)) {
            return slots;
        }
        if (items.length === SLOT_COUNT) {
            for (let i = 0; i < SLOT_COUNT; i++) {
                slots[i] = items[i] || null;
            }
            return slots;
        }
        items.forEach(function (item, i) {
            if (i < SLOT_COUNT && item) {
                slots[i] = item;
            }
        });
        return slots;
    }

    function setInventory(items) {
        if (drag) {
            return;
        }
        lastInventory = normalizeSlots(items);
        if (overlayEl && !overlayEl.hidden) {
            if (viewingItem) {
                const still = lastInventory.find(function (row) {
                    return row && row.instance_id === viewingItem.instance_id;
                });
                viewingItem = still || null;
            }
            render();
        }
    }

    function getInventory() {
        return lastInventory.slice();
    }

    function lightFuelRemaining(item) {
        if (!item || item.light_remaining == null) {
            return null;
        }
        return String(item.light_remaining);
    }

    function appendSlotName(slot, item) {
        const fuel = lightFuelRemaining(item);
        if (fuel != null) {
            const stack = document.createElement('span');
            stack.className = 'inventory-slot-label-stack';

            const title = document.createElement('span');
            title.className = 'inventory-slot-item-title';
            title.textContent = item.name || item.type_id || 'Item';
            stack.appendChild(title);

            const fuelEl = document.createElement('span');
            fuelEl.className = 'inventory-slot-fuel';
            fuelEl.textContent = fuel;
            stack.appendChild(fuelEl);

            slot.appendChild(stack);
            return title.textContent + ' ' + fuel;
        }

        const label = document.createElement('span');
        label.className = 'inventory-slot-name';
        label.textContent = item.name || item.type_id || 'Item';
        slot.appendChild(label);
        return label.textContent;
    }

    function open(opts) {
        cacheDom();
        if (!overlayEl) {
            return;
        }
        opts = opts || {};
        context = opts.context || 'exploration';
        selectable = !!opts.selectable;
        overlayEl.classList.toggle('inventory-overlay-overworld', context !== 'combat');
        viewingItem = null;
        endDrag();
        if (Array.isArray(opts.items)) {
            lastInventory = normalizeSlots(opts.items);
        } else {
            lastInventory = normalizeSlots(lastInventory);
        }
        render();
        overlayEl.hidden = false;
        overlayEl.setAttribute('aria-hidden', 'false');
    }

    function close() {
        cacheDom();
        if (!overlayEl) {
            return;
        }
        endDrag();
        overlayEl.hidden = true;
        overlayEl.setAttribute('aria-hidden', 'true');
        selectable = false;
        context = 'exploration';
        viewingItem = null;
        if (detailEl) {
            detailEl.innerHTML = '';
            detailEl.hidden = true;
        }
    }

    function hide() {
        close();
    }

    function handleEscape() {
        if (drag) {
            endDrag();
            render();
            return;
        }
        if (viewingItem) {
            viewingItem = null;
            render();
            return;
        }
        close();
    }

    function isOpen() {
        cacheDom();
        return !!(overlayEl && !overlayEl.hidden);
    }

    function render() {
        cacheDom();
        if (titleEl) {
            titleEl.textContent = context === 'combat' ? 'Use Item' : 'Action';
        }
        renderGrid();
        renderDetail(viewingItem);
        renderSpells();
    }

    function adjacentSpellTargets() {
        const selfId = (typeof MapView !== 'undefined' && MapView.state)
            ? MapView.state.playerId
            : (document.getElementById('player-id') || {}).value;
        const py = (typeof MapView !== 'undefined' && MapView.state)
            ? MapView.state.playerY
            : null;
        const px = (typeof MapView !== 'undefined' && MapView.state)
            ? MapView.state.playerX
            : null;
        const camY = (typeof MapView !== 'undefined' && MapView.state)
            ? MapView.state.cameraY
            : 0;
        const camX = (typeof MapView !== 'undefined' && MapView.state)
            ? MapView.state.cameraX
            : 0;
        const entities = (typeof MapView !== 'undefined' && MapView.state)
            ? (MapView.state.lastEntities || [])
            : [];
        const options = [];
        if (selfId) {
            options.push({ id: selfId, label: selfId + ' (you)' });
        }
        if (py == null || px == null) {
            return options;
        }
        entities.forEach(function (ent) {
            if (!ent || !ent.id) {
                return;
            }
            if (ent.kind !== 'player' && ent.kind !== 'monster') {
                return;
            }
            if (String(ent.id) === String(selfId)) {
                return;
            }
            const wy = camY + (ent.vy | 0);
            const wx = camX + (ent.vx | 0);
            const dist = Math.max(Math.abs(wy - py), Math.abs(wx - px));
            if (dist <= 1) {
                const label = ent.kind === 'monster'
                    ? (ent.type_id || ent.id)
                    : ent.id;
                options.push({ id: ent.id, label: label });
            }
        });
        return options;
    }

    function emitCastSpell(spellId, targetId) {
        if (!window.socket) {
            return;
        }
        window.socket.emit('cast_spell', {
            spell_id: spellId,
            target_id: targetId || null,
        });
        close();
    }

    function castExplorationSpell(spell) {
        if (!spell || !spell.castable) {
            return;
        }
        const options = adjacentSpellTargets();
        // Only self → auto-cast; any adjacent entity → picker (includes self).
        if (options.length <= 1) {
            emitCastSpell(spell.spell_id, options[0] ? options[0].id : null);
            return;
        }
        if (typeof InteractionUI === 'undefined' || !InteractionUI.showGenericPrompt) {
            emitCastSpell(spell.spell_id, options[0].id);
            return;
        }
        close();
        InteractionUI.showGenericPrompt({
            title: spell.name || 'Cast Spell',
            message: 'Choose a target.',
            choices: options.map(function (opt) {
                return { id: opt.id, label: opt.label };
            }).concat([{ id: '__cancel__', label: 'Cancel' }]),
            onChoice: function (choiceId) {
                if (!choiceId || choiceId === '__cancel__') {
                    return;
                }
                emitCastSpell(spell.spell_id, choiceId);
            },
        });
    }

    function renderSpells() {
        if (!spellsEl || !spellsListEl) {
            return;
        }
        if (context !== 'exploration') {
            spellsEl.hidden = true;
            spellsListEl.innerHTML = '';
            return;
        }
        const spells = (typeof SpellUI !== 'undefined' && SpellUI.getSpells)
            ? SpellUI.getSpells()
            : [];
        spellsListEl.innerHTML = '';
        if (!spells.length) {
            spellsEl.hidden = true;
            return;
        }
        spellsEl.hidden = false;
        spells.forEach(function (spell) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'action-spell-btn';
            const cost = (spell.mp_cost != null) ? spell.mp_cost : 0;
            let label = (spell.name || spell.spell_id || 'Spell') + ' (' + cost + ' MP)';
            const castable = !!spell.castable;
            if (!castable) {
                btn.classList.add('action-spell-disabled');
                btn.disabled = true;
                if (!spell.usable_out_of_combat) {
                    label += ' — combat only';
                } else {
                    label += ' — not enough MP';
                }
            }
            btn.textContent = label;
            if (castable) {
                btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    castExplorationSpell(spell);
                });
            }
            spellsListEl.appendChild(btn);
        });
    }

    function renderGrid() {
        if (!gridEl) {
            return;
        }
        gridEl.innerHTML = '';
        for (let i = 0; i < SLOT_COUNT; i++) {
            const item = lastInventory[i] || null;
            const slot = document.createElement('button');
            slot.type = 'button';
            slot.className = 'inventory-slot';
            slot.dataset.slot = String(i);
            if (item) {
                slot.classList.add('inventory-slot-filled');
                if (viewingItem && viewingItem.instance_id === item.instance_id) {
                    slot.classList.add('inventory-slot-selected');
                }
                if (item.equipped) {
                    slot.classList.add('inventory-slot-equipped');
                }
                let aria = appendSlotName(slot, item);
                if (item.equipped) {
                    const eq = document.createElement('span');
                    eq.className = 'inventory-slot-equipped-label';
                    eq.textContent = 'Equipped';
                    slot.appendChild(eq);
                }
                if (item.lit) {
                    const lit = document.createElement('span');
                    lit.className = 'inventory-slot-lit-label';
                    lit.textContent = 'Lit';
                    slot.appendChild(lit);
                }
                if (item.equipped) {
                    aria += ' (Equipped)';
                }
                if (item.lit) {
                    aria += ' (Lit)';
                }
                slot.setAttribute('aria-label', aria);
                slot.addEventListener('pointerdown', function (e) {
                    onSlotPointerDown(e, i, item, slot);
                });
                slot.addEventListener('click', function (e) {
                    if (suppressClick) {
                        e.preventDefault();
                        suppressClick = false;
                        return;
                    }
                    viewingItem = item;
                    render();
                });
            } else {
                slot.classList.add('inventory-slot-empty');
                slot.setAttribute('aria-label', 'Empty slot');
                slot.textContent = '';
            }
            gridEl.appendChild(slot);
        }
    }

    function clearHold() {
        if (holdTimer) {
            clearTimeout(holdTimer);
            holdTimer = null;
        }
        pendingHold = null;
    }

    function onSlotPointerDown(e, slotIndex, item, slotEl) {
        if (e.button != null && e.button !== 0) {
            return;
        }
        e.preventDefault();
        clearHold();
        const startX = e.clientX;
        const startY = e.clientY;
        pendingHold = {
            x: startX,
            y: startY,
            slot: slotIndex,
            item: item,
            el: slotEl,
            pointerId: e.pointerId,
        };
        holdTimer = setTimeout(function () {
            const pending = pendingHold;
            holdTimer = null;
            pendingHold = null;
            if (!pending) {
                return;
            }
            beginDrag(
                pending.slot,
                pending.item,
                pending.el,
                pending.x,
                pending.y,
                pending.pointerId
            );
        }, HOLD_MS);
        try {
            slotEl.setPointerCapture(e.pointerId);
        } catch (err) { /* ignore */ }
    }

    function beginDrag(slotIndex, item, slotEl, x, y, pointerId) {
        if (!item) {
            return;
        }
        drag = {
            from: slotIndex,
            item: item,
            pointerId: pointerId,
            startX: x,
            startY: y,
            over: slotIndex,
        };
        suppressClick = true;
        slotEl.classList.add('inventory-slot-dragging');
        ghostEl = document.createElement('div');
        ghostEl.className = 'inventory-drag-ghost';
        ghostEl.textContent = item.name || item.type_id || 'Item';
        const rect = slotEl.getBoundingClientRect();
        ghostEl.style.width = rect.width + 'px';
        ghostEl.style.height = rect.height + 'px';
        document.body.appendChild(ghostEl);
        moveGhost(x, y, rect.width, rect.height);
        highlightDrop(slotIndex);
        if (navigator.vibrate) {
            try { navigator.vibrate(12); } catch (err) { /* ignore */ }
        }
    }

    function moveGhost(x, y, w, h) {
        if (!ghostEl) {
            return;
        }
        const width = w || ghostEl.offsetWidth || 72;
        const height = h || ghostEl.offsetHeight || 52;
        ghostEl.style.left = (x - width / 2) + 'px';
        ghostEl.style.top = (y - height / 2) + 'px';
    }

    function slotFromPoint(x, y) {
        const el = document.elementFromPoint(x, y);
        if (!el || !gridEl) {
            return null;
        }
        const slot = el.closest ? el.closest('.inventory-slot') : null;
        if (!slot || !gridEl.contains(slot)) {
            return null;
        }
        const idx = parseInt(slot.dataset.slot, 10);
        return Number.isFinite(idx) ? idx : null;
    }

    function highlightDrop(index) {
        if (!gridEl) {
            return;
        }
        const slots = gridEl.querySelectorAll('.inventory-slot');
        slots.forEach(function (el) {
            el.classList.toggle(
                'inventory-slot-drop-target',
                parseInt(el.dataset.slot, 10) === index
            );
        });
    }

    function onPointerMove(e) {
        if (pendingHold && !drag) {
            const dx = e.clientX - pendingHold.x;
            const dy = e.clientY - pendingHold.y;
            if ((dx * dx + dy * dy) > (MOVE_CANCEL_PX * MOVE_CANCEL_PX)) {
                clearHold();
            }
        }
        if (!drag) {
            return;
        }
        e.preventDefault();
        moveGhost(e.clientX, e.clientY);
        const over = slotFromPoint(e.clientX, e.clientY);
        drag.over = over;
        highlightDrop(over);
    }

    function onPointerUp(e) {
        const wasDragging = !!drag;
        const fromSlot = drag ? drag.from : null;
        const toSlot = wasDragging ? slotFromPoint(e.clientX, e.clientY) : null;
        clearHold();
        if (!wasDragging) {
            return;
        }
        endDrag();
        suppressClick = true;
        setTimeout(function () {
            suppressClick = false;
        }, 50);
        if (toSlot == null || toSlot === fromSlot) {
            render();
            return;
        }
        applyMove(fromSlot, toSlot);
    }

    function applyMove(fromSlot, toSlot) {
        const moved = lastInventory[fromSlot];
        if (!moved) {
            render();
            return;
        }
        lastInventory[fromSlot] = lastInventory[toSlot] || null;
        lastInventory[toSlot] = moved;
        render();
        if (typeof window.socket !== 'undefined' && window.socket) {
            window.socket.emit('reorder_inventory', {
                from_slot: fromSlot,
                to_slot: toSlot,
            });
        }
    }

    function endDrag() {
        clearHold();
        if (ghostEl && ghostEl.parentNode) {
            ghostEl.parentNode.removeChild(ghostEl);
        }
        ghostEl = null;
        drag = null;
        pendingHold = null;
        if (gridEl) {
            gridEl.querySelectorAll('.inventory-slot-dragging, .inventory-slot-drop-target')
                .forEach(function (el) {
                    el.classList.remove('inventory-slot-dragging');
                    el.classList.remove('inventory-slot-drop-target');
                });
        }
    }

    function itemImageUrl(item) {
        if (typeof ItemAssets !== 'undefined') {
            return ItemAssets.getUrl(item.type_id, item.image);
        }
        return item.image || '/static/items/sprites/placeholder.png';
    }

    function renderDetail(item) {
        if (!detailEl) {
            return;
        }
        detailEl.innerHTML = '';

        if (!item) {
            detailEl.hidden = true;
            return;
        }

        detailEl.hidden = false;

        const iconWrap = document.createElement('div');
        iconWrap.className = 'inventory-detail-icon-wrap';

        const meta = document.createElement('div');
        meta.className = 'inventory-detail-meta';

        const img = document.createElement('img');
        img.className = 'inventory-detail-icon';
        img.alt = item.name || item.type_id || 'item';
        img.src = itemImageUrl(item);
        img.onerror = function () {
            img.onerror = null;
            img.src = (typeof ItemAssets !== 'undefined')
                ? ItemAssets.getPlaceholder()
                : '/static/items/sprites/placeholder.png';
        };
        iconWrap.appendChild(img);

        const name = document.createElement('div');
        name.className = 'inventory-detail-name';
        name.textContent = item.name || item.type_id || 'Unknown';

        const desc = document.createElement('p');
        desc.className = 'inventory-detail-desc';
        desc.textContent = item.description || '';

        const price = document.createElement('p');
        price.className = 'inventory-detail-price';
        const pqg = (item.price_pqg != null) ? item.price_pqg : 0;
        price.textContent = pqg + ' PQG';

        meta.appendChild(name);
        meta.appendChild(desc);
        meta.appendChild(price);
        if (item.light_remaining != null) {
            const fuel = document.createElement('p');
            fuel.className = 'inventory-detail-fuel';
            fuel.textContent = String(item.light_remaining);
            meta.appendChild(fuel);
        }
        if (item.lit) {
            const lit = document.createElement('p');
            lit.className = 'inventory-detail-lit';
            lit.textContent = 'Lit';
            meta.appendChild(lit);
        }
        if (item.equipped) {
            const eq = document.createElement('p');
            eq.className = 'inventory-detail-equipped';
            eq.textContent = 'Equipped';
            meta.appendChild(eq);
        }

        const actions = document.createElement('div');
        actions.className = 'inventory-detail-actions';
        actionsForItem(item).forEach(function (spec) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'inventory-use-btn';
            if (spec.id === 'discard') {
                btn.classList.add('inventory-action-discard');
            }
            btn.textContent = spec.label;
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                runAction(spec.id, item);
            });
            actions.appendChild(btn);
        });

        detailEl.appendChild(iconWrap);
        detailEl.appendChild(meta);
        detailEl.appendChild(actions);
    }

    function runAction(actionId, item) {
        if (!item || !item.instance_id || !actionId) {
            return;
        }
        if (typeof window.socket === 'undefined' || !window.socket) {
            return;
        }
        if (actionId === 'unequip') {
            confirmUnequipAction(item);
            return;
        }
        emitInventoryAction(actionId, item);
    }

    function confirmUnequipAction(item) {
        const cat = String(item.category || 'item').toLowerCase();
        const kind = cat === 'armour' ? 'armour' : 'weapon';
        if (typeof InspectUI !== 'undefined' && InspectUI.showConfirm) {
            InspectUI.showConfirm('This ' + kind + ' is currently equipped.', {
                confirmLabel: 'Unequip',
                cancelLabel: 'Cancel',
                onConfirm: function () {
                    emitInventoryAction('unequip', item);
                },
            });
            return;
        }
        emitInventoryAction('unequip', item);
    }

    function emitInventoryAction(actionId, item) {
        window.socket.emit('inventory_action', {
            instance_id: item.instance_id,
            action: actionId,
        });
        if (actionId === 'use' && context === 'combat') {
            close();
            return;
        }
        if (actionId === 'discard') {
            const idx = lastInventory.findIndex(function (row) {
                return row && row.instance_id === item.instance_id;
            });
            if (idx >= 0) {
                lastInventory[idx] = null;
            }
            viewingItem = null;
            render();
        }
    }

    function useItem(item) {
        runAction('use', item);
    }

    return {
        open: open,
        close: close,
        hide: hide,
        handleEscape: handleEscape,
        isOpen: isOpen,
        setInventory: setInventory,
        getInventory: getInventory,
    };
})();

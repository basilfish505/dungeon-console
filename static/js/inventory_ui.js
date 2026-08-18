// inventory_ui.js — 16-slot pack; hold-and-drag to reorder
const InventoryUI = (function () {
    const SLOT_COUNT = 16;
    const HOLD_MS = 280;
    const MOVE_CANCEL_PX = 14;
    // Add future pack verbs here (equip, give, drop, …). Server must accept the id.
    const ITEM_ACTIONS = [
        { id: 'use', label: 'Use' },
        { id: 'discard', label: 'Discard' },
    ];

    let overlayEl = null;
    let gridEl = null;
    let detailEl = null;
    let titleEl = null;
    let context = 'exploration';
    let lastInventory = [];
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

    function open(opts) {
        cacheDom();
        if (!overlayEl) {
            return;
        }
        opts = opts || {};
        context = opts.context || 'exploration';
        selectable = !!opts.selectable;
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
            titleEl.textContent = context === 'combat' ? 'Use Item' : 'Items';
        }
        renderGrid();
        renderDetail(viewingItem);
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
                slot.textContent = item.name || item.type_id || 'Item';
                slot.setAttribute('aria-label', slot.textContent);
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

        const iconWrap = document.createElement('div');
        iconWrap.className = 'inventory-detail-icon-wrap';

        const meta = document.createElement('div');
        meta.className = 'inventory-detail-meta';

        if (!item) {
            const placeholder = document.createElement('div');
            placeholder.className = 'inventory-detail-icon inventory-detail-icon-empty';
            placeholder.setAttribute('aria-hidden', 'true');
            iconWrap.appendChild(placeholder);
            detailEl.appendChild(iconWrap);
            detailEl.appendChild(meta);
            return;
        }

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

        const actions = document.createElement('div');
        actions.className = 'inventory-detail-actions';
        ITEM_ACTIONS.forEach(function (spec) {
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
